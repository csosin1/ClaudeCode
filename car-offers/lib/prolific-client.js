/**
 * Minimal Prolific REST client (no external deps — uses global fetch from Node >=18).
 *
 * Docs: https://docs.prolific.com/docs/api-docs/public/
 *
 * Endpoints used:
 *   POST /api/v1/studies/                             - create draft study
 *   POST /api/v1/studies/{id}/transition/             - publish (action='PUBLISH')
 *   GET  /api/v1/studies/{id}/submissions/            - list submissions
 *   POST /api/v1/submissions/{id}/transition/         - approve/reject
 *   GET  /api/v1/users/me/                            - balance snapshot
 *
 * Budget guardrail: every spend-method checks the caller's declared
 * `balanceCapUsd` and a module-local running total of spend kicked off by
 * this process. If a call would push us over the cap it throws with a
 * clear error BEFORE any HTTP request is made. The in-memory counter resets
 * when the process restarts — deliberate: the real balance lives on Prolific,
 * this is only a last-ditch belt-and-suspenders for runaway code.
 *
 * All money values on this client are US dollar CENTS (integers). Prolific's
 * own API expects cents too, so no conversion is done.
 */

const BASE = 'https://api.prolific.com';

// Module-local running spend in cents. Survives across instances in the same
// process. Test code can reset via _resetRunningSpend (not exported to real code).
let _runningSpendCents = 0;

/**
 * @param {object} opts
 * @param {string} opts.token           - Prolific API token ("Authorization: Token ...").
 * @param {number} [opts.balanceCapUsd] - Per-process hard cap in USD. 0/falsy = no cap
 *                                        (discouraged; always pass a cap in prod).
 * @param {typeof fetch} [opts.fetch]   - Injection point for tests.
 */
