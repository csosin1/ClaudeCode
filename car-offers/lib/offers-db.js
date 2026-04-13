/**
 * SQLite wrapper over offers.db.
 *
 * Schema (one row per site per comparison run):
 *   offers(id, run_id, vin, mileage, zip, condition, site, status,
 *          offer_usd, offer_expires, proxy_ip, ran_at, duration_ms,
 *          wizard_log)
 *
 * Exports:
 *   openDb(filePath?)           - returns a better-sqlite3 Database ready to use
 *   insertOffer(db, row)        - inserts a row; returns the inserted id
 *   getLatestByVin(db, vin)     - { carvana?, carmax?, driveway?, run_id?, ran_at? }
 *                                 latest offer per site for that VIN (any run)
 *   getRuns(db, limit=20)       - recent runs grouped by run_id
 */

const path = require('path');

const DEFAULT_DB_PATH = path.join(__dirname, '..', 'offers.db');
const SITES = ['carvana', 'carmax', 'driveway'];

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  vin TEXT NOT NULL,
  mileage INTEGER NOT NULL,
  zip TEXT NOT NULL,
  condition TEXT NOT NULL,
  site TEXT NOT NULL CHECK (site IN ('carvana','carmax','driveway')),
  status TEXT NOT NULL,
  offer_usd INTEGER,
  offer_expires TEXT,
  proxy_ip TEXT,
  ran_at TEXT NOT NULL,
  duration_ms INTEGER,
  wizard_log TEXT
);
CREATE INDEX IF NOT EXISTS idx_offers_vin ON offers(vin);
CREATE INDEX IF NOT EXISTS idx_offers_run ON offers(run_id);
CREATE INDEX IF NOT EXISTS idx_offers_site_vin_ran ON offers(site, vin, ran_at DESC);

CREATE TABLE IF NOT EXISTS consumers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  vin TEXT NOT NULL UNIQUE,
  year INTEGER,
  make TEXT,
  model TEXT,
  trim TEXT,
  mileage INTEGER NOT NULL,
  home_zip TEXT NOT NULL,
  condition TEXT NOT NULL DEFAULT 'Good',
  proxy_session_id TEXT NOT NULL UNIQUE,
  fingerprint_profile_id INTEGER NOT NULL,
  biweekly_slot INTEGER NOT NULL,
  shop_hour_local INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_consumers_slot ON consumers(biweekly_slot, shop_hour_local);

CREATE TABLE IF NOT EXISTS panel_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  consumer_id INTEGER NOT NULL REFERENCES consumers(id),
  run_id TEXT NOT NULL,
  scheduled_for TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  status TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_panel_runs_consumer ON panel_runs(consumer_id);
