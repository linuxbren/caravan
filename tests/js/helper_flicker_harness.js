// Settings Helper-download button: repeated identical polls must not
// remove, recreate, or toggle the button (that jump was the Day 24 flicker).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function camel(name) {
  return name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

class El {
  constructor(tag = 'div') {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.style = {};
    this.listeners = {};
    this._text = '';
    this.className = '';
    this.hidden = false;
    this.disabled = false;
    this.parent = null;
    this.onclick = null;
    this.type = '';
    this.open = false;
    this.id = '';
    this._innerWrites = 0;
    this._appends = 0;
  }
  set textContent(v) { this._text = String(v == null ? '' : v); }
  get textContent() { return this._text; }
  set innerHTML(v) {
    this._innerWrites++;
    this._text = '';
    this.children = [];
    this._html = String(v == null ? '' : v);
  }
  get innerHTML() { return this._html || ''; }
  setAttribute(k, v) {
    this.attrs[k] = v;
    if (k === 'id') this.id = v;
    if (k.startsWith('data-')) this.dataset[camel(k.slice(5))] = String(v);
  }
  append(...els) {
    this._appends++;
    for (const e of els) {
      if (!e || typeof e !== 'object') continue;
      e.parent = this;
      this.children.push(e);
    }
  }
  appendChild(e) { this.append(e); return e; }
  addEventListener(k, f) { this.listeners[k] = f; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const out = [];
    const walk = (el) => {
      if (matches(el, sel, this)) out.push(el);
      for (const c of el.children) walk(c);
    };
    for (const c of this.children) walk(c);
    return out;
  }
}

function matchesSimple(el, sel) {
  sel = sel.trim();
  if (sel === '[data-helper]') return el.dataset.helper != null;
  if (sel === '[data-helper-slot]') return el.dataset.helperSlot != null;
  if (sel === '.opt[data-id="guess_ahead"]') {
    return String(el.className).includes('opt') && el.dataset.id === 'guess_ahead';
  }
  if (sel === '.opt[data-id="self_tune"]') {
    return String(el.className).includes('opt') && el.dataset.id === 'self_tune';
  }
  if (sel === '#optRows') return el.id === 'optRows';
  if (sel === '#optAdvancedRows') return el.id === 'optAdvancedRows';
  return false;
}

function matches(el, sel, root) {
  const parts = sel.trim().split(/\s+/);
  if (parts.length === 1) return matchesSimple(el, parts[0]);
  // descendant: last simple selector on el, earlier on an ancestor
  if (!matchesSimple(el, parts[parts.length - 1])) return false;
  const ancestorSel = parts.slice(0, -1).join(' ');
  let p = el.parent;
  while (p && p !== root) {
    if (matches(p, ancestorSel, root)) return true;
    p = p.parent;
  }
  return false;
}

function setup() {
  const body = new El('body');
  const optRows = new El('div');
  optRows.id = 'optRows';
  const adv = new El('div');
  adv.id = 'optAdvancedRows';
  const selfTune = new El('div');
  selfTune.className = 'opt';
  selfTune.dataset.id = 'self_tune';
  selfTune.setAttribute('data-id', 'self_tune');
  const guess = new El('div');
  guess.className = 'opt';
  guess.dataset.id = 'guess_ahead';
  guess.setAttribute('data-id', 'guess_ahead');
  const slot = new El('div');
  slot.className = 'helper-slot';
  slot.dataset.helperSlot = '1';
  slot.setAttribute('data-helper-slot', '1');
  const btn = new El('button');
  btn.type = 'button';
  btn.dataset.helper = '1';
  btn.setAttribute('data-helper', '1');
  btn.textContent = 'Helper download…';
  slot.append(btn);
  guess.append(slot);
  optRows.append(selfTune);
  adv.append(guess);
  body.append(optRows, adv);

  const document = {
    body,
    createElement: (tag) => new El(tag),
    querySelector: (sel) => {
      if (sel === '.opt[data-id="guess_ahead"]') return guess;
      if (sel === '.opt[data-id="guess_ahead"] [data-helper]') {
        return guess.querySelector('[data-helper]');
      }
      if (sel === '.opt[data-id="self_tune"]') return selfTune;
      return body.querySelector(sel);
    },
    querySelectorAll: (sel) => body.querySelectorAll(sel),
    getElementById: (id) => (id === 'optRows' ? optRows : id === 'optAdvancedRows' ? adv : null),
  };
  const window = { paintHelperButton: null, applyHelperPoll: null, helperOfferKey: null };
  const timers = [];
  const fetchCalls = [];
  const ctx = {
    document, window, console,
    setInterval: (f) => { timers.push(f); return timers.length; },
    clearInterval() {},
    fetch: async (url) => {
      fetchCalls.push(url);
      return { ok: true, json: async () => ({ offer: currentOffer }) };
    },
    alert() {},
    Error,
    Object, String, JSON, Promise,
  };
  let currentOffer = { id: 'helper-qwen', message: 'A helper is available.', declined: false };
  const src = fs.readFileSync(path.join(__dirname, '../../proxy/web/helpers.js'), 'utf8');
  vm.runInNewContext(src, ctx);
  return {
    document, window, body, optRows, adv, guess, slot, btn, fetchCalls, timers,
    setOffer(o) { currentOffer = o; },
  };
}

