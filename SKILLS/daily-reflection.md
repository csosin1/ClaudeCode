# Skill: Daily Reflection

## Guiding Principle

**The platform has to get better with each day, not just each task.** The stewardship rule said every session leaves an improvement; the reflection is the forcing function that makes sure it actually does. One file per active day, committed to `reflections/YYYY-MM-DD.md` in site-deploy. Honest, specific, useful.

## When To Use

- **Every active day**, authored by the orchestrator chat at end-of-day. Cron at 23:00 UTC fires a notify reminder.
- **After any material incident**, even mid-day — don't wait for the regular slot if something serious happened.
- **User-triggered**, whenever they ask "what did we learn today?" / "do today's reflection" / similar.

A day with no material activity doesn't need one. Use judgment — "I edited two READMEs and one CSS rule" is not a reflection day.

## The Template

Copy this skeleton. Fill it with specifics, not platitudes. Past reflections in `reflections/*.md` are your reference.

```markdown
# Daily Reflection — YYYY-MM-DD

_Authored by <chat name>, covering <time window>._

## What shipped
- Commits, SKILLS added/updated, CLAUDE.md changes, infrastructure built.
- Project-level outcomes (data loaded, features shipped, handoffs completed).
- Keep to bullets with concrete names / numbers. Not "various improvements."

## What broke or degraded
- Per incident: symptom → root cause → fix shipped → preventive rule.
- Include silent degradations (capacity drift, skill that was wrong, doc that misled).
- If something broke and was NOT RCA'd, surface that — it's a debt item.

## Patterns I'm noticing
- Things that happened more than once.
- Tools / skills / docs that keep coming up.
- Friction points agents worked around instead of fixing.
- Positive patterns too: what's compounding well?

## External best practices worth considering
- Things the industry does that we don't, where adoption might pay off.
- Be specific: name the practice, say why it might fit us, note cost.
- Mark "probably overkill" explicitly — surfacing and rejecting is still useful.

## Concrete improvements to propose (ranked by leverage)
- Each proposal: one paragraph.
- Leverage (high/medium/low) and effort (low/medium/high) called out.
- Link to open questions they resolve.

## What I'd do differently if today restarted
- Sequencing mistakes ("should have built X before Y").
- Scope mistakes ("spent 2 hrs on a thing that didn't matter").
- Discipline mistakes ("added a CLAUDE.md section I shouldn't have").

## Rule / skill proposals graduating to work items
- Bullet list of the concrete things that should become tasks / commits from this reflection.
- Each links back to a section above.
```

## How To Research Best Practices

Don't over-engineer this. A single session of structured thinking:

- **What felt clunky today?** That's usually the honest best-practice trigger. "We did X manually three times" → research automation patterns.
- **What did industry peers solve that looks analogous?** SRE practices for service-uptime concerns; agent-orchestration patterns (Langchain / MCP / Claude Agent SDK patterns); DevOps conventions for deploy / rollback / observability.
- **Don't import wholesale.** A pattern that works at Netflix's scale often doesn't fit a solo-operator droplet. Scale-match explicitly.
- **Web search is OK for research.** When you want to check current state of a technique, it's fine to pull a couple of authoritative references. Don't build a research report — one or two references that inform a proposal is enough.

Be honest about what's working. Boosting the signal on things that compound (other chats shipping skills, user actions discovered that would otherwise be buried) matters as much as calling out failures.

## Output Flow

1. Write the reflection to `/opt/site-deploy/reflections/YYYY-MM-DD.md`.
2. Commit with message `reflection: YYYY-MM-DD — <one-line theme>`. Push.
3. If any proposals graduated to immediate work items, file them as `TaskCreate` entries or ship them in the same commit where appropriate.
4. Notify the user with `notify.sh` priority `default`, click-URL to the file on GitHub (since no /reflections.html yet — TODO: add one if this practice sticks).

## Anti-Patterns

- **Platitudes.** "We made good progress today" is worthless. Name what shipped, by commit SHA or file path.
- **Blame-free at the cost of specificity.** "Something went wrong in the pipeline" is a cop-out. Name the module and the decision chain that led there.
- **Reflection as homework.** If it's become a checkbox, delete the template line you're struggling to fill and keep the rest. A good 3-section reflection beats a padded 7-section one.
- **Reflecting in private.** Commit to the repo. Future agents read past reflections as context.
- **Same proposals every day.** If a concrete improvement has been in three reflections without shipping, either ship it or kill it.

## Cadence Reminder Mechanism

Cron at 23:00 UTC (covers most active-session timezones):
```
0 23 * * * root /usr/local/bin/notify.sh "Daily reflection time — reflections/$(date -u +%Y-%m-%d).md" "Platform reflection" default "https://github.com/csosin1/ClaudeCode/tree/main/reflections"
```

The active orchestrator chat sees this and produces the file. If no orchestrator is active, the notify is a gentle prompt to spawn / re-engage one.

## Integration

- `SKILLS/platform-stewardship.md` — reflections are stewardship at a coarser grain. Every reflection's "proposals graduating" feeds the stewardship flywheel.
- `SKILLS/root-cause-analysis.md` — incidents captured in reflections should already have `LESSONS.md` entries; the reflection summarizes, not replaces.
- `SKILLS/session-resilience.md` — if the orchestrator chat can't be reached when reflection is due, any sibling chat with the state files can pick it up.
