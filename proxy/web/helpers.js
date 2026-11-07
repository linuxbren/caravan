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
      offer = (await api('/api/helpers')).offer;
      const row = document.querySelector('.opt[data-id="guess_ahead"]');
      if (row && !row.querySelector('[data-helper]')) {
        const b = document.createElement('button'); b.dataset.helper='1'; b.textContent='Helper download…';
        b.onclick=()=> { if (offer) show(); else alert('No missing compatible helper for the loaded split MLX model.'); }; row.append(b);
      }
      if (offer && !offer.declined && shown !== offer.id) { shown=offer.id; show(); }
    } catch (_) { /* Retry on next tick if web server is restarting. */ }
  }
  setInterval(refresh, 3000); refresh();
})();
