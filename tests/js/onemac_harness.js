const assert = require('assert/strict');
const api = require('../../proxy/web/topo_live.js');

const now = 1_000_000;
const live = (id) => ({ id, label: id, offline: false, cpu_pct: 1.8 });
const off = (id) => ({ id, label: id, offline: true });
const offCaravan = (id) => ({ id, label: id, offline: true, error: api.OFF_REASON });

assert.equal(api.STALE_MS, 15000);
assert.equal(api.isOffline(live('a'), now, now - 1000), false);
assert.equal(api.isOffline(live('a'), now, now - 15001), true);
assert.equal(api.isOffline(off('a'), now, now - 100), true);
assert.equal(api.isOffline(live('a'), now, undefined), false);

const two = [live('exo1'), live('exo2')];
const oneLive = [live('exo1'), off('exo2')];
const oneOnly = [live('exo1')];
const bothOff = [off('exo1'), off('exo2')];
const staleSecond = [live('exo1'), live('exo2')];
const fresh = { exo1: now - 1000, exo2: now - 1000 };
const stale = { exo1: now - 1000, exo2: now - 20000 };

assert.equal(api.liveCount(two, now, fresh), 2);
assert.equal(api.shouldShowSplitSections(two, now, fresh), true);
assert.equal(api.liveCount(oneLive, now, fresh), 1);
assert.equal(api.shouldShowSplitSections(oneLive, now, fresh), false);
assert.equal(api.shouldShowSplitSections(oneOnly, now, { exo1: now }), false);
assert.equal(api.shouldShowSplitSections(bothOff, now, fresh), false);
assert.equal(api.shouldShowSplitSections(staleSecond, now, stale), false);
assert.equal(api.liveCount(staleSecond, now, stale), 1);
assert.equal(api.shouldShowSplitSections([], now, {}), false);
assert.equal(api.shouldShowSplitSections(null, now, {}), false);

assert.equal(api.offlineLabel(offCaravan('x'), false), 'offline · Caravan is off');
assert.equal(api.offlineLabel(live('x'), true), 'offline');
assert.equal(api.offlineLabel(off('x'), false), 'offline');

const fs = require('fs');
const html = fs.readFileSync(require.resolve('../../proxy/web/index.html'), 'utf8');
assert(html.includes('<script src="/topo_live.js"></script>'));
assert(html.indexOf('<script src="/topo_live.js"></script>') < html.indexOf('function syncSplitSections'));
assert(html.includes('function syncSplitSections'));
assert(html.includes('function applyNodePresence'));
assert(html.includes('balancePanel') && html.includes('thunderboltPanel'));
assert(html.includes('el.hidden = !show'));
assert(html.includes('_staleOffline'));
assert(!html.includes('age > 5000'), 'old 5s stale threshold should be gone');

console.log('ok onemac');
