/**
 * Unit tests for offers-db. Runs on an in-memory SQLite so it's safe
 * on any host. Invoke with: node lib/offers-db.test.js
 */
const assert = require('assert');
const {
  openDb, insertOffer, getLatestByVin, getRuns,
  insertConsumer, listConsumers, getConsumer, listDueConsumers,
  insertPanelRun, updatePanelRun, getPanelStatus, dayOfFortnight,
} = require('./offers-db');

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

  // ----- Consumer + panel_runs CRUD -----
  const db2 = openDb(':memory:');

  // Insert 3 consumers with distinct slots/hours
  insertConsumer(db2, {
    id: 1, name: 'Westport 2022 Civic', vin: '2HGFE2F5XNH606212',
    year: 2022, make: 'Honda', model: 'Civic', trim: 'Sport',
    mileage: 36000, home_zip: '06880',
    proxy_session_id: 'cons01-stick', fingerprint_profile_id: 0,
    biweekly_slot: 0, shop_hour_local: 14,
  });
  insertConsumer(db2, {
    id: 2, name: 'Austin 2021 RAV4', vin: '4T3B6RFV8MU042044',
    mileage: 44000, home_zip: '78701',
    proxy_session_id: 'cons02-stick', fingerprint_profile_id: 5,
    biweekly_slot: 5, shop_hour_local: 17,
  });
  insertConsumer(db2, {
    id: 3, name: 'Denver 2023 RX350', vin: '2T2BAMCA9PC007784',
    mileage: 22000, home_zip: '80202', active: 0,
    proxy_session_id: 'cons03-stick', fingerprint_profile_id: 11,
    biweekly_slot: 11, shop_hour_local: 18,
  });

  const all = listConsumers(db2);
  assert.strictEqual(all.length, 3, 'three consumers inserted');
  const active = listConsumers(db2, { active: true });
  assert.strictEqual(active.length, 2, 'two active after one inactive insert');

  const c1 = getConsumer(db2, 1);
  assert(c1 && c1.vin === '2HGFE2F5XNH606212', 'getConsumer returns row');
  assert.strictEqual(getConsumer(db2, 999), null, 'missing id -> null');

  // VIN uniqueness: inserting a duplicate VIN must throw.
  let dup = false;
  try {
    insertConsumer(db2, {
      id: 99, name: 'dup', vin: '2HGFE2F5XNH606212', mileage: 1000,
      home_zip: '00000', proxy_session_id: 'cons99-stick',
      fingerprint_profile_id: 0, biweekly_slot: 0, shop_hour_local: 14,
    });
  } catch { dup = true; }
  assert(dup, 'duplicate VIN must throw');

  // Missing required field -> throw
  let miss = false;
  try { insertConsumer(db2, { id: 50, name: 'x' }); } catch { miss = true; }
  assert(miss, 'missing required -> throw');

  // dayOfFortnight returns 0..13
  const dof = dayOfFortnight(new Date());
  assert(dof >= 0 && dof <= 13, `dof within range: ${dof}`);

  // listDueConsumers filter
  // Build a Date where dof == 5 and UTC hour == 17 to match consumer 2.
  const base = new Date(Date.UTC(2026, 0, 5)); // PANEL_EPOCH
  const matchDate = new Date(base.getTime() + 5 * 86400_000);
  matchDate.setUTCHours(17, 0, 0, 0);
  const due = listDueConsumers(db2, matchDate);
  assert.strictEqual(due.length, 1, 'one consumer due at slot=5 hour=17');
  assert.strictEqual(due[0].id, 2, 'consumer 2 is the due one');

  // panel_runs insert + update
  const prId = insertPanelRun(db2, {
    consumer_id: 1, run_id: 'panel-test-1',
    scheduled_for: new Date().toISOString(),
    started_at: new Date().toISOString(),
    status: 'running',
  });
  assert(Number(prId) > 0, 'panel_runs row inserted');
  updatePanelRun(db2, prId, { status: 'done', finished_at: new Date().toISOString(), notes: 'ok' });

  // getPanelStatus summary
  const status = getPanelStatus(db2);
  assert.strictEqual(status.active_count, 2, 'status counts only active');
  assert(Array.isArray(status.rows), 'status has rows array');
  assert.strictEqual(status.rows.length, 2, 'two rows for two active consumers');

  // Insert an offer for consumer 1 and make sure it surfaces in status
  insertOffer(db2, {
    run_id: 'panel-test-1', vin: '2HGFE2F5XNH606212', mileage: 36000, zip: '06880',
    condition: 'Good', site: 'carvana', status: 'ok', offer_usd: 18500,
    ran_at: new Date().toISOString(), duration_ms: 120000,
  });
  const status2 = getPanelStatus(db2);
  const row1 = status2.rows.find((r) => r.consumer.id === 1);
  assert(row1 && row1.latest.carvana && row1.latest.carvana.offer_usd === 18500,
    'panel status surfaces latest carvana offer');
  assert(row1.last_ran_at, 'panel status surfaces last_ran_at');
  assert(row1.next_scheduled_at, 'panel status computes next_scheduled_at');

  console.log('offers-db.test.js: all assertions passed');
}

if (require.main === module) {
  try { run(); process.exit(0); }
  catch (e) { console.error('TEST FAILURE:', e.message, e.stack); process.exit(1); }
}

module.exports = { run };
