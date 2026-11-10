/* Read-only preview until the explicit reload button. Same API as a future TUI. */
(() => {
  const $ = id => document.getElementById(id);
  let plan = null, counts = null, revision = 0, timer, measuredModel = null, adjusting = false;
  const V = window.CaravanBalanceView;
  const memory = $("balanceMemory"), controls = $("balanceControls"), technical = $("balanceTechnical");
  const preview = $("balancePreview"), apply = $("balanceApply");
  const text = (tag, value) => { const el = document.createElement(tag); el.textContent = value; return el; };
  const model = () => $("balanceModel").value || $("modelSelect").value;
  const fetchButton = $("balanceFetch");
  let jobId = null;
  const request = () => ({model_id: model(), counts, repo_id: $("balanceRepo").value.trim() || undefined,
                          gguf_file: $("balanceFile").value.trim() || undefined});
  async function models() {
    const response = await fetch('/api/models'), result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Cannot list installed models');
    const chosen = model(), select = $("balanceModel");
    select.replaceChildren();
    (result.models || []).forEach(m => {
      const option = text('option', m.name + (m.usable === false ? ' (files/fit not ready)' : ''));
      option.value = m.id; option.selected = m.id === chosen; select.append(option);
    });
  }
  function mode() {
    $("balanceMode").textContent = adjusting ? "Adjusting" : "Auto · recommended";
    $("balanceModeHelp").textContent = adjusting ? "Your split · preview only" : "Auto · Caravan shares the work for you";
    $("balanceAdjust").setAttribute("aria-expanded", String(adjusting));
    $("balanceAdjust").disabled = adjusting || !plan;
    $("balanceAuto").disabled = !adjusting;
    controls.hidden = !adjusting;
  }
  function invalidate(message) {
    ++revision; plan = null; apply.disabled = true; fetchButton.disabled = true;
    memory.setAttribute("aria-busy", "true");
    if (message) preview.textContent = message;
  }
  function draw(next) {
    memory.replaceChildren(); controls.replaceChildren(); technical.replaceChildren();
    $("balanceModelName").textContent = `${$("balanceModel").selectedOptions[0]?.textContent || model()} · ${next.stages.length} ${next.stages.length === 1 ? 'Mini' : 'Minis'} · memory estimates, not speed`;
    next.stages.forEach((stage, i) => {
      const c = V.card(stage), gb = n => n == null ? 'unknown' : (n/1e9).toFixed(2) + ' GB';
      const card = text('article', ''); card.className = 'balance-card' + (c.safe ? '' : ' unsafe');
      const head = text('div', ''); head.className='balance-card-head'; head.append(text('strong', c.label), text('span', 'Estimated memory'));
      const bar = text('div', ''); bar.className='balance-bar'; bar.setAttribute('role','img');
      bar.setAttribute('aria-label', c.known ? `${c.label}: estimated ${stage.estimated_use_gb} GB of ${c.capacity} GB usable model budget` : `${c.label}: memory unknown`);
      const fill=text('i',''); fill.style.width=c.percent+'%'; bar.append(fill);
      const values=text('div',''); values.className='balance-card-values';
      values.append(text('span',c.known ? `≈${stage.estimated_use_gb.toFixed(2)} GB for model` : 'Model memory unknown'), text('span',c.known ? `≈${stage.headroom_gb.toFixed(2)} GB left` : 'Free memory unknown'));
      card.append(head,bar,values,text('small',c.known ? `Usable model budget ${c.capacity.toFixed(2)} GB · room reserved for macOS and other apps` : 'Refresh when this Mini is reachable.'));
      if (!c.safe) card.append(text('small','Not enough known free memory. Apply is blocked.'));
      memory.append(card);
      technical.append(text('p', `${stage.label}: ${next.format === 'gguf' ? 'device share ' + next.counts[i] : 'layers '+stage.range[0]+'–'+(stage.range[1]-1)} · ${stage.safe ? 'memory fits' : 'too tight'} · minimum margin ${next.margin_gb} GB`));
      technical.append(text('p', `${stage.label} disk: ${gb(stage.on_disk_bytes)} logical · ${gb(stage.allocated_bytes)} allocated${stage.cache_scope ? ' · ' + stage.cache_scope + (stage.cache_path ? ' ('+stage.cache_path+')' : '') : ''}`));
      if ((stage.links || []).length) technical.append(text('small','Linked files left untouched: '+stage.links.join(', ')+'. Use the real model folder for selective fetching.'));
      if (stage.not_needed_for_plan === null) technical.append(text('small','Retained files unknown.'));
      else if ((stage.not_needed_for_plan || []).length) technical.append(text('p', `Not needed for this plan, kept on disk (${gb(stage.retained_bytes)}): ${stage.not_needed_for_plan.join(', ')}. Other splits/models may still need these; nothing is deleted.`));
      const downloads = stage.downloads;
      technical.append(text('small', downloads === null ? 'Files unknown; reload blocked.' : downloads.length ? `Download from source: ${downloads.join(', ')}${stage.download_bytes == null ? '' : ` (≈${(stage.download_bytes/1e9).toFixed(2)} GB)`}` : 'Required shards already here.'));
      if (!stage.metadata_ready) technical.append(text('p','Config, index or tokenizer is missing; reload blocked.'));
      if (!adjusting) return;
      const row=text('div',''); row.className='balance-boundary';
      if (next.format === 'gguf') {
        const share=document.createElement('input'); share.type='number'; share.min='0.1'; share.step='0.1'; share.value=next.counts[i];
        share.id='balanceShare'+i; share.setAttribute('aria-label','GGUF share for '+stage.label);
        const label=text('label',stage.label+' device share (proportion, not layers)'); label.htmlFor=share.id;
        share.oninput=() => {
          counts=[...(counts || next.counts)]; counts[i]=Number(share.value);
          invalidate('Preview: checking your new memory split…'); clearTimeout(timer);
          if (!Number.isFinite(counts[i]) || counts[i]<=0) { preview.textContent='Enter a positive device share. Apply is blocked.'; return; }
          timer=setTimeout(refresh,200);
        };
        row.append(label,share); controls.append(row);
      } else if (i < next.stages.length-1) {
        const input=document.createElement('input'); input.type='range'; input.step='1'; input.id='balanceBoundary'+i;
        input.min=stage.range[0]+1; input.max=next.stages[i+1].range[1]-1; input.value=stage.range[1];
        input.setAttribute('aria-label', `Layer boundary after ${stage.label}`);
        const label=text('label', `${stage.label} ↔ ${next.stages[i+1].label} · ${next.counts[i]} / ${next.counts[i+1]} layers`); label.htmlFor=input.id;
        input.oninput=() => {
          counts=V.moveBoundary(counts || next.counts,i,input.value);
          label.textContent=`${stage.label} ↔ ${next.stages[i+1].label} · ${counts[i]} / ${counts[i+1]} layers`;
          invalidate(`Preview: ${next.stages.map((s,j)=>`${s.label} ${counts[j]} layers`).join(' · ')} · checking memory…`);
          clearTimeout(timer); timer=setTimeout(refresh,200);
        };
        row.append(label,input); controls.append(row);
      }
    });
    technical.append(text('p',next.note));
    preview.textContent=V.summary(next,adjusting) + (next.ready ? '' : ' Check Technical details before applying.');
    apply.disabled=!next.ready || !next.stages.every(s=>V.card(s).safe);
    fetchButton.disabled=!!jobId || next.stages.some(s=>s.downloads===null) || !next.stages.some(s=>s.downloads.length || !s.metadata_ready);
    mode();
  }
  async function refresh() {
    invalidate('Checking each Mini’s files and memory…');
    const version=revision, mid=model();
    try {
      const response=await fetch('/api/balance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request())});
      const next=await response.json();
      if (version!==revision || mid!==model()) return;
      if (!response.ok) throw new Error(next.error || 'Preview unavailable');
      if (!V.valid(next)) throw new Error('Invalid preview; Apply is blocked.');
      plan=next; memory.setAttribute('aria-busy','false'); draw(next);
    } catch(error) {
      if (version!==revision || mid!==model()) return;
      plan=null; memory.replaceChildren(); controls.replaceChildren(); technical.replaceChildren();
      memory.setAttribute('aria-busy','false'); preview.textContent=error.message; mode();
    }
  }
  async function reset(reloadModels=false) {
    counts=null; adjusting=false; clearTimeout(timer); invalidate('Checking each Mini’s files and memory…');
    controls.replaceChildren(); mode(); const version=revision;
    try { if (reloadModels) await models(); if (version===revision) await refresh(); }
    catch(error) { if (version===revision) { preview.textContent=error.message; mode(); } }
  }
  $('balanceAdjust').onclick=() => { if (!plan) return; adjusting=true; counts=[...plan.counts]; draw(plan); };
  $('balanceAuto').onclick=() => reset();
  $('balanceRefresh').onclick=() => { clearTimeout(timer); refresh(); };
  $('balanceModel').onchange=() => reset();
  [$('balanceRepo'),$('balanceFile')].forEach(el=>el.oninput=()=>{
    clearTimeout(timer); invalidate('Source changed. Refresh preview before applying.');
    memory.replaceChildren(); controls.replaceChildren(); mode();
  });
  $('btnOpenTopo').addEventListener('click',()=>{
    if ($('topoDrawer').classList.contains('open')) reset(true);
  });
  fetchButton.onclick = async () => {
    if (!plan || jobId) return;
    counts = [...plan.counts]; // Freeze the plan being fetched; do not chase changing free RAM.
    const submitted = {...request(), counts, node_ids: plan.node_ids};
    fetchButton.disabled=true; apply.disabled=true;
    try {
      const response = await fetch('/api/files/fetch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(submitted)});
      const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Fetch failed');
      jobId=result.job.id; $("balanceStop").disabled=false;
      const poll = async () => {
        try {
          const r=await fetch('/api/picker/jobs/'+jobId), j=await r.json();
          if (!r.ok) throw new Error(j.error || 'Cannot read fetch status');
          const nodes=Object.entries(j.progress||{}).filter(([id]) => id!=='lead' && id!=='packer');
          $("balanceJob").textContent = `${j.status}: `+nodes.map(([id,p])=>`${p.label||id}: ${p.stage||p.msg||'waiting'}`).join(' · ')+(j.error ? ' — '+j.error : '');
          if (['done','error','cancelled'].includes(j.status)) { jobId=null; $("balanceStop").disabled=true; await refresh(); }
          else setTimeout(poll,1500);
        } catch(error) { $("balanceJob").textContent=error.message+'; fetch may still be running. Check Downloads before starting another.'; }
      }; poll();
    } catch(error) { preview.append(text('p',error.message)); await refresh(); }
  };
  $("balanceStop").onclick = async () => {
    if (!jobId) return;
    $("balanceStop").disabled=true;
    try { const r=await fetch('/api/picker/download/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId})});
      if (!r.ok) throw new Error('Could not stop fetch; inspect Downloads');
    } catch(error) { $("balanceJob").textContent=error.message; }
  };
  $("modelSelect").addEventListener("change", () => {
    $("balanceModel").value = $("modelSelect").value;
    measuredModel = null; $("balanceSpeed").textContent = "Real speed will appear after reload and a reply.";
    reset(true);
  });
  apply.onclick = async () => {
    if (!plan || !plan.ready || apply.disabled) return;
    clearTimeout(timer);
    const submittedPlan=plan; ++revision; plan=null;
    apply.disabled = true;
    measuredModel = null;
    try {
      const response = await fetch("/api/models/load", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...request(), model_id: submittedPlan.model_id, node_ids: submittedPlan.node_ids, counts: submittedPlan.counts, balance: true})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Reload failed");
      measuredModel = submittedPlan.model_id;
      $("balanceSpeed").textContent = "Reload requested. Wait for Ready, then send a reply to measure speed.";
    } catch (error) {
      preview.append(text("p", error.message));
    }
    // Never re-enable from a stale preview: get a fresh memory/file plan.
    plan = null; mode();
  };
  window.addEventListener("caravan-reply-stats", event => {
    const {stats, model: mid} = event.detail;
    if (measuredModel && mid === measuredModel && stats.write_tok_s != null) {
      $("balanceSpeed").textContent = `Measured after reload: ${Number(stats.write_tok_s).toFixed(2)} tok/s writing · first token ${stats.ttft_s == null ? "unknown" : Number(stats.ttft_s).toFixed(2) + " s"}`;
    }
  });
})();
