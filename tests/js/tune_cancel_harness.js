// Day 28: Cancel Auto-tune shows "Cancelling…" at once, keeps it until the
// server says the run ended, then a plain cancelled line in the Auto-tune
// section and where the Tuning badge was; buttons come back.
const assert = require('node:assert/strict');
const I18N_T = require('../../proxy/web/i18n.js').T; // Day 32: page text lives in locales/en.json
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const htmlPath = process.argv[2] || path.join(__dirname, '../../proxy/web/index.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const a = html.indexOf('  let _tuneWasRunning = false;');
const b = html.indexOf('  // Presentation-only mirror', a);
assert.ok(a > 0 && b > a, 'tune section not found');
const c0 = html.indexOf('  $("btnOptCancel").onclick = async () => {');
const c1 = html.indexOf('\n  refreshOptimize();\n', c0);
assert.ok(c0 > 0 && c1 > c0, 'cancel handler not found');
const code = html.slice(a, b) + '\n' + html.slice(c0, c1);

class El {
  constructor(id) { this.id = id; this.hidden = false; this.disabled = false; this.textContent = '';
    const set = new Set(); this.classList = { add: (...c) => c.forEach((x) => set.add(x)),
      remove: (...c) => c.forEach((x) => set.delete(x)),
      toggle: (x, on) => { if (on === undefined ? !set.has(x) : on) set.add(x); else set.delete(x); },
      contains: (x) => set.has(x) }; }
}
const els = {};
const $ = (id) => (els[id] = els[id] || new El(id));
['btnOptStart', 'btnTuneReset', 'btnOptCancel', 'btnOptPause', 'btnLoad', 'tuneResult', 'tuneStep',
  'tuneDone', 'tuneNote', 'optProgress', 'tuneBadge', 'tuneHeaderBadge'].forEach($);

const timers = [];
const calls = [];
let server = { running: true, phase: 'A/B', step: 'Testing Prompt batch 256', schedule: [] };
const ctx = {
  $, console, JSON, Object, String, Number, Math, Date, Promise, Error, isFinite, T: I18N_T,
  setTimeout: (f, ms) => { timers.push({ f, ms }); return timers.length; }, clearTimeout: () => {},
  refreshTuneResult: () => {}, repaintUpdate: () => {},
  api: async (url, opts) => { calls.push(url); if (url === '/api/optimize/cancel') return Object.assign({}, server, { cancelling: true }); return JSON.parse(JSON.stringify(server)); },
};
vm.createContext(ctx);
vm.runInContext(code + '\n;this.__t = { paintTuneRunning, refreshOptimize, state: () => ({ cancelling: _tuneCancelling }) };', ctx);
const T = ctx.__t;

(async () => {
  T.paintTuneRunning(server);
  assert.equal(els.tuneBadge.textContent, 'Tuning…');
  assert.equal(els.btnOptCancel.hidden, false);
  assert.equal(els.btnOptCancel.textContent, 'Cancel');

  // Click Cancel: busy right away, before the server answers.
  const p = els.btnOptCancel.onclick();
  assert.equal(els.btnOptCancel.textContent, 'Cancelling…');
  assert.equal(els.btnOptCancel.disabled, true);
  assert.equal(els.tuneBadge.textContent, 'Cancelling…');
  assert.ok(els.tuneBadge.classList.contains('is-cancelling'));
  assert.ok(!els.tuneBadge.classList.contains('is-tuning'), 'campfire animation stops');
  await p;
  assert.ok(calls.includes('/api/optimize/cancel'));

  // Still running on the server (current step finishing): stays Cancelling….
  server = Object.assign({}, server, { cancelling: true });
  await T.refreshOptimize();
  assert.equal(els.btnOptCancel.textContent, 'Cancelling…');
  assert.equal(els.btnOptPause.disabled, true);
  assert.match(els.tuneStep.textContent, /^Cancelling/);

  // Server confirms: plain end line, badge says cancelled, buttons back.
  server = { running: false, phase: 'canceled', schedule: [{ name: 'ubatch', state: 'lost' }], summary: {} };
  await T.refreshOptimize();
  assert.equal(els.tuneDone.hidden, false);
  assert.equal(els.tuneDone.textContent, 'Auto-tune cancelled — your settings are unchanged.');
  assert.equal(els.tuneBadge.hidden, false);
  assert.equal(els.tuneBadge.textContent, 'Auto-tune cancelled');
  assert.equal(els.tuneHeaderBadge.textContent, 'Cancelled');
  assert.ok(els.tuneBadge.classList.contains('is-ended'));
  assert.ok(!els.tuneBadge.classList.contains('is-cancelling'));
  assert.equal(els.btnOptCancel.hidden, true);
  assert.equal(els.btnOptCancel.textContent, 'Cancel');
  assert.equal(els.btnOptStart.disabled, false);
  assert.equal(T.state().cancelling, false);

  // The idle poll does not wipe the end line early.
  await T.refreshOptimize();
  assert.equal(els.tuneBadge.textContent, 'Auto-tune cancelled');
  // Its timer clears it (no layout change: the header keeps its height in CSS).
  const t = timers.filter((x) => x.ms === 6000).pop();
  assert.ok(t, 'end line timer');
  t.f();
  assert.equal(els.tuneBadge.hidden, true);
  assert.equal(els.tuneBadge.textContent, '');

  // A run that kept a winner before Cancel says so.
  server = { running: true, phase: 'A/B', schedule: [] };
  await T.refreshOptimize();
  server = { running: false, phase: 'canceled', schedule: [{ name: 'ubatch', state: 'kept' }] };
  await T.refreshOptimize();
  assert.equal(els.tuneDone.textContent,
    'Auto-tune cancelled — kept the faster settings it found before you cancelled.');
  console.log('tune cancel harness ok');
})().catch((e) => { console.error(e); process.exit(1); });
