# Skill: Session Resilience

## Guiding Principle

**Any remote chat session can fail at any time — including the orchestrator.** Build every chat to be recoverable. The failure modes are distinct, the recoveries are distinct, and a session that vanishes should produce at most two minutes of user disruption — never lost work.

## The Failure Modes (and what happens under each)

| Failure | What's lost | What survives | Recovery |
|---|---|---|---|
| **Remote-control URL goes stale** (Anthropic relay blips, slash-command fails) | UX access on user's phone | tmux session, claude process, JSONL, all running tool calls | Watchdog detects missing "Remote Control active" status, runs `reactivate-remote.sh`, refreshes bookmark. Auto-recovers within 1 min of cron. |
| **Claude CLI process crashes** (OOM, uncaught bug) | In-flight tool calls | JSONL on disk, tmux window (empty), data, commits | Respawn cron or boot service runs `claude-project.sh` with `--continue`; chat resumes from JSONL. ~30-60 s downtime. |
| **Tmux window killed** (accidental, process reap) | Same as above | JSONL, data | Same — respawn cron recreates within 5 min. |
| **Droplet reboots / resizes** | In-flight tool calls across all chats; ~60-120 s of bookmark blip | Everything on disk | `claude-respawn-boot.service` runs 15 s after `claude-tmux.service`; every expected project chat comes back with `--continue`. Bookmarks refresh as URLs are captured. |
| **JSONL file corruption** (rare — duplicate writers) | The corrupted session's chat history | Other chats' JSONLs, data | Manual: identify the good jsonl by line count / content, move the corrupted one aside, restart window with `--continue`. |
| **Orchestrator chat dies mid-orchestration** | In-flight orchestration decisions, in-memory state | Everything on disk — including `PROJECT_STATE.md`, `AUDIT_FINDINGS.md`, `CHANGES.md`, cron, all other chats | Any other chat can pick up orchestrator role by reading the state files. The respawn cron brings the dead orchestrator back within 5 min with full history. |

## The Three Mandatory Habits

Because any chat can die, every chat at all times must:

1. **Keep `PROJECT_STATE.md` current.** If a chat dies and a resume reads the JSONL, the last few messages may be mid-tool-call. `PROJECT_STATE.md` is the ground-truth handoff document. Update it when focus changes, decisions land, or new open questions emerge — not at the end of the day. "Every 30 min of active work or on any meaningful transition" is the cadence.

2. **Commit and push frequently during long work.** Uncommitted edits in a worktree are lost if the worktree gets trashed during recovery. Every ~10-15 min of real work: commit, push. Branches on origin are the backup.

3. **Don't hold load-bearing state in conversation memory.** If a number, decision, or intermediate result matters, write it to `PROJECT_STATE.md`, `AUDIT_FINDINGS.md`, `CHANGES.md`, or a JSON file — not "I'll remember." You might not.

## Automatic Resilience (what the platform does without you)

- **`claude-watchdog.sh`** (every minute): scans tmux panes for each expected project. Detects `Remote Control active` status. If missing, calls `reactivate-remote.sh` to re-issue `/remote-control` and refresh the bookmark. After 3 failed attempts, escalates `urgent` notify to user.
- **`claude-respawn.sh`** (every 5 min): checks every expected project has a live tmux window. If missing, runs `claude-project.sh` with `claude --continue`, which resumes from the most recent JSONL.
- **`claude-respawn-boot.service`** (on droplet boot, +15 s): brings every expected chat back after a reboot / resize.
- **`/etc/claude-projects.conf`** lists every expected chat. Add / remove / rename entries to reflect the current project roster.

## Manual Recovery Playbook

When a chat appears "lost" from the user's perspective:

1. **Don't assume death.** Check first:
   - `tmux list-windows -t claude -F '#I #W'` — window still alive?
   - `ps -ef | grep claude` — claude process still alive?
   - `curl -s https://casinv.dev/liveness.json` — what does the watchdog see?
   - `ps -ef | grep <project-process>` — any project-owned background work still running?

