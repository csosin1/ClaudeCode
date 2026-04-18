---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Python Script Path Hygiene (avoid /tmp/ shadowing stdlib)

## When to use

Use this skill when working on python script path hygiene (avoid /tmp/ shadowing stdlib). (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## What this is about
CPython prepends the script's own directory to `sys.path[0]`. If any `.py` file in that directory has the same name as a stdlib module (`inspect.py`, `types.py`, `json.py`, `random.py`, etc.), it **shadows** the stdlib module — which silently breaks imports deep inside packages that depend on the stdlib version.

`/tmp/` is the most common footgun: stray `.py` files from other projects or debugging sessions accumulate there, and any Python script you later launch from `/tmp/` inherits their namespace.

## When this bites
- You run `python /tmp/my_script.py` and it crashes with an error like
  `AttributeError: module 'inspect' has no attribute 'signature'`
  inside a third-party package (`typing_extensions`, `bs4`, `pydantic`).
- The same script works fine from `/opt/project/` and you can't figure out why.
- Error appears deep in the import chain, nowhere near your code.

## When to use this skill
- Before writing a one-shot Python helper, ask: where does it live?
- When you see a baffling stdlib-attribute error that only reproduces from a specific directory.
- When auditing a project's launch scripts / cron jobs.

## The rule

**Never put Python scripts in `/tmp/`** (or any dir you don't own).  Put them in the repo root (`/opt/<project>/`) so `sys.path[0]` is a directory whose contents you control.

If you must run from `/tmp/`:
1. Use `python -I` (isolated mode) — disables `sys.path[0]` prepending plus several other user-site behaviors.
2. Or set `PYTHONSAFEPATH=1` before invocation (Python 3.11+) — same effect, just `sys.path[0]`.
3. Or `cd /opt/<project> && python -m my_module` — using `-m` means `sys.path[0]` is `''` (current dir), which you at least know.

Note: `cwd=/opt/<project>` alone is NOT sufficient. `sys.path[0]` comes from the SCRIPT's directory, not the process cwd.

## Minimum working example
```bash
# BAD — will pick up /tmp/inspect.py if it exists
cp my_helper.py /tmp/ && python /tmp/my_helper.py

# GOOD — pin sys.path[0] to your project
cp my_helper.py /opt/<project>/ && python /opt/<project>/my_helper.py

# GOOD — isolated mode if you really must run from /tmp
python -I /tmp/my_helper.py
```

## Detection / prevention
Add to health checks:
```bash
# Flag any long-running python process whose script is in /tmp
pgrep -al "python.*\s/tmp/" && echo "WARN: python running from /tmp — risk of stdlib shadowing"

# Scan /tmp for .py files with stdlib names
find /tmp -maxdepth 2 -name "*.py" -exec basename {} \; \
    | sort -u | grep -f <(python -c "import sys; print('\n'.join(sys.stdlib_module_names))")
```

## Incident reference
2026-04-14 abs-dashboard: reparse script at `/tmp/cmx_reparse.py` failed 3× before I spotted `/tmp/inspect.py` from another project. Cost ~15 min.  Moved script to `/opt/abs-dashboard/cmx_reparse.py`; immediately worked.  Full root-cause in `/opt/abs-dashboard/LESSONS.md`.
