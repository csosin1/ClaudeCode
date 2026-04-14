/**
 * Thin wrapper around @aws-sdk/client-mturk. Same shape as prolific-client so
 * the humanloop orchestrator treats them interchangeably.
 *
 * All money values are US dollar CENTS (integers). MTurk's own API expects
 * USD strings with 2 decimals ("3.00") — this client converts for you.
 *
 * Sandbox: when sandbox=true the SDK hits the sandbox endpoint and no real
 * money moves. Default is false (production). NEVER flip to prod by accident —
 * this client refuses to instantiate without explicit credentials.
 *
 * Budget guardrail mirrors prolific-client: every spend-method checks a
 * module-local running total against the declared cap BEFORE the API call.
 */

const PROD_ENDPOINT = 'https://mturk-requester.us-east-1.amazonaws.com';
const SANDBOX_ENDPOINT = 'https://mturk-requester-sandbox.us-east-1.amazonaws.com';

let _runningSpendCents = 0;

function centsToUsdString(cents) {
  const n = Math.max(0, Math.floor(cents || 0));
  return (n / 100).toFixed(2);
}

/**
 * @param {object} opts
 * @param {string} opts.accessKeyId
 * @param {string} opts.secretAccessKey
 * @param {string} [opts.region]       - default 'us-east-1' (MTurk only lives there)
 * @param {boolean} [opts.sandbox]     - default false (prod)
 * @param {number} [opts.balanceCapUsd]
 * @param {object} [opts.clientFactory] - injection point for tests
 */