2. **Recover the cheapest thing first.** If the tmux window is alive but remote-control is stale, run `reactivate-remote.sh <project>`. User gets new URL by re-tapping their bookmark.

3. **If the chat process is dead but the JSONL is fine:** `claude-project.sh <project> <cwd>` (or wait for the 5-min respawn cron). `--continue` resumes from the JSONL. Full conversation preserved.

4. **If the user has truly lost UX access and wants to transfer context to a sibling chat:** see the "Handoff" section below.

5. **Background processes are independent.** Killing a chat does not kill its subprocesses (Python ingestions, Playwright drivers, etc.). Verify any ongoing work is still running via `ps` before assuming it's dead.

## Handoff Playbook (chat A → chat B)

When the user wants chat B to take over chat A's work:

**Option 1 (preserves full history — preferred if possible):**
1. Kill chat B's current tmux window (drop its fresh JSONL).
2. Move chat B's fresh JSONL aside (rename to `.bak`).
3. Kill chat A's tmux window so its writer is released.
4. Identify chat A's JSONL in `/root/.claude/projects/-<cwd-slug>/` (usually the largest/most-recent).
5. Spawn a new window named B with `claude --continue` (same CWD) — it picks up chat A's JSONL.
6. Activate `/remote-control`, update bookmark at `/var/www/landing/remote/B.html`.
7. Update `/etc/claude-projects.conf`: remove A, add/keep B.
8. Update `/opt/site-deploy/deploy/projects.html` PROJECTS key to match B.

**Option 2 (just transfers state summary — simpler):**
1. Build a handoff brief from chat A's `PROJECT_STATE.md`, `CHANGES.md`, recent commits, running processes.
2. Send the brief to chat B via `tmux send-keys`.
3. Chat B reads the brief, acks, continues.

Option 1 is better when full history matters (audits, long investigations, complex in-flight decisions). Option 2 is faster and cleaner when chat B can pick up from just the state files.

## Checking Your Own Resilience Before Going Deep

Before starting a multi-hour investigation or big batch job, spend 60 seconds:

- Is `PROJECT_STATE.md` current with today's plan? If not, write it.
- Is there any uncommitted work? Commit.
- Would someone reading just `PROJECT_STATE.md` + recent commits understand what you're doing and why? If not, fix the doc.
- Is the project in `/etc/claude-projects.conf`? If not and it's a stable project, add it.

This takes a minute and saves the user 18 minutes of "canoodling" and a painful handoff if you die mid-task.

## Anti-Patterns

- **Assuming "stuck" = "dead."** The watchdog says "stuck" when a single activity has run >10 min. That's a flag, not a verdict. Check the process list before killing anything.
- **Killing tmux windows to "reset" a misbehaving chat.** This loses in-flight tool calls unnecessarily. `Escape` to interrupt is almost always better than `tmux kill-window`.
- **Rebuilding context in conversation rather than from files.** If you're re-explaining the project to yourself in a long prompt because "I can't remember," the `PROJECT_STATE.md` failed you — fix that, don't work around it.
- **Hot-editing `/etc/claude-projects.conf` without testing.** A typo here can prevent boot respawn. `bash -n /usr/local/bin/claude-respawn.sh` catches nothing; check with `awk '!/^#/ && NF{print $1}' /etc/claude-projects.conf`.

## Integration

- `SKILLS/platform-stewardship.md` — resilience is stewardship for the lifecycle of a chat.
- `SKILLS/root-cause-analysis.md` — when a chat dies, RCA the cause (was it OOM? hang? specific tool? relay?) so it doesn't recur.
- `SKILLS/non-blocking-prompt-intake.md` — a dying chat with a queued user prompt should hand off rather than silently lose it.
- `SKILLS/capacity-monitoring.md` — capacity pressure is the most common underlying cause of chat deaths.
