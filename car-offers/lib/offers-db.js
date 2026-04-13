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
`;

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

module.exports = {
  openDb,
  insertOffer,
  getLatestByVin,
  getRuns,
  SITES,
  DEFAULT_DB_PATH,
  SCHEMA_SQL,
};
