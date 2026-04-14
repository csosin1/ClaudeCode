# Lessons Learned

Append an entry when something breaks in a way that wasn't obvious from the code. Builders and Reviewers read this before starting a task.

## Format

```
## [YYYY-MM-DD] [short title]
- **What went wrong:**
- **Root cause:**
- **What to do differently:**
```

## 2026-04-14 — CarMax disabled CTA uses a CSS class, not the HTML attribute

- **What went wrong:** The CarMax `/sell-my-car` wizard filled every field correctly (mileage, email, 13 radio groups) but the final "Get My Offer" click was a no-op, so the wizard looped stuck=3 and returned `status=error`. A Playwright debug capture showed the button WAS enabled (form valid) at that point.
- **Root cause:** CarMax's primary submit button is `<button id="ico-continue-button">`. When the form is incomplete, CarMax does NOT set the `disabled` HTML attribute and does NOT set `aria-disabled="true"`. Instead, it ADDS the literal CSS class `disabled` to the button's className. Our selector `button:has-text("Get My Offer"):not([disabled]):not([aria-disabled="true"])` didn't filter that out. Worse, there's a second `<button type="submit">Get my offer</button>` in the hero intake form at the top of the page (lowercase variant) that matches the same has-text pattern — the old code hit that one first, silently re-submitted the already-submitted hero form, and never touched `#ico-continue-button`.
- **What to do differently:** When a site's advance button looks enabled by attribute but clicks do nothing, inspect `className`. Many SPAs use CSS classes (e.g. `.disabled`, `.is-disabled`, `.btn-disabled`) to gate click handlers rather than the HTML disabled attribute. Target the button by its stable ID when present, read `className` via `page.evaluate`, and fall back to text-based matching with `:not(.disabled)` added to the selector. Also: never assume two buttons with similar text are the same thing — hero intake forms often shadow the main form's CTA text.

## 2026-04-14 — Driveway "Whoops" modal is a proxy-reputation signal, not a selector bug

- **What went wrong:** Driveway's `/sell-your-car` wizard successfully switched to the VIN tab (`data-testid="vin-tab"`), filled the VIN input (`id="vinInput"`), and submitted; the VIN was validated (green `valid-icon` appeared). Then the site popped an MUI Dialog with a friendly "Whoops! Something went wrong on our end" message and the wizard dead-ended. This behavior was consistent across every panel consumer.
- **Root cause:** The modal's title span has `id="modal-title"` containing `Whoops!` — not a validation error. Driveway's backend accepts the POST, flags it as suspicious (proxy IP reputation + low-entropy fingerprint), and returns a generic 500 that the frontend renders as this modal. The captures show the modal appears within ~1 second of submit; that's too fast to be a real outage.
- **What to do differently:** For any auto-buyer with an "aw shucks" generic error right after VIN submit, don't waste time tweaking selectors. The leverage is in rotating the proxy session (fresh Decodo sticky-session ID) and/or warming cookies on unrelated pages first. We now delete the `.proxy-sessions/<consumer>.json` file before a retry so `getOrCreateProxySession` issues a new suffix, which changes the upstream sticky-session ID inside the Decodo proxy user-string. Deeper fix if this keeps happening: rotate the whole consumer (new fingerprint + new zip), or pre-bake warm cookies by browsing shop pages for 10 min before the sell flow.

## 2026-04-14 — Node require-cache: copying files into /opt/<project>/lib is not enough; systemctl restart is required

- **What went wrong:** During this task I edited wizard files under /opt/site-deploy/, cp'd them to the preview service's lib dir, and expected the next `POST /api/carmax` to pick up the changes. It didn't — the service kept running the OLD wizard because Node caches required modules in-process.
- **Root cause:** `require('./lib/carmax')` resolves once per process. The server's `getOffersDb` and wizard modules are lazy-loaded but only on first use; subsequent calls return the cached module object. Editing the file on disk doesn't invalidate the cache.
- **What to do differently:** After any wizard-file change on the droplet, `systemctl restart car-offers-preview` (or `car-offers`). The preview's auto-deploy pipeline already does this when a git push hits main; manual copies need a manual restart. Alternatively: cache-bust in server.js via `delete require.cache[require.resolve('./lib/carmax')]` before each call — but that hides bugs where wizard state bleeds across runs, so restart is safer.

## 2026-04-14 — Only edit code in a git worktree on this droplet; /opt/site-deploy is shared

- **What went wrong:** Made wizard edits directly in `/opt/site-deploy/` (on a feature branch). A parallel agent in another window reset `/opt/site-deploy`'s HEAD back to origin/main to switch to a different branch, wiping all my uncommitted changes. Then the auto-deploy pipeline rsynced the vanilla main over `/opt/car-offers-preview/lib/`, taking my already-copied changes out of the runtime too.
- **Root cause:** `/opt/site-deploy` is a SINGLE git checkout shared by the deploy pipeline and every agent. `git checkout <branch>` in one window mutates the working tree for every other window. Even if you're on your own branch, another process can switch away — especially automated deploy flows reacting to webhook pushes on unrelated projects.
- **What to do differently:** For any non-trivial multi-file change, IMMEDIATELY create a worktree: `git worktree add /opt/worktrees/<name> -b claude/<branch>`. Edit there. `/opt/site-deploy` is effectively read-only from an agent's perspective — it belongs to the deploy pipeline. When you're done, either push the branch and let the deploy pipeline take over, or copy the files into place AND restart the service, AND commit before any other agent can pull the rug out.

