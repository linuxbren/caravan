/* Guess-ahead consent stays separate from theme/layout code. */
(() => {
  let offer = null, shown = '', job = null;
  const dialog = document.createElement('dialog');
  dialog.className = 'panel'; dialog.style.maxWidth = '520px';
  const title = document.createElement('h3'); title.textContent = 'Guess-ahead helper';
  const text = document.createElement('p'), status = document.createElement('p');
  const yes = document.createElement('button'), no = document.createElement('button');
  yes.textContent = 'Download'; no.textContent = 'Not now';
  const stop = document.createElement('button'); stop.textContent='Stop download'; stop.hidden=true;
  const close = document.createElement('button'); close.textContent='Close'; close.onclick=()=>dialog.close();
  dialog.append(title, text, status, yes, no, stop, close); document.body.append(dialog);
  stop.onclick = async () => { try { await api('/api/picker/download/cancel', {job_id:job.id}); } catch(e) {status.textContent=e.message;} };
  async function api(path, body) {
    const r = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {});
    const j = await r.json(); if (!r.ok) throw Error(j.error || 'Request failed'); return j;
  }
  function show() { text.textContent = offer.message + ' Runs on the lead Mini; used on the next load. Size is the pairing-table estimate.'; status.textContent = ''; yes.hidden = no.hidden = false; if (!dialog.open) dialog.showModal(); }
  no.onclick = async () => { try { await api('/api/helpers/answer', {helper_id:offer.id, action:'decline'}); dialog.close(); } catch(e) {status.textContent=e.message;} };
  // Escape is Not now for this visit, not persistent consent.
  dialog.addEventListener('cancel', () => { shown = offer?.id || ''; });
  yes.onclick = async () => {
    yes.disabled = true;
    try {
      const j = await api('/api/helpers/answer', {helper_id:offer.id, action:'download'});
      job = j.job; yes.hidden = no.hidden = true; stop.hidden=false; status.textContent = 'Starting download…';
    } catch(e) { status.textContent = e.message; }
    finally {yes.disabled = false;}
  };
  function offerKey(o) {
    return (o && !o.declined && o.id) ? String(o.id) : '';
  }

  // Keep the Helper download button in a reserved slot on the Guess-ahead
  // row (inside Advanced). Create it once; identical later polls must not
  // replace it or the row will jump.
  function paintHelperButton() {
    const row = document.querySelector('.opt[data-id="guess_ahead"]');
    if (!row) return null;
    let slot = row.querySelector('[data-helper-slot]');
    if (!slot) {
      slot = document.createElement('div');
      slot.className = 'helper-slot';
      slot.dataset.helperSlot = '1';
      row.append(slot);
    }
    let b = slot.querySelector('[data-helper]');
    if (!b) {
      b = document.createElement('button');
      b.type = 'button';
      b.dataset.helper = '1';
      b.textContent = 'Helper download…';
      slot.append(b);
    }
    b.onclick = () => { if (offer) show(); else alert('No missing compatible helper for the loaded split MLX model.'); };
    return b;
  }

  // One /api/helpers response. Returns whether the button DOM was written.
  // Repeated identical polls with the button already present are a no-op.
  function applyHelperPoll(data) {
    const next = (data && data.offer) || null;
    const prevKey = offerKey(offer);
    const nextKey = offerKey(next);
    offer = next;
    const button = document.querySelector('.opt[data-id="guess_ahead"] [data-helper]');
    let wrote = false;
    if (!button) {
      paintHelperButton();
      wrote = true;
    }
    // Day 27: the one-line offer under the model (helper_line.js) replaces the pop-up.
    if (offer && !offer.declined && shown !== offer.id && !window.caravanHelperLine) { shown = offer.id; show(); }
    return { changed: wrote || prevKey !== nextKey, wrote, offerKey: nextKey };
  }

  async function refresh() {
    try {
      if (job) {
        job = await api('/api/picker/jobs/' + job.id).then(j => j.job || j);
        const p = Object.values(job.progress || {})[0] || {};
        stop.hidden = !['queued','running'].includes(job.status);
        status.textContent = job.status === 'done' ? 'Downloaded. It will be used on the next model load.' : job.status + ' · ' + (p.msg || 'starting…');
        if (['error','cancelled'].includes(job.status)) {
          yes.hidden = false; yes.textContent = 'Resume';
          yes.onclick = async () => { try { const r = await api('/api/picker/download/resume', {job_id:job.id}); job = r.job; yes.hidden = true; } catch(e) {status.textContent=e.message;} };
        }
        return;
      }
      applyHelperPoll(await api('/api/helpers'));
    } catch (_) { /* Retry on next tick if web server is restarting. */ }
  }
  window.paintHelperButton = paintHelperButton;
  window.applyHelperPoll = applyHelperPoll;
  window.helperOfferKey = offerKey;
  setInterval(refresh, 3000); refresh();
})();