function createProlificClient({ token, balanceCapUsd = 0, fetch: fetchImpl } = {}) {
  if (!token || typeof token !== 'string') {
    throw new Error('prolific-client: token is required');
  }
  const f = fetchImpl || globalThis.fetch;
  if (typeof f !== 'function') {
    throw new Error('prolific-client: no global fetch (need Node >=18 or pass fetch option)');
  }

  const capCents = Math.max(0, Math.floor((balanceCapUsd || 0) * 100));

  async function request(method, path, body) {
    const url = BASE + path;
    const init = {
      method,
      headers: {
        Authorization: `Token ${token}`,
        Accept: 'application/json',
      },
    };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await f(url, init);
    } catch (e) {
      throw new Error(`prolific ${method} ${path} network error: ${e.message}`);
    }
    const text = await resp.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch { /* non-JSON body */ }
    if (!resp.ok) {
      const msg = (json && (json.detail || json.error || json.message)) || text.slice(0, 400);
      const err = new Error(`prolific ${method} ${path} ${resp.status}: ${msg}`);
      err.status = resp.status;
      err.body = json || text;
      throw err;
    }
    return json;
  }

  /**
   * Check that planned spend (cents) fits under the cap BEFORE the network
   * call. If no cap was configured, just pass.
   */
  function assertBudget(plannedCents, label) {
    if (!capCents) return;
    if (_runningSpendCents + plannedCents > capCents) {
      throw new Error(
        `prolific budget guardrail blocked ${label}: ` +
        `running=$${(_runningSpendCents / 100).toFixed(2)} + ` +
        `planned=$${(plannedCents / 100).toFixed(2)} > cap=$${(capCents / 100).toFixed(2)}`,
      );
    }
  }

  /**
   * Create a study in DRAFT state. Not yet published (no participants will
   * see it until publishStudy() is called).
   *
   * Required fields map to Prolific's study schema. We charge the guardrail
   * at CREATE time — publishing later cannot fail the cap check.
   *
   * @param {object} p
   * @param {string} p.name
   * @param {string} [p.internal_name]
   * @param {string} p.description
   * @param {string} p.external_study_url  - participants get redirected here
   * @param {number} p.total_available_places
   * @param {number} p.reward_usd_cents    - per-participant reward
   * @param {number} p.estimated_completion_time_minutes
   * @param {string} [p.device_compatibility] - 'desktop' default
   * @param {Array}  [p.eligibility_requirements] - Prolific's raw shape
   * @param {string} [p.completion_code]   - code participants enter to finish
   */
  async function createStudy(p) {
    const places = Math.max(1, Math.floor(p.total_available_places || 1));
    const reward = Math.max(1, Math.floor(p.reward_usd_cents || 0));
    const plannedCents = places * reward;
    assertBudget(plannedCents, `createStudy "${p.name}" (${places} x $${(reward / 100).toFixed(2)})`);

    // Prolific charges a service fee on top of reward; the cap is protective,
    // so we count reward-only here. Their fee is ~33% of reward — leave room
    // for that when you choose balanceCapUsd.
    const payload = {
      name: p.name,
      internal_name: p.internal_name || p.name,
      description: p.description,
      external_study_url: p.external_study_url,
      prolific_id_option: 'url_parameters',
      completion_code: p.completion_code || 'CAROFFERS',
      completion_option: 'url',
      total_available_places: places,
      reward: reward,
      estimated_completion_time: Math.max(1, Math.floor(p.estimated_completion_time_minutes || 10)),
      device_compatibility: p.device_compatibility
        ? [p.device_compatibility]
        : ['desktop'],
      peripheral_requirements: p.peripheral_requirements || [],
      eligibility_requirements: p.eligibility_requirements || [],
    };

    const study = await request('POST', '/api/v1/studies/', payload);
    _runningSpendCents += plannedCents;
    return study;
  }

  /** Transition a draft study to PUBLISH (makes it visible to participants). */
  async function publishStudy(id) {
    if (!id) throw new Error('publishStudy: id is required');
    return request('POST', `/api/v1/studies/${encodeURIComponent(id)}/transition/`, {
      action: 'PUBLISH',
    });
  }

  /** List all submissions (any status) for a study. */
  async function listSubmissions(id) {
    if (!id) throw new Error('listSubmissions: id is required');
    const data = await request('GET', `/api/v1/studies/${encodeURIComponent(id)}/submissions/`);
    // Prolific paginates as {results:[...]} or sometimes a bare array.
    if (Array.isArray(data)) return data;
    if (data && Array.isArray(data.results)) return data.results;
    return [];
  }

  async function approveSubmission(submissionId) {
    if (!submissionId) throw new Error('approveSubmission: id is required');
    return request('POST', `/api/v1/submissions/${encodeURIComponent(submissionId)}/transition/`, {
      action: 'APPROVE',
    });
  }

  async function rejectSubmission(submissionId, reason) {
    if (!submissionId) throw new Error('rejectSubmission: id is required');
    const categories = ['LOW_EFFORT']; // Prolific requires at least one category
    return request('POST', `/api/v1/submissions/${encodeURIComponent(submissionId)}/transition/`, {
      action: 'REJECT',
      message: String(reason || 'Did not meet the study requirements.').slice(0, 1000),
      rejection_category: categories[0],
    });
  }

  /**
   * Best-effort retrieval of whatever data Prolific exposes per submission.
   * Prolific itself does not host videos/audio — participants upload those to
   * the external study URL. This method returns the submission payload
   * (custom responses, start/end times, participant id) so callers can
   * correlate with their own S3/video storage.
   */
  async function downloadSubmissionData(submissionId) {
    if (!submissionId) throw new Error('downloadSubmissionData: id is required');
    const data = await request('GET', `/api/v1/submissions/${encodeURIComponent(submissionId)}/`);
    // Normalise to an array of "event blobs" so the shape matches the mturk
    // client's listAssignments result. For Prolific we only ever get one blob
    // per submission — wrap it.
    return [data];
  }

  /**
   * Fetch the account's current available balance in USD cents. Prolific
   * exposes this on /users/me/ as "available_balance" (cents).
   */
  async function getBalance() {
    const me = await request('GET', '/api/v1/users/me/');
    const cents = (me && (me.available_balance ?? me.balance)) || 0;
    return { cents: Math.floor(cents), usd: cents / 100 };
  }

  return {
    createStudy,
    publishStudy,
    listSubmissions,
    approveSubmission,
    rejectSubmission,
    downloadSubmissionData,
    getBalance,
    // Diagnostics — not for production use:
    _runningSpendCents: () => _runningSpendCents,
    _capCents: () => capCents,
  };
}

// Test-only hook. Never called in prod code.
function _resetRunningSpend() { _runningSpendCents = 0; }

module.exports = { createProlificClient, _resetRunningSpend };
