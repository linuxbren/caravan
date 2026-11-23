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
  let jobId = null, latest = window.caravanWorkerSnapshot || null, reload = null, finished = false;
  const busy = st => ['stopping','starting_packer','starting_lead','loading'].includes(st);
  function quietStatus(msg) {
    const idle=$('balanceIdleStatus');
    if (idle) { idle.hidden=!msg; idle.textContent=msg || ''; }
    const box=$('balanceReload');
    if (box && !reload) { box.hidden=true; if (typeof box.removeAttribute==='function') box.removeAttribute('data-state'); else if (box.dataset) delete box.dataset.state; }
    const chat=$('balanceChatNotice');
    if (chat && !reload) { chat.hidden=true; chat.textContent=''; }
  }
  function notice(title, state, steps=[]) {
    const idle=$('balanceIdleStatus'); if (idle) { idle.hidden=true; idle.textContent=''; }
    const box=$('balanceReload'); box.hidden=false; box.dataset.state=state;
    $('balanceReloadTitle').textContent=title;
    $('balanceReloadSteps').replaceChildren(...steps.map(s=>text('li',s)));
    const chat=$('balanceChatNotice');chat.hidden=state==='ready';chat.dataset.state=state;chat.textContent=title;
  }
  function lockChat(locked) {
    window.caravanBalanceReloading=locked;
    if (locked) { $('btnSend').disabled=true; $('input').disabled=true; }
    $('balanceControlLock').disabled=locked;
    $('modelSelect').disabled=locked;
    if (locked) { $('btnLoad').disabled=true; $('btnApply').disabled=true; }
  }
  function updateApply() {
    const unsafe=!!(plan && (!plan.ready || !plan.stages.every(s=>V.card(s).safe)));
    const already=!!(plan && !unsafe && !V.changed(plan,latest));
    apply.disabled=!!reload || !plan || unsafe || already;
    if (!reload && !finished && plan && latest?.worker?.status==='ready') {
      quietStatus(already?T('web.this_split_is_already_applied'):unsafe?T('web.this_split_is_not_safe_to'):T('web.ready_to_apply_a_new_split'));
    } else if (!reload && !plan) {
      quietStatus('');
    }
  }
  function reloadSteps(w) {
    const st=(w?.status==='ready' && reload && !reload.external && w.lead_pid===reload.oldPid)?'queued':(w?.status || 'queued'), labels=reload?.target?.stages?.map(s=>s.label) || latest?.worker?.balance?.node_ids || [];
    const msgs=(w?.progress || []).map(p=>p.msg || '').join('\n');
    const stopping=st==='stopping'||st==='queued';
    return [stopping?T('web.stopping_old_model'):T('web.old_model_stopped'),...labels.map((label,i)=>{
      const last=i===labels.length-1;
      const ready=st==='ready' || (!last && st==='starting_lead') || msgs.includes(label+': '+(reload?.target?.counts?.[i] || '')+' layers ready');
      return ready?T(`web.label_loaded`, {label}):stopping?T(`web.waiting_for_label`, {label}):st==='starting_packer'&&last?T(`web.waiting_for_label`, {label}):T(`web.loading_on_label`, {label});
    }),st==='ready'?T('web.ready'):T('web.waiting_for_the_model_to_answer')];
  }
  function onStatus(snapshot) {
    latest=snapshot;const w=snapshot.worker || {};
    if (!reload && busy(w.status)) { reload={external:true,started:Date.now(),oldPid:null};finished=false; }
    if (reload) {
      lockChat(true);
      if (w.status==='error') {
        notice(T(`web.reload_failed_error`, {error: w.error || T('web.check_technical_details')}),'error');reload=null;finished=true;lockChat(false);
      } else if (w.status==='idle' && reload.external) {
        notice(T('web.model_unloaded_choose_a_model_in'),'error');reload=null;finished=true;lockChat(false);
      } else if (w.status==='ready' && snapshot.lead_healthy) {
        const newWorker=reload.external || (w.lead_pid && w.lead_pid!==reload.oldPid);
        const kv=reload.settings?.kv_bits;
        const matches=reload.external || (V.matches(reload.target,w) && (reload.target.format==='gguf' || !kv || String(snapshot.active?.kv_bits)===kv));
        if (newWorker) {
          notice(matches?(reload.external?T('web.ready_model_loaded'):T('web.ready_new_split_applied')):T('web.reload_finished_but_the_requested_split'),''+(matches?'done':'error'),matches?reloadSteps(w):[]);
          $('balanceSpeed').textContent=matches?T('web.ready_send_a_reply_to_measure'):T('web.requested_split_not_confirmed_check_the');
          reload=null;finished=true;lockChat(false);
        } else if (reload.failure || Date.now()-reload.started>180000) {
          notice(T(`web.reload_not_confirmed_failure`, {failure: reload.failure || T('web.timed_out_current_model_is_still')}),'error');reload=null;finished=true;lockChat(false);
        }
      }
      if (reload) notice(reload.failure?T(`web.reload_status_uncertain_failure_checking_the`, {failure: reload.failure}):T('web.reloading_model_this_takes_about_10'),'reloading',reloadSteps(w));
    }
    updateApply();mode();
  }
  window.addEventListener('caravan-worker-status',e=>onStatus(e.detail));
  window.addEventListener('caravan-worker-status-error',()=>{
    apply.disabled=true;
    if (reload) { lockChat(true);notice(T('web.connection_lost_reload_may_still_be'),'error'); }
    latest=null;
  });
  const request = () => ({model_id: model(), counts, repo_id: $("balanceRepo").value.trim() || undefined,
                          gguf_file: $("balanceFile").value.trim() || undefined});
  async function models() {
    const response = await fetch('/api/models'), result = await response.json();
    if (!response.ok) throw new Error(result.error || T('web.cannot_list_installed_models'));
    const chosen = model(), select = $("balanceModel");
    select.replaceChildren();
    (result.models || []).forEach(m => {
      const option = text('option', m.name + (m.usable === false ? T('web.files_fit_not_ready') : ''));
      option.value = m.id; option.selected = m.id === chosen; select.append(option);
    });
  }
  function mode() {
    $("balanceMode").textContent = adjusting ? T("web.adjusting") : T("web.auto_recommended");
    $("balanceModeHelp").textContent = adjusting ? T("web.your_split_preview_only") : T("web.auto_caravan_shares_the_work_for");
    $("balanceAdjust").setAttribute("aria-expanded", String(adjusting));
    $("balanceAdjust").disabled = !!reload || adjusting || !plan;
    $("balanceAuto").disabled = !!reload || !adjusting;
    controls.hidden = !adjusting;
  }
  function invalidate(message) {
    ++revision; plan = null; apply.disabled = true; fetchButton.disabled = true;
    memory.setAttribute("aria-busy", "true");
    if (message) preview.textContent = message;
  }
  function draw(next) {
    memory.replaceChildren(); controls.replaceChildren(); technical.replaceChildren();
    $("balanceModelName").textContent = T(`web.text_content_stages_count_v_memory`, {text_content: $("balanceModel").selectedOptions[0]?.textContent || model(), stages_count: next.stages.length, v: next.stages.length === 1 ? T('web.mini') : T('web.minis')});
    next.stages.forEach((stage, i) => {
      const c = V.card(stage), gb = n => n == null ? 'unknown' : T(`web.v_gb`, {v: ((n/1e9).toFixed(2))});
      const card = text('article', ''); card.className = 'balance-card' + (c.safe ? '' : ' unsafe');
      const head = text('div', ''); head.className='balance-card-head'; head.append(text('strong', c.label), text('span', T('web.estimated_memory')));
      const bar = text('div', ''); bar.className='balance-bar'; bar.setAttribute('role','img');
      bar.setAttribute('aria-label', c.known ? T(`web.label_estimated_estimated_use_gb_gb`, {label: c.label, estimated_use_gb: stage.estimated_use_gb, capacity: c.capacity}) : T(`web.label_memory_unknown`, {label: c.label}));
      const fill=text('i',''); fill.style.width=c.percent+'%'; bar.append(fill);
      const values=text('div',''); values.className='balance-card-values';
      values.append(text('span',c.known ? T(`web.estimated_use_gb_gb_for_model`, {estimated_use_gb: stage.estimated_use_gb.toFixed(2)}) : T('web.model_memory_unknown')), text('span',c.known ? T(`web.headroom_gb_gb_left`, {headroom_gb: stage.headroom_gb.toFixed(2)}) : T('web.free_memory_unknown')));
      card.append(head,bar,values,text('small',c.known ? T(`web.usable_model_budget_capacity_gb_room`, {capacity: c.capacity.toFixed(2)}) : T('web.refresh_when_this_mini_is_reachable')));
      if (!c.safe) card.append(text('small',T('web.not_enough_known_free_memory_apply')));
      memory.append(card);
      technical.append(text('p', T(`web.label_v_v2_minimum_margin_margin`, {label: stage.label, v: next.format === 'gguf' ? T(`web.device_share_v`, {v: next.counts[i]}) : T(`web.layers_v_v2`, {v: stage.range[0], v2: stage.range[1]-1}), v2: stage.safe ? T('web.memory_fits') : T('web.too_tight'), margin_gb: next.margin_gb})));
      technical.append(text('p', T(`web.label_disk_gb_logical_gb2_allocated`, {label: stage.label, gb: gb(stage.on_disk_bytes), gb2: gb(stage.allocated_bytes), v: stage.cache_scope ? ' · ' + stage.cache_scope + (stage.cache_path ? ' ('+stage.cache_path+')' : '') : ''})));
      if ((stage.links || []).length) technical.append(text('small',T(`web.linked_files_left_untouched_links_use`, {links: stage.links.join(', ')})));
      if (stage.not_needed_for_plan === null) technical.append(text('small',T('web.retained_files_unknown')));
      else if ((stage.not_needed_for_plan || []).length) technical.append(text('p', T(`web.not_needed_for_this_plan_kept`, {gb: gb(stage.retained_bytes), not_needed_for_plan: stage.not_needed_for_plan.join(', ')})));
      const downloads = stage.downloads;
      technical.append(text('small', downloads === null ? T('web.files_unknown_reload_blocked') : downloads.length ? T(`web.download_from_source_downloads_v`, {downloads: downloads.join(', '), v: stage.download_bytes == null ? '' : T(`web.v_gb_2`, {v: (stage.download_bytes/1e9).toFixed(2)})}) : T('web.required_shards_already_here')));
      if (!stage.metadata_ready) technical.append(text('p',T('web.config_index_or_tokenizer_is_missing')));
      if (!adjusting) return;
      const row=text('div',''); row.className='balance-boundary';
      if (next.format === 'gguf') {
        const share=document.createElement('input'); share.type='number'; share.min='0.1'; share.step='0.1'; share.value=next.counts[i];
        share.id='balanceShare'+i; share.setAttribute('aria-label',T(`web.gguf_share_for_label`, {label: stage.label}));
        const label=text('label',T(`web.label_device_share_proportion_not_layers`, {label: (stage.label)})); label.htmlFor=share.id;
        share.oninput=() => {
          counts=[...(counts || next.counts)]; counts[i]=Number(share.value);
          invalidate(T('web.preview_checking_your_new_memory_split')); clearTimeout(timer);
          if (!Number.isFinite(counts[i]) || counts[i]<=0) { preview.textContent=T('web.enter_a_positive_device_share_apply'); return; }
          timer=setTimeout(refresh,200);
        };
        row.append(label,share); controls.append(row);
      } else if (i < next.stages.length-1) {
        const input=document.createElement('input'); input.type='range'; input.step='1'; input.id='balanceBoundary'+i;
        input.min=stage.range[0]+1; input.max=next.stages[i+1].range[1]-1; input.value=stage.range[1];
        input.setAttribute('aria-label', T(`web.layer_boundary_after_label`, {label: stage.label}));
        const label=text('label', T(`web.label_label2_v_v2_layers`, {label: stage.label, label2: next.stages[i+1].label, v: next.counts[i], v2: next.counts[i+1]})); label.htmlFor=input.id;
        input.oninput=() => {
          counts=V.moveBoundary(counts || next.counts,i,input.value);
          label.textContent=T(`web.label_label2_v_v2_layers`, {label: stage.label, label2: next.stages[i+1].label, v: counts[i], v2: counts[i+1]});
          invalidate(T(`web.preview_v_checking_memory`, {v: counts.length <= 2 ? T(`web.counts_layers`, {counts: (counts.join(' / '))}) : T(`web.counts_count_minis`, {counts_count: (counts.length)})}));
          clearTimeout(timer); timer=setTimeout(refresh,200);
        };
        row.append(label,input); controls.append(row);
      }
    });
    technical.append(text('p',next.note));
    preview.textContent=V.summary(next,adjusting) + (next.ready ? '' : T('web.check_technical_details_before_applying'));
    updateApply();
    fetchButton.disabled=!!jobId || next.stages.some(s=>s.downloads===null) || !next.stages.some(s=>s.downloads.length || !s.metadata_ready);
    mode();
  }
  async function refresh() {
    if (reload) return;
    invalidate(T('web.checking_each_minis_files_and_memory'));
    const version=revision, mid=model();
    try {
      const response=await fetch('/api/balance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request())});
      const next=await response.json();
      if (version!==revision || mid!==model()) return;
      if (!response.ok) throw new Error(next.error || T('web.preview_unavailable'));
      if (!V.valid(next)) throw new Error(T('web.invalid_preview_apply_is_blocked'));
      plan=next; memory.setAttribute('aria-busy','false'); draw(next);
    } catch(error) {
      if (version!==revision || mid!==model()) return;
      plan=null; memory.replaceChildren(); controls.replaceChildren(); technical.replaceChildren();
      memory.setAttribute('aria-busy','false'); preview.textContent=error.message; mode();
    }
  }
  async function reset(reloadModels=false) {
    if (reload) return;
    finished=false;
    counts=null; adjusting=false; clearTimeout(timer); invalidate(T('web.checking_each_minis_files_and_memory'));
    controls.replaceChildren(); mode(); const version=revision;
    try { if (reloadModels) await models(); if (version===revision) await refresh(); }
    catch(error) { if (version===revision) { preview.textContent=error.message; mode(); } }
  }
  $('balanceAdjust').onclick=() => { if (!plan || reload) return; adjusting=true; counts=[...plan.counts]; draw(plan); };
  $('balanceAuto').onclick=() => reset();
  $('balanceRefresh').onclick=() => { clearTimeout(timer); refresh(); };
  $('balanceModel').onchange=() => reset();
  [$('balanceRepo'),$('balanceFile')].forEach(el=>el.oninput=()=>{
    clearTimeout(timer); invalidate(T('web.source_changed_refresh_preview_before_applying'));
    memory.replaceChildren(); controls.replaceChildren(); mode();
  });
  $('btnOpenTopo').addEventListener('click',()=>{
    if ($('topoDrawer').classList.contains('open')) reset(true);
  });
  fetchButton.onclick = async () => {
    if (!plan || jobId || reload) return;
    counts = [...plan.counts]; // Freeze the plan being fetched; do not chase changing free RAM.
    const submitted = {...request(), counts, node_ids: plan.node_ids};
    fetchButton.disabled=true; apply.disabled=true;
    try {
      const response = await fetch('/api/files/fetch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(submitted)});
      const result=await response.json(); if (!response.ok) throw new Error(result.error || T('web.fetch_failed'));
      jobId=result.job.id; $("balanceStop").disabled=false;
      const poll = async () => {
        try {
          const r=await fetch('/api/picker/jobs/'+jobId), j=await r.json();
          if (!r.ok) throw new Error(j.error || T('web.cannot_read_fetch_status'));
          const nodes=Object.entries(j.progress||{}).filter(([id]) => id!=='lead' && id!=='packer');
          $("balanceJob").textContent = `${j.status}: `+nodes.map(([id,p])=>`${p.label||id}: ${p.stage||p.msg||'waiting'}`).join(' · ')+(j.error ? ' — '+j.error : '');
          if (['done','error','cancelled'].includes(j.status)) { jobId=null; $("balanceStop").disabled=true; await refresh(); }
          else setTimeout(poll,1500);
        } catch(error) { $("balanceJob").textContent=T(`web.message_fetch_may_still_be_running`, {message: (error.message)}); }
      }; poll();
    } catch(error) { preview.append(text('p',error.message)); await refresh(); }
  };
  $("balanceStop").onclick = async () => {
    if (!jobId) return;
    $("balanceStop").disabled=true; $("balanceJob").textContent=T('web.stopping_this_fetch');
    try { const r=await fetch('/api/picker/download/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId})});
      if (!r.ok) throw new Error(T('web.could_not_stop_fetch_inspect_downloads'));
    } catch(error) { $("balanceJob").textContent=error.message; }
  };
  $("modelSelect").addEventListener("change", () => {
    $("balanceModel").value = $("modelSelect").value;
    measuredModel = null; $("balanceSpeed").textContent = T("web.real_speed_will_appear_after_reload");
    reset(true);
  });
  apply.onclick = async () => {
    if (!plan || !plan.ready || apply.disabled || reload || !V.changed(plan,latest)) return;
    clearTimeout(timer);
    const submittedPlan=plan, settings=V.reloadSettings(latest);
    reload={target:submittedPlan,oldPid:latest.worker.lead_pid,started:Date.now(),settings};
    finished=false;++revision;plan=null;apply.disabled=true;measuredModel=null;
    lockChat(true);mode();notice(T('web.reloading_model_this_takes_about_10'),'reloading',reloadSteps({status:'queued'}));
    try {
      const response=await fetch('/api/models/load',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...request(),model_id:submittedPlan.model_id,node_ids:submittedPlan.node_ids,counts:submittedPlan.counts,balance:true,settings})});
      const result=await response.json();
      if (!response.ok) throw Error(result.error || T('web.reload_request_failed'));
      measuredModel=submittedPlan.model_id;
      plan=submittedPlan; // Keep display for exact no-change comparison after completion.
      $('balanceSpeed').textContent=T('web.reloading_measured_speed_appears_after_ready');
    } catch(error) {
      if (reload) reload.failure=error.message;
      notice(T(`web.reload_request_failed_message_checking_model`, {message: error.message}),'error');
    }
    updateApply();mode();
  };
  window.addEventListener("caravan-reply-stats", event => {
    const {stats, model: mid} = event.detail;
    if (measuredModel && mid === measuredModel && stats.write_tok_s != null) {
      $("balanceSpeed").textContent = T(`web.measured_after_reload_write_tok_s`, {write_tok_s: Number(stats.write_tok_s).toFixed(2), v: stats.ttft_s == null ? T("web.unknown") : T(`web.ttft_s_s`, {ttft_s: (Number(stats.ttft_s).toFixed(2))})});
    }
  });
})();