function countButtons(root) {
  const walk = (el, acc) => {
    if (el.dataset && el.dataset.helper) acc.push(el);
    for (const c of el.children || []) walk(c, acc);
    return acc;
  };
  return walk(root, []);
}

(async () => {
  const name = process.argv[2];
  const s = setup();

  if (name === 'identical_polls_do_not_toggle') {
    const first = s.window.applyHelperPoll({ offer: { id: 'helper-qwen', message: 'A helper is available.' } });
    const button = s.document.querySelector('.opt[data-id="guess_ahead"] [data-helper]');
    assert.ok(button, 'button should exist after first poll');
    assert.equal(countButtons(s.guess).length, 1);
    const appendsAfterFirst = s.guess._appends + s.slot._appends;
    const writesAfterFirst = s.guess._innerWrites + s.slot._innerWrites;
    for (let i = 0; i < 20; i++) {
      const r = s.window.applyHelperPoll({ offer: { id: 'helper-qwen', message: 'A helper is available.' } });
      assert.equal(r.wrote, false, 'identical poll must not write the button DOM');
      assert.equal(r.offerKey, 'helper-qwen');
      const again = s.document.querySelector('.opt[data-id="guess_ahead"] [data-helper]');
      assert.equal(again, button, 'same button element must be kept');
      assert.equal(countButtons(s.guess).length, 1, 'never two Helper buttons');
    }
    assert.equal(s.guess._appends + s.slot._appends, appendsAfterFirst, 'no further appends');
    assert.equal(s.guess._innerWrites + s.slot._innerWrites, writesAfterFirst, 'no innerHTML wipes');
    // First poll found the reserved button already in the row: also no write.
    assert.equal(first.wrote, false);
  } else if (name === 'restore_after_wipe_then_stable') {
    // Simulate the old bug: renderOpts replaced innerHTML, wiping the button.
    s.guess.innerHTML = '';
    s.guess.children = [];
    assert.equal(countButtons(s.guess).length, 0);
    const r1 = s.window.applyHelperPoll({ offer: { id: 'helper-qwen', message: 'x' } });
    assert.equal(r1.wrote, true);
    const button = s.document.querySelector('.opt[data-id="guess_ahead"] [data-helper]');
    assert.ok(button);
    assert.equal(button.textContent, 'Helper download…');
    assert.equal(countButtons(s.guess).length, 1);
    for (let i = 0; i < 10; i++) {
      const r = s.window.applyHelperPoll({ offer: { id: 'helper-qwen', message: 'x' } });
      assert.equal(r.wrote, false);
      assert.equal(s.document.querySelector('.opt[data-id="guess_ahead"] [data-helper]'), button);
      assert.equal(countButtons(s.guess).length, 1);
    }
  } else if (name === 'render_skip_and_polls_together') {
    // Production contract: renderOpts is a no-op when its signature is unchanged.
    const state = { choice: { self_tune: 'auto', guess_ahead: 'auto' }, filePins: {}, opts: ['self_tune', 'guess_ahead'] };
    let lastSig = null;
    let rebuilds = 0;
    function sig() { return JSON.stringify(state); }
    function renderOpts() {
      if (sig() === lastSig && s.optRows.querySelector('.opt[data-id="self_tune"]')) return;
      lastSig = sig();
      rebuilds++;
      // A real rebuild would replace Advanced innerHTML; skip must prevent this.
      s.adv.innerHTML = 'wiped';
    }
    // Already painted at this signature (same as after the first loadOpts).
    lastSig = sig();
    const button = s.document.querySelector('.opt[data-id="guess_ahead"] [data-helper]');
    const writes = s.adv._innerWrites;
    for (let i = 0; i < 15; i++) {
      renderOpts();
      s.window.applyHelperPoll({ offer: { id: 'helper-qwen', message: 'x' } });
    }
    assert.equal(rebuilds, 0, 'identical Settings state must not rebuild');
    assert.equal(s.adv._innerWrites, writes, 'Advanced rows are not wiped on later polls');
    assert.equal(s.document.querySelector('.opt[data-id="guess_ahead"] [data-helper]'), button);
    assert.equal(countButtons(s.guess).length, 1);
    // A real state change may rebuild.
    state.choice.guess_ahead = 'on';
    renderOpts();
    assert.equal(rebuilds, 1);
  } else {
    throw new Error('unknown test ' + name);
  }
  console.log('ok ' + name);
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