CREATE INDEX IF NOT EXISTS idx_panel_runs_scheduled ON panel_runs(scheduled_for);
`;

// Consumer panel biweekly epoch. day-of-fortnight = 0..13 computed against
// this anchor so the schedule is deterministic across service restarts.
// 2026-01-05 is a Monday (UTC) — week 1 of the panel.
const PANEL_EPOCH_MS = Date.UTC(2026, 0, 5);
const BIWEEKLY_MS = 14 * 24 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Open the offers DB. Pass ':memory:' for tests. Creates schema if missing.
 *
 * Migration: this DB was previously used by a different schema that had an
 * `offers` table without `run_id`. If that legacy table is present, it's
 * renamed to `offers_legacy` on first open so our new schema can coexist.
 * No data is dropped.
 */
function openDb(filePath) {
  const Database = require('better-sqlite3');
  const target = filePath || DEFAULT_DB_PATH;
  const db = new Database(target);
  db.pragma('journal_mode = WAL');

  // Detect legacy schema: offers table with no run_id column.
  try {
    const cols = db.prepare(`PRAGMA table_info(offers)`).all();
    const hasRunId = cols.some((c) => c.name === 'run_id');
    if (cols.length > 0 && !hasRunId) {
      // Rename legacy out of the way before creating the new one.
      console.log('[offers-db] Migrating legacy offers -> offers_legacy (no run_id column present)');
      db.exec(`ALTER TABLE offers RENAME TO offers_legacy`);
    }
  } catch (e) {
    console.warn('[offers-db] migration probe failed:', e.message);
  }

  db.exec(SCHEMA_SQL);
  return db;
}

/**
 * Insert one offer row. All fields required except offer_usd, offer_expires,
 * proxy_ip, duration_ms, wizard_log.
 *
 * wizard_log is coerced to a JSON string if an array/object is passed.
 */
function insertOffer(db, row) {
  if (!row || typeof row !== 'object') throw new Error('row required');
  const required = ['run_id', 'vin', 'mileage', 'zip', 'condition', 'site', 'status', 'ran_at'];
  for (const k of required) {
    if (row[k] === undefined || row[k] === null || row[k] === '') {
      throw new Error(`insertOffer: missing required field: ${k}`);
    }
  }
  if (!SITES.includes(row.site)) {
    throw new Error(`insertOffer: invalid site: ${row.site}`);
  }
  const wizardLog = row.wizard_log == null
    ? null
    : (typeof row.wizard_log === 'string' ? row.wizard_log : JSON.stringify(row.wizard_log));

  const stmt = db.prepare(`
    INSERT INTO offers (
      run_id, vin, mileage, zip, condition, site, status,
      offer_usd, offer_expires, proxy_ip, ran_at, duration_ms, wizard_log
    ) VALUES (
      @run_id, @vin, @mileage, @zip, @condition, @site, @status,
      @offer_usd, @offer_expires, @proxy_ip, @ran_at, @duration_ms, @wizard_log
    )
  `);
  const res = stmt.run({
    run_id: String(row.run_id),
    vin: String(row.vin),
    mileage: Number(row.mileage),
    zip: String(row.zip),
    condition: String(row.condition),
    site: String(row.site),
    status: String(row.status),
    offer_usd: row.offer_usd == null ? null : Number(row.offer_usd),
    offer_expires: row.offer_expires || null,
    proxy_ip: row.proxy_ip || null,
    ran_at: String(row.ran_at),
    duration_ms: row.duration_ms == null ? null : Number(row.duration_ms),
    wizard_log: wizardLog,
  });
  return res.lastInsertRowid;
}

/**
 * Parse a row back from sqlite — decode wizard_log JSON if possible.
 */
function hydrate(row) {
  if (!row) return null;
  const out = { ...row };
  if (out.wizard_log) {
    try { out.wizard_log = JSON.parse(out.wizard_log); } catch { /* leave as string */ }
  }
  return out;
}

/**
 * Latest offer row per site for a given VIN (across all runs). Returns
 * { carvana?, carmax?, driveway?, run_id, ran_at } — run_id/ran_at come
 * from whichever row was latest overall (most recent ran_at). If no rows
 * exist, returns { vin, carvana: null, carmax: null, driveway: null,
 * run_id: null, ran_at: null }.
 */
function getLatestByVin(db, vin) {
  const normVin = String(vin || '').trim().toUpperCase();
  const out = {
    vin: normVin,
    carvana: null,
    carmax: null,
    driveway: null,
    run_id: null,
    ran_at: null,
  };

  // SQLite trick: for each site, take the row with max ran_at for this VIN.
  const stmt = db.prepare(`
    SELECT * FROM offers
    WHERE vin = ? AND site = ?
    ORDER BY ran_at DESC
    LIMIT 1
  `);
  let latestAt = null;
  let latestRun = null;
  for (const site of SITES) {
    const row = hydrate(stmt.get(normVin, site));
    if (row) {
      out[site] = row;
      if (!latestAt || row.ran_at > latestAt) {
        latestAt = row.ran_at;
        latestRun = row.run_id;
      }
    }
  }
  out.run_id = latestRun;
  out.ran_at = latestAt;
  return out;
}

/**
 * Recent runs grouped by run_id. Each group contains the three (or fewer)
 * site rows. Ordered newest-first by the earliest ran_at within the run.
 */
function getRuns(db, limit = 20) {
  const cap = Math.max(1, Math.min(200, Number(limit) || 20));
  // Pick the N most recent run_ids by max ran_at within the run.
  const runIds = db.prepare(`
    SELECT run_id, MAX(ran_at) AS latest
    FROM offers
    GROUP BY run_id
    ORDER BY latest DESC
    LIMIT ?
  `).all(cap);

  const rowStmt = db.prepare(`SELECT * FROM offers WHERE run_id = ? ORDER BY site`);
  return runIds.map(({ run_id, latest }) => {
    const rows = rowStmt.all(run_id).map(hydrate);
    const grouped = { run_id, latest_at: latest, vin: rows[0] && rows[0].vin, rows };
    for (const r of rows) grouped[r.site] = r;
    return grouped;
  });
}

// =========================================================================
// Consumer panel helpers
// =========================================================================

const CONSUMER_REQUIRED = [
  'id', 'name', 'vin', 'mileage', 'home_zip', 'proxy_session_id',
  'fingerprint_profile_id', 'biweekly_slot', 'shop_hour_local',
];

/**
 * Insert one consumer row. Throws on missing required fields or VIN/session
 * collision. Returns the consumer id.
 */
function insertConsumer(db, row) {
  if (!row || typeof row !== 'object') throw new Error('row required');
  for (const k of CONSUMER_REQUIRED) {
    if (row[k] === undefined || row[k] === null || row[k] === '') {
      throw new Error(`insertConsumer: missing required field: ${k}`);
    }
  }
  const stmt = db.prepare(`
    INSERT INTO consumers (
      id, name, vin, year, make, model, trim, mileage, home_zip, condition,
      proxy_session_id, fingerprint_profile_id, biweekly_slot, shop_hour_local,
      active
    ) VALUES (
      @id, @name, @vin, @year, @make, @model, @trim, @mileage, @home_zip, @condition,
      @proxy_session_id, @fingerprint_profile_id, @biweekly_slot, @shop_hour_local,
      @active
    )
  `);
  stmt.run({
    id: Number(row.id),
    name: String(row.name),
    vin: String(row.vin).toUpperCase(),
    year: row.year == null ? null : Number(row.year),
    make: row.make || null,
    model: row.model || null,
    trim: row.trim || null,
    mileage: Number(row.mileage),
    home_zip: String(row.home_zip),
    condition: String(row.condition || 'Good'),
    proxy_session_id: String(row.proxy_session_id),
    fingerprint_profile_id: Number(row.fingerprint_profile_id),
    biweekly_slot: Number(row.biweekly_slot),
    shop_hour_local: Number(row.shop_hour_local),
    active: row.active == null ? 1 : (row.active ? 1 : 0),
  });
  return Number(row.id);
}

/**
 * List consumers. Pass {active:true} to filter to only active rows.
 */
function listConsumers(db, opts = {}) {
  const sql = opts && opts.active
    ? `SELECT * FROM consumers WHERE active = 1 ORDER BY id ASC`
    : `SELECT * FROM consumers ORDER BY id ASC`;
  return db.prepare(sql).all();
}

/** Get one consumer by id. Returns null if not found. */
function getConsumer(db, id) {
  const row = db.prepare(`SELECT * FROM consumers WHERE id = ?`).get(Number(id));
  return row || null;
}

/**
 * Compute the day-of-fortnight (0..13) for a given Date in UTC.
 * Stable across DST because we anchor on UTC midnight.
 */
function dayOfFortnight(now) {
  const nowMs = (now instanceof Date) ? now.getTime() : new Date(now).getTime();
  const diff = nowMs - PANEL_EPOCH_MS;
  if (!Number.isFinite(diff)) return 0;
  const within = ((diff % BIWEEKLY_MS) + BIWEEKLY_MS) % BIWEEKLY_MS;
  return Math.floor(within / DAY_MS);
}

/**
 * List consumers whose biweekly_slot matches today's day-of-fortnight AND
 * whose shop_hour_local matches the current UTC hour. Called hourly by the
 * cron; returns 0..N consumers depending on how many are scheduled for
 * this hour.
 *
 * Currently shop_hour_local is interpreted as UTC hour for simplicity.
 * A proper zip->tz mapping would be nicer but adds a dependency; for a
 * first-cut biweekly cadence the zip-level time accuracy is fine.
 */
function listDueConsumers(db, now) {
  const ts = now instanceof Date ? now : new Date(now || Date.now());
  const dof = dayOfFortnight(ts);
  const hour = ts.getUTCHours();
  return db.prepare(`
    SELECT * FROM consumers
    WHERE active = 1 AND biweekly_slot = ? AND shop_hour_local = ?
    ORDER BY id ASC
  `).all(dof, hour);
}

/** Insert a panel_runs row; returns the inserted id. */
function insertPanelRun(db, row) {
  if (!row || typeof row !== 'object') throw new Error('row required');
  if (!row.consumer_id || !row.run_id || !row.scheduled_for) {
    throw new Error('insertPanelRun: consumer_id, run_id, scheduled_for required');
  }
  const res = db.prepare(`
    INSERT INTO panel_runs (consumer_id, run_id, scheduled_for, started_at, finished_at, status, notes)
    VALUES (@consumer_id, @run_id, @scheduled_for, @started_at, @finished_at, @status, @notes)
  `).run({
    consumer_id: Number(row.consumer_id),
    run_id: String(row.run_id),
    scheduled_for: String(row.scheduled_for),
    started_at: row.started_at || null,
    finished_at: row.finished_at || null,
    status: row.status || 'queued',
    notes: row.notes || null,
  });
  return res.lastInsertRowid;
}

/** Patch a panel_runs row. Only keys in allowed set are honored. */
function updatePanelRun(db, id, patch) {
  if (!id || !patch || typeof patch !== 'object') return;
  const allowed = ['started_at', 'finished_at', 'status', 'notes'];
  const sets = [];
  const params = { id: Number(id) };
  for (const k of allowed) {
    if (patch[k] !== undefined) {
      sets.push(`${k} = @${k}`);
      params[k] = patch[k] == null ? null : String(patch[k]);
    }
  }
  if (sets.length === 0) return;
  db.prepare(`UPDATE panel_runs SET ${sets.join(', ')} WHERE id = @id`).run(params);
}

/**
 * Panel status summary for the /panel UI. Returns one record per active
 * consumer: their latest offer per site, their last run timestamp, and
 * their next scheduled timestamp (best-effort — biweekly-slot based).
 */
function getPanelStatus(db) {
  const consumers = listConsumers(db, { active: true });
  const latestStmt = db.prepare(`
    SELECT * FROM offers
    WHERE vin = ? AND site = ?
    ORDER BY ran_at DESC LIMIT 1
  `);
  const lastRunStmt = db.prepare(`
    SELECT MAX(ran_at) AS last_ran FROM offers WHERE vin = ?
  `);
  const runRowStmt = db.prepare(`
    SELECT * FROM panel_runs WHERE consumer_id = ? ORDER BY id DESC LIMIT 1
  `);

  const nowMs = Date.now();
  const nowDof = dayOfFortnight(new Date(nowMs));
  const nowHour = new Date(nowMs).getUTCHours();

  const rows = consumers.map((c) => {
    const carvana  = hydrate(latestStmt.get(c.vin, 'carvana'));
    const carmax   = hydrate(latestStmt.get(c.vin, 'carmax'));
    const driveway = hydrate(latestStmt.get(c.vin, 'driveway'));
    const last = lastRunStmt.get(c.vin);
    const latestRun = runRowStmt.get(c.id) || null;

    // Compute next scheduled: the next UTC timestamp where dof == biweekly_slot
    // AND utc-hour == shop_hour_local. Simple math, assumes hour==UTC.
    let daysAhead = (c.biweekly_slot - nowDof + 14) % 14;
    if (daysAhead === 0 && nowHour >= c.shop_hour_local) daysAhead = 14;
    const nextDate = new Date(nowMs);
    nextDate.setUTCDate(nextDate.getUTCDate() + daysAhead);
    nextDate.setUTCHours(c.shop_hour_local, 0, 0, 0);

    return {
      consumer: c,
      latest: { carvana, carmax, driveway },
      last_ran_at: (last && last.last_ran) || null,
      next_scheduled_at: nextDate.toISOString(),
      latest_panel_run: latestRun,
    };
  });

  const inFlight = rows.filter((r) => r.latest_panel_run && r.latest_panel_run.status === 'running').length;
  const lastRunAt = rows.map((r) => r.last_ran_at).filter(Boolean).sort().pop() || null;
  const nextAt = rows.map((r) => r.next_scheduled_at).filter(Boolean).sort()[0] || null;

  return {
    active_count: consumers.length,
    in_flight: inFlight,
    last_ran_at: lastRunAt,
    next_scheduled_at: nextAt,
    rows,
  };
}

module.exports = {
  openDb,
  insertOffer,
  getLatestByVin,
  getRuns,
  SITES,
  DEFAULT_DB_PATH,
  SCHEMA_SQL,
  // Panel
  insertConsumer,
  listConsumers,
  getConsumer,
  listDueConsumers,
  insertPanelRun,
  updatePanelRun,
  getPanelStatus,
  dayOfFortnight,
  PANEL_EPOCH_MS,
  BIWEEKLY_MS,
};
