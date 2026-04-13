/**
 * Panel runner — executes one or more consumer panel runs.
 *
 * A "panel run" is one consumer shopping their VIN across Carvana, CarMax,
 * and Driveway sequentially. Each site write goes to offers.db (shared
 * schema with the ad-hoc /api/quote-all). Each run also inserts a
 * panel_runs row so we can tell "consumer 3 was shopped 14 days ago" even
 * when the offer rows are blocked / account_required.
 *
 * Concurrency: ZERO for v1. The droplet has ONE Xvfb display and the
 * Chromium profile is a per-consumer singleton-lock, so two consumers
 * launching at once would step on each other. Sequential is fine because
 * one consumer is ~5-15 min; 12 consumers ~ 1-3 hours worst case.
 *
 * Exports:
 *   runOneConsumer(consumer, opts)      -> one consumer, 3 sites
 *   runDueConsumers({ now })            -> all consumers whose slot+hour match
 *   runConsumerById(id)                 -> ad-hoc single run for /api/panel/run/:id
 *   simulateFirstPanelSeed(now, count)  -> returns per-consumer offsets so the
 *                                          first-ever panel run staggers out
 */

const crypto = require('crypto');
const path = require('path');
const {
  openDb, insertOffer, getConsumer, listDueConsumers,
  listConsumers, insertPanelRun, updatePanelRun,
} = require('./offers-db');
const { normalizeOfferRequest } = require('./offer-input');

// Per-panel-run serialize. Cheap in-memory lock — we only run this inside
// one Node process. Set true while a consumer is in-flight so the HTTP
// trigger can return 409 instead of stacking.
let panelActive = false;

/**
 * Jittered pause between sites for a single consumer. 30-90s — avoids
 * obvious bot-burst. Matches /api/quote-all behavior.
 */
function interSitePause() {
  const ms = 30000 + Math.floor(Math.random() * 60000);
  return new Promise((r) => setTimeout(r, ms));
}

/** Extract a USD int from '$21,500' or a number. Null if no match. */
function extractUsdInt(raw) {
  if (raw == null) return null;
  if (typeof raw === 'number' && Number.isFinite(raw)) return Math.round(raw);
  const m = String(raw).match(/\$?\s?([\d,]+)/);
  if (!m) return null;
  const n = parseInt(m[1].replace(/,/g, ''), 10);
  return Number.isFinite(n) ? n : null;
}

/**
 * Resolve a site handler lazily so a module that failed to install (e.g.
 * better-sqlite3 hadn't finished compiling) doesn't crash the runner.
 */
function _loadSiteHandler(site) {
  switch (site) {
    case 'carvana':  return require('./carvana').getCarvanaOffer;
    case 'carmax':   return require('./carmax').getCarmaxOffer;
    case 'driveway': return require('./driveway').getDrivewayOffer;
  }
  throw new Error(`unknown site: ${site}`);
}

/**
 * Run one consumer through all three sites sequentially. Writes one
 * offers row per site and one panel_runs row.
 *
 * @param {Object} consumer - row from the consumers table.
 * @param {Object} [opts]
 * @param {Object} [opts.db] - Optional DB handle (defaults to openDb()).
 * @param {string} [opts.scheduledFor] - ISO timestamp; defaults to now.
 * @param {string} [opts.runId] - override run id; default auto-generated.
 * @param {Function} [opts.log] - logger override; default console.log.
 * @returns {Promise<Object>} per-site results + panel_run id.
 */
