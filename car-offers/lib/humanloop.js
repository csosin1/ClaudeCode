/**
 * Human-loop orchestrator.
 *
 * Posts "briefed jobs" to either Prolific (quality, $5+ tasks, real humans
 * with narration) or MTurk (volume, <$5 tasks, quick validation) based on
 * the brief's `prefer` field. Persists to a `humanloop_jobs` SQLite table
 * so the car-offers panel can show what's in flight + results.
 *
 * Public API:
 *   postBriefedJob(brief) -> { platform, id, status, job_id }
 *   harvestSubmissions(jobId) -> [{submission_id, video_url, metadata}, ...]
 *   approveSubmission(jobId, submissionId)
 *   rejectSubmission(jobId, submissionId, reason)
 *   listJobs()
 *   ensureSchema(db)
 *
 * Brief shape:
 *   {
 *     title: string,
 *     description: string,
 *     steps: string[],
 *     success_criteria: string,
 *     reward_usd_cents: number,
 *     participants: 1..50,
 *     max_minutes: number,
 *     prefer: 'quality' | 'volume' | 'auto',
 *     external_url?: string,       // Prolific requires a URL participants hit
 *     mturk_external_url?: string, // MTurk's ExternalQuestion URL, if different
 *   }
 */

const path = require('path');
const config = require('./config');

const HUMANLOOP_SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS humanloop_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  platform_id TEXT NOT NULL,
  brief_json TEXT NOT NULL,
  status TEXT NOT NULL,
  reward_usd_cents INTEGER,
  participants INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_humanloop_jobs_platform ON humanloop_jobs(platform, platform_id);
CREATE INDEX IF NOT EXISTS idx_humanloop_jobs_status ON humanloop_jobs(status);

CREATE TABLE IF NOT EXISTS humanloop_submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES humanloop_jobs(id),
  submission_id TEXT NOT NULL,
  status TEXT NOT NULL,
  video_url TEXT,
  metadata_json TEXT,
  harvested_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_humanloop_sub ON humanloop_submissions(job_id, submission_id);
