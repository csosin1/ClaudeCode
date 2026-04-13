/**
 * Unit tests for offers-db. Runs on an in-memory SQLite so it's safe
 * on any host. Invoke with: node lib/offers-db.test.js
 */
const assert = require('assert');
const { openDb, insertOffer, getLatestByVin, getRuns } = require('./offers-db');

function run() {
  const db = openDb(':memory:');

  const run1 = 'run-aaa';
  const vin = '1HGCV2F9XNA008352';
  const baseAt = '2026-04-13T12:00:00Z';

  // Insert all three sites for one run
  const id1 = insertOffer(db, {
    run_id: run1, vin, mileage: 48000, zip: '06880', condition: 'Good',
    site: 'carvana', status: 'ok', offer_usd: 21000, offer_expires: '2026-04-20',
    proxy_ip: '24.228.193.57', ran_at: baseAt, duration_ms: 180000,
    wizard_log: ['step1', 'step2'],
  });
  assert(typeof id1 === 'bigint' || typeof id1 === 'number', 'id1 returned');

  insertOffer(db, {
    run_id: run1, vin, mileage: 48000, zip: '06880', condition: 'Good',
    site: 'carmax', status: 'ok', offer_usd: 20500,
    proxy_ip: '24.228.193.57', ran_at: '2026-04-13T12:05:00Z', duration_ms: 200000,
    wizard_log: '["a","b"]', // string also accepted
  });
  insertOffer(db, {
    run_id: run1, vin, mileage: 48000, zip: '06880', condition: 'Good',
    site: 'driveway', status: 'account_required', offer_usd: null,
    proxy_ip: '24.228.193.57', ran_at: '2026-04-13T12:10:00Z', duration_ms: 90000,
    wizard_log: null,
  });

  const latest = getLatestByVin(db, vin);
  assert.strictEqual(latest.vin, vin);
  assert(latest.carvana && latest.carvana.offer_usd === 21000, 'carvana row present');
  assert(latest.carmax && latest.carmax.offer_usd === 20500, 'carmax row present');
  assert(latest.driveway && latest.driveway.status === 'account_required', 'driveway row present');
  assert.strictEqual(latest.run_id, run1, 'run_id surfaced');
  // wizard_log should round-trip JSON
  assert(Array.isArray(latest.carvana.wizard_log) && latest.carvana.wizard_log[0] === 'step1',
    'wizard_log JSON round-trip');

  // Unknown VIN returns well-formed empty
  const empty = getLatestByVin(db, 'ZZZZZZZZZZZZZZZZZ');
  assert.strictEqual(empty.carvana, null);
  assert.strictEqual(empty.carmax, null);
  assert.strictEqual(empty.driveway, null);
  assert.strictEqual(empty.run_id, null);

  // Second run: only carvana this time — latest should reflect
  insertOffer(db, {
    run_id: 'run-bbb', vin, mileage: 48000, zip: '06880', condition: 'Good',
    site: 'carvana', status: 'ok', offer_usd: 22000,
    ran_at: '2026-04-14T12:00:00Z', duration_ms: 160000,
  });
  const latest2 = getLatestByVin(db, vin);
  assert.strictEqual(latest2.carvana.offer_usd, 22000, 'latest carvana is newer run');
  // carmax/driveway still from run-aaa (still latest for those sites)
  assert.strictEqual(latest2.carmax.offer_usd, 20500);
  assert.strictEqual(latest2.run_id, 'run-bbb', 'overall latest run surfaced');

  // getRuns groups correctly
  const runs = getRuns(db, 5);
  assert.strictEqual(runs.length, 2, 'two distinct runs');
  assert.strictEqual(runs[0].run_id, 'run-bbb', 'newest first');
  assert.strictEqual(runs[1].run_id, 'run-aaa');
  assert(runs[1].carvana && runs[1].carmax && runs[1].driveway, 'run-aaa has all three sites');
  assert.strictEqual(runs[0].rows.length, 1, 'run-bbb has 1 row');

  // Invalid site rejected
  let threw = false;
  try {
    insertOffer(db, {
      run_id: 'bad', vin, mileage: 1, zip: '06880', condition: 'Good',
      site: 'ebay', status: 'ok', ran_at: 'x',
    });
  } catch (e) { threw = true; }
  assert(threw, 'invalid site should throw');

  console.log('offers-db.test.js: all assertions passed');
}

if (require.main === module) {
  try { run(); process.exit(0); }
  catch (e) { console.error('TEST FAILURE:', e.message, e.stack); process.exit(1); }
}

module.exports = { run };