function createMturkClient({
  accessKeyId,
  secretAccessKey,
  region = 'us-east-1',
  sandbox = false,
  balanceCapUsd = 0,
  clientFactory,
} = {}) {
  if (!accessKeyId || !secretAccessKey) {
    throw new Error('mturk-client: accessKeyId + secretAccessKey are required');
  }

  const capCents = Math.max(0, Math.floor((balanceCapUsd || 0) * 100));
  const endpoint = sandbox ? SANDBOX_ENDPOINT : PROD_ENDPOINT;

  // Lazy-require aws-sdk so that pure unit tests (which inject clientFactory)
  // don't need the module installed.
  let sdk;
  function loadSdk() {
    if (sdk) return sdk;
    if (clientFactory) {
      sdk = clientFactory();
      return sdk;
    }
    // eslint-disable-next-line global-require
    sdk = require('@aws-sdk/client-mturk');
    return sdk;
  }

  let _client;
  function getClient() {
    if (_client) return _client;
    const { MTurkClient } = loadSdk();
    _client = new MTurkClient({
      region,
      endpoint,
      credentials: { accessKeyId, secretAccessKey },
    });
    return _client;
  }

  function assertBudget(plannedCents, label) {
    if (!capCents) return;
    if (_runningSpendCents + plannedCents > capCents) {
      throw new Error(
        `mturk budget guardrail blocked ${label}: ` +
        `running=$${(_runningSpendCents / 100).toFixed(2)} + ` +
        `planned=$${(plannedCents / 100).toFixed(2)} > cap=$${(capCents / 100).toFixed(2)}`,
      );
    }
  }

  /**
   * Create a HIT using ExternalQuestion (the participant sees an iframe
   * pointing at external_url_question). FrameHeight defaults to 800.
   *
   * @param {object} p
   * @param {string} p.title
   * @param {string} p.description
   * @param {string} [p.keywords]         - comma-separated
   * @param {number} p.reward_usd_cents   - per-assignment reward
   * @param {number} p.assignments        - MaxAssignments
   * @param {number} p.lifetime_minutes   - HIT expiry
   * @param {number} p.duration_minutes   - per-assignment time limit
   * @param {string} p.external_url_question - HTTPS URL shown in the iframe
   * @param {number} [p.frame_height]     - iframe height, default 800
   * @param {number} [p.auto_approval_days] - auto-approve after N days; default 3
   */
  async function createHit(p) {
    const assignments = Math.max(1, Math.floor(p.assignments || 1));
    const reward = Math.max(1, Math.floor(p.reward_usd_cents || 0));
    const plannedCents = assignments * reward;
    assertBudget(plannedCents, `createHit "${p.title}" (${assignments} x $${(reward / 100).toFixed(2)})`);

    if (!p.external_url_question || !/^https:\/\//.test(p.external_url_question)) {
      throw new Error('createHit: external_url_question must be an HTTPS URL');
    }

    const frameHeight = Math.max(200, Math.floor(p.frame_height || 800));
    // ExternalQuestion XML — MTurk requires this exact namespace.
    const question =
      '<?xml version="1.0" encoding="UTF-8"?>' +
      '<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">' +
      `<ExternalURL>${escapeXml(p.external_url_question)}</ExternalURL>` +
      `<FrameHeight>${frameHeight}</FrameHeight>` +
      '</ExternalQuestion>';

    const { CreateHITCommand } = loadSdk();
    const client = getClient();
    const resp = await client.send(new CreateHITCommand({
      Title: String(p.title || '').slice(0, 128),
      Description: String(p.description || '').slice(0, 2000),
      Keywords: p.keywords ? String(p.keywords).slice(0, 1000) : undefined,
      Reward: centsToUsdString(reward),
      MaxAssignments: assignments,
      LifetimeInSeconds: Math.max(60, Math.floor((p.lifetime_minutes || 60 * 24) * 60)),
      AssignmentDurationInSeconds: Math.max(60, Math.floor((p.duration_minutes || 30) * 60)),
      AutoApprovalDelayInSeconds: Math.max(0, Math.floor((p.auto_approval_days ?? 3) * 86400)),
      Question: question,
    }));

    _runningSpendCents += plannedCents;
    return resp && resp.HIT ? resp.HIT : resp;
  }

  async function listAssignments(hitId) {
    if (!hitId) throw new Error('listAssignments: hitId required');
    const { ListAssignmentsForHITCommand } = loadSdk();
    const client = getClient();
    const all = [];
    let nextToken;
    // Paginate — each page maxes at 100.
    do {
      const resp = await client.send(new ListAssignmentsForHITCommand({
        HITId: hitId,
        MaxResults: 100,
        NextToken: nextToken,
      }));
      if (resp && Array.isArray(resp.Assignments)) {
        all.push(...resp.Assignments);
      }
      nextToken = resp && resp.NextToken;
    } while (nextToken);
    return all;
  }

  async function approveAssignment(assignmentId, requesterFeedback) {
    if (!assignmentId) throw new Error('approveAssignment: id required');
    const { ApproveAssignmentCommand } = loadSdk();
    const client = getClient();
    return client.send(new ApproveAssignmentCommand({
      AssignmentId: assignmentId,
      RequesterFeedback: requesterFeedback ? String(requesterFeedback).slice(0, 1024) : undefined,
    }));
  }

  async function rejectAssignment(assignmentId, reason) {
    if (!assignmentId) throw new Error('rejectAssignment: id required');
    const { RejectAssignmentCommand } = loadSdk();
    const client = getClient();
    return client.send(new RejectAssignmentCommand({
      AssignmentId: assignmentId,
      // MTurk requires RequesterFeedback on reject.
      RequesterFeedback: String(reason || 'Did not meet the HIT requirements.').slice(0, 1024),
    }));
  }

  /** GetAccountBalance returns "AvailableBalance" as a USD string. */
  async function getBalance() {
    const { GetAccountBalanceCommand } = loadSdk();
    const client = getClient();
    const resp = await client.send(new GetAccountBalanceCommand({}));
    const usdStr = (resp && resp.AvailableBalance) || '0';
    const usd = Number(usdStr) || 0;
    return { cents: Math.round(usd * 100), usd };
  }

  return {
    createHit,
    listAssignments,
    approveAssignment,
    rejectAssignment,
    getBalance,
    _runningSpendCents: () => _runningSpendCents,
    _capCents: () => capCents,
    _endpoint: () => endpoint,
  };
}

function escapeXml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function _resetRunningSpend() { _runningSpendCents = 0; }

module.exports = { createMturkClient, _resetRunningSpend };
