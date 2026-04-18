---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Memory Hygiene

## When to use

Use this skill when working on memory hygiene. (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**Cheap wins only, on a regular cadence.** Memory hygiene is flossing — small, routine, boring, cumulative. Not a quarterly refactor. If a fix takes a meaningful design change or measurable performance tradeoff, file it as a separate task; don't bundle it into the hygiene pass.

## When To Run

- **On-demand when `/capacity.html` goes `warn` or `urgent`** — every chat audits its own code.
- **Once a week as routine** — each chat picks one day and does a pass, even if nothing's red.
- **Before a heavy new feature** — check you're not already bloated before adding more.

## The Audit Checklist

Walk through these. Each item takes < 5 min to check.

### 1. Streaming vs bulk loads
- [ ] Any `pd.read_sql("SELECT * FROM t")` or `.fetchall()` on a table > 10k rows → convert to `chunksize=` or cursor iteration.
- [ ] `json.load(huge_file)` or `f.read()` on files > 50 MB → stream with `ijson` / line-by-line iteration.
- [ ] Loading a whole directory of files into memory before processing → iterate instead.

### 2. Open handles
- [ ] Every file / DB / HTTP client opened is closed (`with` blocks, not bare `open()`).
- [ ] SQLite connections are closed after use, not cached forever in module globals.
- [ ] Playwright browser / context / page objects closed in `finally:` blocks.

### 3. SQLite quick wins
- [ ] `PRAGMA journal_mode=WAL` for write-heavy DBs (reduces lock contention).
- [ ] `PRAGMA wal_checkpoint(TRUNCATE)` periodically — WAL files grow unbounded without it.
- [ ] `VACUUM` after bulk deletes.
- [ ] `PRAGMA cache_size = -50000` (50 MB cache) instead of the 2 MB default if you have the RAM; `-10000` (10 MB) if you don't. Negative = KB.
- [ ] `PRAGMA mmap_size = 134217728` (128 MB) for read-heavy DBs lets the kernel page-manage cache.

### 4. Pandas
- [ ] Chained `.copy()` / `.assign()` / `.apply()` that each duplicates the frame → combine with in-place ops or a single assign.
- [ ] Object-dtype columns holding short strings → cast to `category` where cardinality is low.
- [ ] `astype('int64')` columns that fit in `int32` / `int16` → downcast.
- [ ] Keeping the raw DataFrame after transforming it → `del raw; gc.collect()`.

### 5. Long-running processes
- [ ] Watchers / daemons that read into a list forever → bound the list, or rotate to disk.
- [ ] Caches with no eviction → add an LRU bound (`functools.lru_cache(maxsize=...)`).
- [ ] Log handlers without rotation → add `logging.handlers.RotatingFileHandler`.
- [ ] Streamlit / Flask processes that grow slowly → add a periodic `gc.collect()` or a restart-on-memory-threshold systemd directive.

### 6. Browser automation
- [ ] Playwright contexts not closed after each test → `browser.new_context()` → `context.close()` per scenario.
- [ ] Persistent user-data-dirs growing unbounded → periodic purge.
- [ ] Multiple concurrent browsers when one serial run would do.

### 7. Caches on disk (RAM proxy)
- [ ] Raw source files kept alongside parsed outputs → gzip or delete.
- [ ] Logs not rotated / compressed.
- [ ] Test artifacts (screenshots, traces) not cleaned.

## What NOT To Touch In A Hygiene Pass

These are real wins but aren't "basic hygiene." File as separate tasks:

- Database schema changes (partitioning, column pruning).
- Moving data to external storage (S3, Spaces).
- Switching libraries (e.g., DuckDB over SQLite).
- Rewriting in a lower-level language.
- Adding a cache layer (Redis, memcached).

If you find yourself wanting to do one of these, stop, file the task, and move on to the next cheap-win.

## How To Measure Before / After

Tiny overhead, honest signal:

```python
import resource, os
print(f"RSS before: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.1f} MB")
# ... work ...
print(f"RSS after:  {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.1f} MB")
```

For a service, compare peak RSS in `systemctl status <service>` before/after a deploy.

For the platform overall: note `curl -s https://casinv.dev/capacity.json | jq .ram.pct` before and after the pass.

## Output Of A Pass

After each hygiene pass, a short entry in the project's `PROJECT_STATE.md`:

> **Memory hygiene 2026-04-14:** Found X wins (list). Shipped Y. Deferred Z as separate tasks. Peak RSS dropped/unchanged.

If a single pass found zero wins *and* a prior pass found many, that's a signal the prior work is holding up. If zero wins three times in a row, the checklist has probably gone stale — update it.

## Integration

- Companion skills: `SKILLS/capacity-monitoring.md` (triggers on-demand audits), `SKILLS/root-cause-analysis.md` (when investigating a memory incident, start here).
- This is platform stewardship applied to memory — per `SKILLS/platform-stewardship.md`, regular small improvements compound.
