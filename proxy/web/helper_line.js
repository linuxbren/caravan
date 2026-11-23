/* Day 27: one short line under the model offering a missing Guess-ahead
   helper. Never downloads without a click on Download. "Not now" is
   remembered per model on the server and never asks again. Hidden on the
   plain-LAN view (the server says lan:true and we stop asking). */
(() => {
  window.caravanHelperLine = true;
  let offer = null, job = null, stopped = false, note = '';
  const line = () => document.getElementById('helperLine');
  async function api(path, body) {
    const r = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw Error(j.error || T('web.request_failed'));
    return j;
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }
  function mbText(o) { return o && o.size_mb ? ' (' + (o.size_mb >= 1000 ? T(`web.v_gb`, {v: ((o.size_mb / 1000).toFixed(1))}) : T(`web.size_mb_mb`, {size_mb: (o.size_mb)})) + ')' : ''; }
  function paint() {
    const el = line();
    if (!el) return;
    if (job) {
      const p = Object.values(job.progress || {})[0] || {};
      const st = job.status;
      const pct = st === 'done' ? 100 : (p.pct || 0);
      let text;
      if (st === 'done') text = T('web.helper_ready_guess_ahead_is_on');
      else if (st === 'error' || st === 'cancelled') text = T('web.helper_download_stopped');
      else text = T(`web.downloading_helper_pct_v`, {pct, v: p.speed_bps ? T(`web.v_mb_s_2`, {v: (p.speed_bps / 1e6).toFixed(1)}) : ''});
      const running = ['queued', 'running'].includes(st);
      el.innerHTML = '<span>' + esc(text) + '</span>' +
        (running ? ` <button type="button" class="ghost" data-hl="stop">${T("web.stop")}</button>` : '') +
        (st === 'error' || st === 'cancelled' ? ` <button type="button" class="ghost" data-hl="resume">${T("web.resume")}</button>` : '') +
        (st === 'done' ? ` <button type="button" class="ghost" data-hl="ok">${T("web.ok")}</button>` : '') +
        (running ? '<div class="bar"><i style="width:' + pct + '%"></i></div>' : '');
      el.hidden = false;
    } else if (offer) {
      el.innerHTML = '<span>' + esc(offer.message || T('web.download_helper_for_faster_replies')) + esc(mbText(offer)) + '</span> ' +
        `<button type="button" class="primary" data-hl="yes">${T("web.download")}</button> ` +
        `<button type="button" class="ghost" data-hl="no">${T("web.not_now")}</button>` +
        (note ? '<div class="j-sub">' + esc(note) + '</div>' : '');
      el.hidden = false;
    } else {
      el.innerHTML = '';
      el.hidden = true;
    }
    el.querySelectorAll('[data-hl]').forEach((b) => { b.onclick = () => { el.querySelectorAll('[data-hl]').forEach((x) => { x.disabled = true; }); b.textContent = ({yes: T('web.starting_2'), no: T('web.not_now'), stop: T('web.stopping'), resume: T('web.resuming'), ok: 'OK'})[b.dataset.hl] || b.textContent; act(b.dataset.hl); }; });
  }
  async function act(what) {
    note = '';
    try {
      if (what === 'yes' && offer) {
        const r = await api('/api/helper-offer/answer', {model: offer.model, helper_id: offer.id, action: 'download'});
        job = r.job || null; offer = null;
      } else if (what === 'no' && offer) {
        await api('/api/helper-offer/answer', {model: offer.model, helper_id: offer.id, action: 'not_now'});
        offer = null;
      } else if (what === 'stop' && job) {
        await api('/api/picker/download/cancel', {job_id: job.id});
      } else if (what === 'resume' && job) {
        const r = await api('/api/picker/download/resume', {job_id: job.id});
        job = r.job || job;
      } else if (what === 'ok') {
        job = null;
        window.dispatchEvent(new CustomEvent('caravan-models-changed'));
      }
    } catch (e) { note = e.message; }
    paint();
  }
  // One /api/helper-offer response. Returns whether the line changed.
  function applyHelperOffer(data) {
    if (data && data.lan) { stopped = true; offer = null; paint(); return true; }
    const next = (data && data.offer) || null;
    const changed = JSON.stringify(next) !== JSON.stringify(offer);
    offer = next;
    if (changed) paint();
    return changed;
  }
  async function refresh() {
    if (stopped) return;
    try {
      if (job) {
        if (['queued', 'running', 'cancelling'].includes(job.status)) {
          const j = await api('/api/picker/jobs/' + job.id);
          job = j.job || j;
          paint();
        }
        return;
      }
      applyHelperOffer(await api('/api/helper-offer'));
    } catch (_) { /* web server restarting: try again next tick */ }
  }
  window.applyHelperOffer = applyHelperOffer;
  // The Helper download button started a download: show its progress here.
  window.helperLineShowJob = (j) => { if (j) { job = j; offer = null; stopped = false; paint(); } };
  setInterval(refresh, 4000); refresh();
})();