async function runOneConsumer(consumer, opts = {}) {
  if (!consumer || !consumer.id || !consumer.vin) {
    throw new Error('runOneConsumer: consumer with id + vin required');
  }
  const db = opts.db || openDb();
  const log = opts.log || ((m) => console.log(m));
  const runId = opts.runId || `panel-${consumer.id}-${Date.now()}-${crypto.randomBytes(3).toString('hex')}`;
  const scheduledFor = opts.scheduledFor || new Date().toISOString();
  const startedAt = new Date().toISOString();

  const panelRunId = insertPanelRun(db, {
    consumer_id: consumer.id,
    run_id: runId,
    scheduled_for: scheduledFor,
    started_at: startedAt,
    status: 'running',
    notes: null,
  });

  const normalized = normalizeOfferRequest({
    vin: consumer.vin,
    mileage: String(consumer.mileage),
    zip: consumer.home_zip,
    condition: consumer.condition || 'Good',
  });

  const results = { carvana: null, carmax: null, driveway: null };
  const sites = ['carvana', 'carmax', 'driveway'];
  let anyOk = false;
  let errorsAggregate = [];

  try {
    for (let i = 0; i < sites.length; i++) {
      const site = sites[i];
      const t0 = Date.now();
      log(`[panel] consumer=${consumer.id} run=${runId} site=${site} start`);

      let raw;
      let threwBeforeReturn = null;
      try {
        const handler = _loadSiteHandler(site);
        raw = await handler({
          vin: normalized.vin,
          mileage: normalized.mileage,
          zip: normalized.zip,
          condition: normalized.condition,
          email: undefined,
          consumerId: consumer.id,
          fingerprintProfileId: consumer.fingerprint_profile_id,
          proxyZip: normalized.zip,
        });
        if (!raw || typeof raw !== 'object') {
          raw = { error: `handler returned non-object: ${typeof raw}`, wizardLog: [] };
        }
      } catch (err) {
        threwBeforeReturn = err;
        raw = { error: err.message || String(err), wizardLog: [] };
        errorsAggregate.push(`${site}:${err.message}`);
      }

      const offerUsd = raw.offer_usd != null ? Number(raw.offer_usd) : extractUsdInt(raw.offer);
      const status = raw.status || (offerUsd ? 'ok' : (raw.error ? 'error' : 'ok'));
      if (status === 'ok' && offerUsd) anyOk = true;

      // Defense in depth: ALWAYS persist a wizard_log. If the handler returned
      // without one, synthesize a minimal log so the DB row is never NULL.
      // Append the error text as the final log entry — this is the diagnostic
      // signal that was previously dropped on the floor (issue from
      // 2026-04-13 consumer-1 carvana run).
      let logEntries = Array.isArray(raw.wizardLog) ? raw.wizardLog.slice() : [];
      if (logEntries.length === 0) {
        logEntries.push(`[panel-runner] ${site} returned no wizard_log (status=${status})`);
      }
      if (raw.error) {
        logEntries.push(`[panel-runner] error: ${raw.error}`);
      }
      if (threwBeforeReturn) {
        logEntries.push(`[panel-runner] handler threw: ${threwBeforeReturn.stack || threwBeforeReturn.message}`);
      }

      const durationMs = Date.now() - t0;
      try {
        insertOffer(db, {
          run_id: runId,
          vin: normalized.vin,
          mileage: Number(normalized.mileage),
          zip: normalized.zip,
          condition: normalized.condition,
          site,
          status,
          offer_usd: offerUsd,
          offer_expires: raw.offer_expires || null,
          proxy_ip: (raw.details && raw.details.proxy_ip) || null,
          ran_at: new Date().toISOString(),
          duration_ms: durationMs,
          wizard_log: logEntries,
        });
      } catch (e) {
        log(`[panel] insertOffer failed for ${site}: ${e.message}`);
      }

      results[site] = {
        status,
        offer_usd: offerUsd,
        offer: raw.offer || (offerUsd ? `$${offerUsd.toLocaleString()}` : null),
        offer_expires: raw.offer_expires || null,
        error: raw.error || null,
        duration_ms: durationMs,
      };

      log(`[panel] consumer=${consumer.id} site=${site} status=${status} offer=${offerUsd || '-'} dur=${durationMs}ms`);

      if (i < sites.length - 1) {
        await interSitePause();
      }
    }

    const finalStatus = anyOk ? 'done' : (errorsAggregate.length === sites.length ? 'error' : 'done');
    updatePanelRun(db, panelRunId, {
      finished_at: new Date().toISOString(),
      status: finalStatus,
      notes: errorsAggregate.join(' | ').slice(0, 400) || null,
    });

    return {
      panel_run_id: Number(panelRunId),
      run_id: runId,
      consumer_id: consumer.id,
      vin: consumer.vin,
      results,
    };
  } catch (fatal) {
    updatePanelRun(db, panelRunId, {
      finished_at: new Date().toISOString(),
      status: 'error',
      notes: `fatal: ${fatal.message}`.slice(0, 400),
    });
    throw fatal;
  }
}

/**
 * Run every consumer currently due (slot+hour matches now). Sequential.
 * Safe to call hourly via cron — if none are due, returns quickly.
 *
 * @param {Object} [opts]
 * @param {Date}   [opts.now]
 * @param {Object} [opts.db]
 * @returns {Promise<{ran: number, results: Array}>}
 */
async function runDueConsumers(opts = {}) {
  if (panelActive) {
    return { ran: 0, skipped: true, reason: 'panel_already_running', results: [] };
  }
  const db = opts.db || openDb();
  const now = opts.now || new Date();
  const due = listDueConsumers(db, now);
  if (due.length === 0) {
    return { ran: 0, results: [] };
  }
  panelActive = true;
  const results = [];
  try {
    for (const consumer of due) {
      try {
        const r = await runOneConsumer(consumer, { db, scheduledFor: now.toISOString() });
        results.push(r);
      } catch (e) {
        console.error(`[panel] consumer ${consumer.id} failed: ${e.message}`);
        results.push({ consumer_id: consumer.id, error: e.message });
      }
    }
  } finally {
    panelActive = false;
  }
  return { ran: results.length, results };
}

/**
 * Ad-hoc: run one consumer by id, regardless of schedule. Used by
 * POST /api/panel/run/:id and by the first-panel-seed kickoff.
 */
async function runConsumerById(id, opts = {}) {
  const db = opts.db || openDb();
  const consumer = getConsumer(db, id);
  if (!consumer) throw new Error(`no consumer with id=${id}`);
  if (panelActive) {
    return { error: 'panel_already_running', consumer_id: id };
  }
  panelActive = true;
  try {
    return await runOneConsumer(consumer, { db });
  } finally {
    panelActive = false;
  }
}

/**
 * Returns an array of { consumer_id, delay_minutes } so the first panel
 * run staggers: consumer 1 at +0, consumer 2 at +15, etc. Not currently
 * wired into a timer — the orchestrator triggers seed + kickoff manually.
 */
function simulateFirstPanelSeed(consumers, stepMinutes = 15) {
  return (consumers || []).map((c, i) => ({ consumer_id: c.id, delay_minutes: i * stepMinutes }));
}

/** Snapshot panel lock state — exposed for /api/status-style diagnostics. */
function isPanelActive() { return panelActive; }

module.exports = {
  runOneConsumer,
  runDueConsumers,
  runConsumerById,
  simulateFirstPanelSeed,
  isPanelActive,
};