## 2026-04-13 — never POST to /api/setup from a builder without dry_run

- **What went wrong:** While testing the new /setup extension I ran a local Node instance in the worktree and POSTed a fake `{mturkAccessKeyId, ...}` body to `/api/setup`. The handler's sibling-mirror logic then wrote my fake values into `/opt/car-offers/.env` AND `/opt/car-offers-preview/.env`, wiping the real 18-char `PROXY_PASS` and the real `PROJECT_EMAIL` on both instances. When systemd restarted the services they booted with blank credentials.
- **Root cause:** Two problems compounded. (1) The handler's feature — mirroring to both sibling `.env` files — does exactly what it's supposed to but is unsafe in any test context where a bad test run can clobber real creds. (2) My local test node server was also bound to a port that the live service uses for its own workflow (3599 in this case), so stray `curl` calls from a terminal accidentally hit the wrong process.
- **What to do differently:** Any `POST /api/setup` test or local probe MUST pass `dry_run:true` (or `?dry_run=1`). The handler now honors this: it validates and returns the same shape but does not persist. Playwright tests in `tests/car-offers.spec.ts` all set `dry_run:true`. When you need to test the real persist path, do it against an isolated test directory — never point `__dirname` at or near `/opt/car-offers`. Recovery is possible (gcore + `strings | grep PROXY_PASS=` on the live node process) but only as long as the live service hasn't restarted yet.

## 2026-04-13 — patchright evaluate() runs in an isolated world

- **What went wrong:** Wrote a fingerprint unit test that set `window.__fp = result` from a `<script>` tag in the page, then read it back via `await page.evaluate(() => window.__fp)`. Always returned `undefined`, even though `document.title` (set on the same line) reflected the change.
- **Root cause:** Patchright (and Playwright with `useWorld: 'utility'`) runs `page.evaluate` in an *isolated* world — the same DOM, but a separate JS global object. `window.__fp` set in the page's main world is NOT visible to `evaluate`. Patchright does this by default to avoid the CDP `Runtime.enable` leak.
- **What to do differently:** When a fixture script must communicate with Node, write to a DOM attribute (`document.body.setAttribute('data-fp', JSON.stringify(out))`) and read it from Node via `page.getAttribute('body', 'data-fp')`. DOM is shared; window globals are not.

## 2026-04-13 — Object.defineProperty on Navigator.prototype isn't enough alone

- **What went wrong:** Stealth init script used `Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', { get: () => 12 })` to spoof CPU count. Page still saw `2` (the patchright-injected value).
- **Root cause:** Navigator instances can have own-properties that shadow the prototype. Patchright (and likely Playwright itself) installs an own-property on `navigator` for some fields. A prototype-only override loses to an own-property.
- **What to do differently:** Always override at BOTH levels — `Object.defineProperty(Navigator.prototype, name, ...)` AND `Object.defineProperty(navigator, name, ...)` — and make both `configurable: true` so the second call doesn't throw. Helper:
  ```js
  const defNav = (name, value) => {
    try { Object.defineProperty(Navigator.prototype, name, { get: () => value, configurable: true }); } catch(e){}
    try { Object.defineProperty(navigator, name, { get: () => value, configurable: true }); } catch(e){}
  };
  ```

## 2026-04-13 — `addInitScript` + `+`-concatenated try/catch is fragile

- **What went wrong:** Built the stealth init script as one giant `'try { ... ' + 'foo;' + 'bar;' + '} catch(e){}'` string concatenation. Page silently ignored the script — `window.__stealthApplied = true` (the very first statement) was never set, but no error surfaced because `addInitScript` swallows page-side syntax errors silently.
- **Root cause:** The script had a syntax error (a try without a matching catch on the same logical line) but `addInitScript` runs the script via `eval`-style injection and a syntax error means *the whole script never runs*, with no error propagated to Node. There's no console listener early enough to catch it either.
- **What to do differently:** (1) Build the init script as a single template literal with real newlines, not string concatenation. (2) Always validate the generated script's syntax in Node BEFORE injecting: `try { new Function(scriptStr); } catch(e) { throw new Error('init script syntax: ' + e.message); }`. (3) Add a marker statement at the very top of the init script (`window.__stealthApplied = true`) so tests can verify the script ran at all, separately from verifying individual patches.

## 2026-04-13 — concurrent agent sessions racing on a shared git worktree

- **What went wrong:** Mid-edit, the local branch repeatedly reset itself, files reverted to older content, and `cd` between bash invocations would land on a different branch than the prior command was on. Ate ~30k tokens of unnecessary cherry-picks and stash dances.
- **Root cause:** Multiple parallel Claude sessions were running in different tmux windows against the same `/opt/site-deploy/` worktree. Each session was checking out its own branch, blowing away in-flight work in the other sessions' working tree.
- **What to do differently:** Long multi-file edits in shared-worktree environments should (a) commit-and-push aggressively after each logical chunk so origin survives the race, (b) use `git worktree add` to spin up a per-session worktree, or (c) do all writes + commit in one atomic Bash invocation chained with `&&`. Option (a) is the cheapest and worked here.
