// Update now must not reload the page for the previous run's "done".
// Runs the update section of proxy/web/index.html with a tiny fake DOM:
// old "done" progress + click + slow server reply => no reload until the
// new run finishes, then exactly one reload.
const assert = require('node:assert/strict');
const I18N_T = require('../../proxy/web/i18n.js').T; // Day 32: page text lives in locales/en.json
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const htmlPath = process.argv[2] || path.join(__dirname, '../../proxy/web/index.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const start = html.indexOf('  const UPDATE_PENDING_KEY');
const endMark = '\n  refreshUpdate();\n';
const end = html.indexOf(endMark, start);
assert.ok(start > 0 && end > start, 'update section not found');
const code = html.slice(start, end);

class El {
  constructor(id) { this.id = id; this.hidden = false; this.disabled = false; this.textContent = '';
    this.title = ''; this.listeners = {}; this.children = []; this.attrs = {};
    const set = new Set(); this.classList = { add: (c) => set.add(c), remove: (c) => set.delete(c),
      toggle: (c, on) => { if (on === undefined ? !set.has(c) : on) set.add(c); else set.delete(c); },
      contains: (c) => set.has(c) }; }
  addEventListener(k, f) { this.listeners[k] = f; }
  replaceChildren() { this.children = []; }
  appendChild(e) { this.children.push(e); return e; }
  append(e) { this.children.push(e); }
  setAttribute(k, v) { this.attrs[k] = v; }
  scrollIntoView() {}
}
const els = {};
const $ = (id) => (els[id] = els[id] || new El(id));
for (const id of ['updatesCard', 'updateStatus', 'updateChanges', 'updateChangesLabel', 'btnUpdateNow',
  'btnUpdateRetry', 'btnUpdateCheck', 'updateStep', 'updateMacs', 'updateHeaderBadge', 'updateDailySwitch', 'input']) $(id);

function store() { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null),
  setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; }

let reloads = 0;
const timers = [];
const pendingCalls = [];
let handler = null;
const ctx = {
  $, console, JSON, Object, String, Number, Math, Date, Promise, Error, T: I18N_T,
  localStorage: store(), sessionStorage: store(),
  location: { reload: () => { reloads++; }, search: '' },
  document: { querySelectorAll: () => [], addEventListener: () => {}, createElement: (t) => new El(t),
    activeElement: null, body: null, visibilityState: 'visible' },
  window: {}, confirm: () => true, openDrawer: () => {}, _tuneRunning: false,
  setTimeout: (f) => { timers.push(f); return timers.length; }, clearTimeout: () => {},
  setInterval: () => 0, clearInterval: () => {},
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  api: (url, opts) => new Promise((resolve, reject) => { pendingCalls.push({ url, opts: opts || {}, resolve, reject }); }),
};
ctx.window = ctx; ctx.state = { streaming: false };
vm.createContext(ctx);
vm.runInContext(code + '\n;this.__u = { renderUpdate, refreshUpdate, repaint: (typeof repaintUpdate === "function") ? repaintUpdate : () => { if (_updateInfo) renderUpdate(_updateInfo); } };', ctx);
const U = ctx.__u;

const OLD = { phase: 'done', started_at: 1794620000.5, finished_at: 1794620050.5 };
const NEW_START = 1794700590.7;
function upd(progress, extra) {
  return Object.assign({ show: true, packaged: true, check_daily: true, newer: true, can_apply: true,
    changes: ['x'], macs: [{ id: 'local', label: '1st Mac', mine: true, status: 'update needed' }],
    progress, updating: progress && progress.phase === 'updating', step: null, page: 'tag-old' }, extra || {});
}
const tick = () => new Promise((r) => setImmediate(r));

(async () => {
  // Page open and idle: the last answer still carries the previous run's "done".
  U.renderUpdate(upd(OLD));
  assert.equal(reloads, 0);
  // Click Update now. The server is slow to answer.
  $('btnUpdateNow').listeners.click();
  await tick();
  const apply = pendingCalls.find((c) => c.opts.body && c.opts.body.includes('apply'));
  assert.ok(apply, 'apply was sent');
  assert.equal($('btnUpdateNow').textContent, 'Updating…', 'busy right away');
  // Auto-tune / chat repaint, plus a poll answer that still shows the old run.
  for (let i = 0; i < 5; i++) U.repaint();
  U.renderUpdate(upd(OLD));
  assert.equal(reloads, 0, 'no reload for the previous run while the update starts');
  assert.notEqual($('updateStep').textContent, 'Done.', 'no false Done for the old run');
  // The server answers: the new run is going.
  apply.resolve(upd({ phase: 'updating', started_at: NEW_START, finished_at: null }, { newer: true, can_apply: false }));
  await tick();
  U.repaint();
  U.renderUpdate(upd({ phase: 'updating', started_at: NEW_START, finished_at: null }));
  assert.equal(reloads, 0, 'no reload while the new run is going');
  // The new run finishes: exactly one reload.
  U.renderUpdate(upd({ phase: 'done', started_at: NEW_START, finished_at: NEW_START + 49 }, { newer: false }));
  assert.equal(reloads, 1, 'one reload when the new run finishes');
  U.renderUpdate(upd({ phase: 'done', started_at: NEW_START, finished_at: NEW_START + 49 }, { newer: false }));
  assert.equal(reloads, 1, 'only once');
  console.log('ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