`;

function ensureSchema(db) {
  db.exec(HUMANLOOP_SCHEMA_SQL);
}

/** Open the DB from car-offers runtime location (or override for tests). */
function openHumanloopDb(dbPath) {
  // Default to the live runtime DB — NOT the source-tree copy — because the
  // writes we do here need to be visible to the running server's reads.
  const target = dbPath || process.env.HUMANLOOP_DB_PATH
    || path.join('/opt/car-offers', 'offers.db');
  const Database = require('better-sqlite3');
  const db = new Database(target);
  db.pragma('journal_mode = WAL');
  ensureSchema(db);
  return db;
}

/**
 * Routing rule:
 *   prefer='quality' -> Prolific
 *   prefer='volume'  -> MTurk
 *   prefer='auto'    -> Prolific if reward_usd_cents >= 800 else MTurk
 */
function pickPlatform(brief) {
  const pref = (brief.prefer || 'auto').toLowerCase();
  if (pref === 'quality') return 'prolific';
  if (pref === 'volume') return 'mturk';
  return (brief.reward_usd_cents || 0) >= 800 ? 'prolific' : 'mturk';
}

function haveProlific() { return !!config.PROLIFIC_TOKEN; }
function haveMturk() { return !!(config.MTURK_ACCESS_KEY_ID && config.MTURK_SECRET_ACCESS_KEY); }

/** Build a Prolific client using current config. */
function prolific() {
  const { createProlificClient } = require('./prolific-client');
  return createProlificClient({
    token: config.PROLIFIC_TOKEN,
    balanceCapUsd: config.PROLIFIC_BALANCE_USD,
  });
}

/** Build an MTurk client using current config. Defaults to prod (sandbox=false). */
function mturk() {
  const { createMturkClient } = require('./mturk-client');
  return createMturkClient({
    accessKeyId: config.MTURK_ACCESS_KEY_ID,
    secretAccessKey: config.MTURK_SECRET_ACCESS_KEY,
    balanceCapUsd: config.MTURK_BALANCE_USD,
  });
}

/**
 * Build a human-readable description block from a brief. We concat
 * description + steps + success_criteria into one string so participants see
 * the full task in one place (Prolific's description field and MTurk's
 * Description both accept plain text).
 */
function flattenBriefText(brief) {
  const steps = Array.isArray(brief.steps) && brief.steps.length
    ? 'Steps:\n' + brief.steps.map((s, i) => `${i + 1}. ${s}`).join('\n')
    : '';
  const success = brief.success_criteria
    ? `\n\nSuccess criteria: ${brief.success_criteria}`
    : '';
  return [brief.description || '', steps, success]
    .filter(Boolean)
    .join('\n\n')
    .slice(0, 1900); // leave room under MTurk's 2000-char Description cap
}

/**
 * Post a briefed job to whichever platform the brief prefers.
 * Throws if the chosen platform isn't credentialed — caller should check
 * haveProlific()/haveMturk() first for a friendly error.
 */
async function postBriefedJob(brief, opts = {}) {
  const platform = pickPlatform(brief);
  const db = opts.db || openHumanloopDb(opts.dbPath);

  const flat = flattenBriefText(brief);
  let platformId;
  let payload;

  if (platform === 'prolific') {
    if (!haveProlific()) throw new Error('prolific not configured');
    const client = opts.prolificClient || prolific();
    const study = await client.createStudy({
      name: brief.title,
      internal_name: `car-offers-${Date.now()}`,
      description: flat,
      external_study_url: brief.external_url || 'https://casinv.dev/car-offers/preview/',
      total_available_places: Math.max(1, Math.min(50, brief.participants || 1)),
      reward_usd_cents: brief.reward_usd_cents,
      estimated_completion_time_minutes: brief.max_minutes || 10,
      device_compatibility: 'desktop',
    });
    platformId = study.id || study.study_id || '';
    payload = study;
    // Auto-publish if the caller asked. Otherwise leave as draft so a human
    // can review the study on prolific.com before spending money.
    if (opts.autoPublish && platformId) {
      try {
        await client.publishStudy(platformId);
      } catch (e) {
        // Don't bail — the job is already persisted below as 'posted'.
        // eslint-disable-next-line no-console
        console.warn(`[humanloop] auto-publish failed for ${platformId}: ${e.message}`);
      }
    }
  } else {
    if (!haveMturk()) throw new Error('mturk not configured');
    const client = opts.mturkClient || mturk();
    const hit = await client.createHit({
      title: brief.title,
      description: flat,
      keywords: 'car,research,survey',
      reward_usd_cents: brief.reward_usd_cents,
      assignments: Math.max(1, Math.min(50, brief.participants || 1)),
      lifetime_minutes: Math.max(60, (brief.max_minutes || 30) * 12), // expire in ~half a day
      duration_minutes: Math.max(5, brief.max_minutes || 30),
      external_url_question: brief.mturk_external_url || brief.external_url
        || 'https://casinv.dev/car-offers/preview/',
    });
    platformId = hit.HITId || hit.hit_id || '';
    payload = hit;
  }

  if (!platformId) {
    throw new Error(`${platform} returned no id; raw=${JSON.stringify(payload).slice(0, 300)}`);
  }

  const info = db.prepare(`
    INSERT INTO humanloop_jobs
      (platform, platform_id, brief_json, status, reward_usd_cents, participants, updated_at)
    VALUES (?, ?, ?, 'posted', ?, ?, datetime('now'))
  `).run(
    platform,
    String(platformId),
    JSON.stringify(brief),
    Math.floor(brief.reward_usd_cents || 0),
    Math.floor(brief.participants || 1),
  );

  return {
    job_id: info.lastInsertRowid,
    platform,
    id: platformId,
    status: 'posted',
  };
}

/** Look up a job row (returns null if not found). */
function getJob(db, jobId) {
  const row = db.prepare(`SELECT * FROM humanloop_jobs WHERE id = ?`).get(jobId);
  return row || null;
}

/**
 * Pull the latest submissions for a job from its platform and persist
 * anything new to humanloop_submissions. Returns the merged list of rows
 * currently known for this job.
 */
async function harvestSubmissions(jobId, opts = {}) {
  const db = opts.db || openHumanloopDb(opts.dbPath);
  const job = getJob(db, Number(jobId));
  if (!job) throw new Error(`harvestSubmissions: no job with id=${jobId}`);

  let rows = [];
  if (job.platform === 'prolific') {
    const client = opts.prolificClient || prolific();
    const subs = await client.listSubmissions(job.platform_id);
    rows = subs.map((s) => ({
      submission_id: s.id || s.submission_id,
      status: s.status || 'unknown',
      // Prolific doesn't host video — participants upload to the external
      // site. video_url will come from the study's custom response fields.
      video_url: (s.custom_responses && s.custom_responses.video_url) || null,
      metadata: s,
    }));
  } else {
    const client = opts.mturkClient || mturk();
    const assignments = await client.listAssignments(job.platform_id);
    rows = assignments.map((a) => ({
      submission_id: a.AssignmentId,
      status: a.AssignmentStatus || 'unknown',
      // MTurk's ExternalQuestion posts an answer XML blob; extraction left
      // to the panel UI since answers are free-form per brief.
      video_url: null,
      metadata: a,
    }));
  }

  const upsert = db.prepare(`
    INSERT INTO humanloop_submissions
      (job_id, submission_id, status, video_url, metadata_json)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(job_id, submission_id) DO UPDATE SET
      status = excluded.status,
      video_url = COALESCE(excluded.video_url, humanloop_submissions.video_url),
      metadata_json = excluded.metadata_json,
      harvested_at = datetime('now')
  `);

  const tx = db.transaction((items) => {
    for (const r of items) {
      if (!r.submission_id) continue;
      upsert.run(
        job.id,
        String(r.submission_id),
        String(r.status || 'unknown'),
        r.video_url || null,
        JSON.stringify(r.metadata || {}),
      );
    }
  });
  tx(rows);

  // Bump job status if we now have finished submissions.
  const doneStatuses = new Set(['APPROVED', 'Approved', 'Rejected', 'COMPLETED', 'completed']);
  const anyComplete = rows.some((r) => doneStatuses.has(r.status));
  if (rows.length > 0) {
    db.prepare(`UPDATE humanloop_jobs SET status = ?, updated_at = datetime('now') WHERE id = ?`)
      .run(anyComplete ? 'collecting' : 'posted', job.id);
  }

  return rows.map((r) => ({
    submission_id: r.submission_id,
    video_url: r.video_url,
    status: r.status,
    metadata: r.metadata,
  }));
}

async function approveSubmission(jobId, submissionId, opts = {}) {
  const db = opts.db || openHumanloopDb(opts.dbPath);
  const job = getJob(db, Number(jobId));
  if (!job) throw new Error(`approveSubmission: no job with id=${jobId}`);
  if (job.platform === 'prolific') {
    const client = opts.prolificClient || prolific();
    await client.approveSubmission(submissionId);
  } else {
    const client = opts.mturkClient || mturk();
    await client.approveAssignment(submissionId);
  }
  db.prepare(`UPDATE humanloop_submissions SET status = 'approved' WHERE job_id = ? AND submission_id = ?`)
    .run(job.id, String(submissionId));
}

async function rejectSubmission(jobId, submissionId, reason, opts = {}) {
  const db = opts.db || openHumanloopDb(opts.dbPath);
  const job = getJob(db, Number(jobId));
  if (!job) throw new Error(`rejectSubmission: no job with id=${jobId}`);
  if (job.platform === 'prolific') {
    const client = opts.prolificClient || prolific();
    await client.rejectSubmission(submissionId, reason);
  } else {
    const client = opts.mturkClient || mturk();
    await client.rejectAssignment(submissionId, reason);
  }
  db.prepare(`UPDATE humanloop_submissions SET status = 'rejected' WHERE job_id = ? AND submission_id = ?`)
    .run(job.id, String(submissionId));
}

/** List all jobs, newest first. Returns rows with `brief` parsed. */
function listJobs(db) {
  const rows = db.prepare(`SELECT * FROM humanloop_jobs ORDER BY id DESC`).all();
  return rows.map((r) => {
    let brief = null;
    try { brief = JSON.parse(r.brief_json); } catch { brief = null; }
    return { ...r, brief };
  });
}

module.exports = {
  postBriefedJob,
  harvestSubmissions,
  approveSubmission,
  rejectSubmission,
  listJobs,
  getJob,
  pickPlatform,
  ensureSchema,
  openHumanloopDb,
  haveProlific,
  haveMturk,
  HUMANLOOP_SCHEMA_SQL,
};
