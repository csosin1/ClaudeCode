# SQLite across multiple writers — avoid WAL

## Purpose
Any project where a SQLite file is written by more than one process (a long-lived service + operator CLI tools + a background worker) needs to be careful about `journal_mode`. WAL's speed wins come with a subtle failure mode that silently eats data when processes restart uncleanly.

## The trap
`journal_mode = WAL` is the default recommendation for most SQLite deployments — it's fast, it allows concurrent reads during writes, it's the right answer for a single-process-writes scenario (one server + many readers). Every tutorial reaches for it.

But WAL writes go to `<db>.db-wal` first, and only land in the main `.db` file on **checkpoint**. Checkpoints happen either automatically (every ~1000 pages) or when the last connection closes. If three different processes write concurrently:

1. Service opens DB at startup, begins writing rows to WAL.
2. Operator CLI runs `node -e "insertOffer(...)"` — opens DB, writes to the *same* WAL file, closes.
3. Service restarts (deploy, SIGTERM). Its open WAL entries may not be checkpointed.
4. New service instance opens DB — sees main db file, sees WAL file, tries to recover.
5. If the WAL's state is inconsistent (split writes, missing pages, truncated on improper close), recent writes silently disappear. The newly-opened DB looks "fresh minus some rows."

Hours of silent data loss, no error messages.

## The fix
Use `journal_mode = DELETE` (SQLite's default, pre-WAL). Every COMMIT lands in the main `.db` file immediately via a brief exclusive lock. Standard file-locking serializes writes across any number of handles:

```js
const db = new Database(path);
db.pragma('journal_mode = DELETE');
db.pragma('synchronous = FULL');  // trade throughput for durability
```

You trade ~2–5× write throughput for absolute durability. At our typical load (tens of writes/second), this is invisible.

## When to prefer WAL anyway
- **Single process, many threads/connections.** A Node service with a connection pool; a Python app with several workers; a Go service. These all share one OS process and its transaction log behaves cleanly. WAL is the right answer here.
- **Read-heavy workloads where concurrent reads during a write matter.** WAL lets readers proceed without blocking; DELETE mode doesn't. Not relevant if you're writing infrequently.

## When to NEVER use WAL
- Service + operator CLI scripts that each open their own handle.
- Service + cron scripts that write to the DB.
- Multi-process workers.
- Anywhere a developer can run `sqlite3 the.db 'INSERT...'` or `node -e 'insertOffer(...)'` against a live db.

## Other precautions (orthogonal to journal_mode)

- **Short-interval backup cron.** `*/10 * * * * cp the.db backups/the-$(date +%Y%m%d-%H%M).db` takes 2 seconds to set up and makes every wipe recoverable. Install on day one.
- **Never keep live db files inside your rsync destination for a deploy pipeline.** Put them in a sibling path: `/opt/project-data/db/` or similar. If the deploy ever accidentally fails the exclude, the data is nowhere near the target.
- **Don't name your dev scratch db the same as prod.** We had `/opt/site-deploy/car-offers/offers.db` (dev scratch from CLI tests) sitting right next to the source dir that gets rsynced to runtime. Rsync excluded `*.db`, but one typo in the exclude would have copied scratch over prod.

## Reference implementation
`car-offers/lib/offers-db.js` after commit 448190d — canonical example of journal_mode=DELETE + synchronous=FULL + a 10-min backup cron. Any new project copying its offers-db pattern inherits the safe defaults.

## Failure-mode signatures to recognize
- "The database seems to reset every time I deploy."
- "Rows I inserted via CLI are missing after a service restart."
- Service logs show "database disk image is malformed" on startup.
- `.db-wal` file sitting alongside `.db` with a newer mtime than `.db`, and you just restarted.

All of these point at a concurrent-writer WAL race. Move to DELETE mode.
