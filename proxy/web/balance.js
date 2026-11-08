/* Read-only preview until the explicit reload button. Same API as a future TUI. */
(() => {
  const $ = id => document.getElementById(id);
  let plan = null, counts = null, revision = 0, timer, measuredModel = null;
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
  async function refresh() {
    const version = ++revision, mid = model();
    apply.disabled = true; fetchButton.disabled = true;
    preview.replaceChildren(text('p', 'Checking each Mini’s files and memory… (first GGUF source verification may take a while)'));
    try {
      const response = await fetch("/api/balance", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(request())});
      const next = await response.json();
      if (version !== revision || mid !== model()) return;
      if (!response.ok) throw new Error(next.error || "Preview unavailable");
      plan = next;
      preview.replaceChildren(text("p", `${next.mode === "auto" ? "Auto" : "Manual"}: ${next.counts.join(" / ")} layers · keep ${next.margin_gb} GB free`));
      next.stages.forEach((stage, i) => {
        const gb = n => n == null ? 'unknown' : (n/1e9).toFixed(2) + ' GB';
        preview.append(text('p', `${stage.label} disk: ${gb(stage.on_disk_bytes)} logical · ${gb(stage.allocated_bytes)} allocated${stage.cache_scope ? ' · ' + stage.cache_scope + (stage.cache_path ? ' ('+stage.cache_path+')' : '') : ''}`));
        if ((stage.links || []).length) preview.append(text('small', 'Linked files left untouched: '+stage.links.join(', ')+'. Use the real model folder for selective fetching.'));
        if (stage.not_needed_for_plan === null) preview.append(text('small', 'Retained files unknown.'));
        else if ((stage.not_needed_for_plan || []).length) preview.append(text('p', `Not needed for this plan, kept on disk (${gb(stage.retained_bytes)}): ${stage.not_needed_for_plan.join(', ')}. Other splits/models may still need these; nothing is deleted.`));
        preview.append(text("p", `${stage.label}: layers ${stage.range[0]}–${stage.range[1] - 1} · use ≈${stage.estimated_use_gb} GB · free ≈${stage.headroom_gb} GB${stage.safe ? "" : " — too tight"}`));
        const downloads = stage.downloads;
        preview.append(text("small", downloads === null ? "Files unknown; reload blocked." :
          downloads.length ? `Download from source: ${downloads.join(", ")}${stage.download_bytes == null ? "" : ` (≈${(stage.download_bytes/1e9).toFixed(2)} GB)`}` : "Required shards already here."));
        if (!stage.metadata_ready) preview.append(text("p", "Config, index or tokenizer is missing; reload blocked."));
        if (next.format === 'gguf') {
          const share = document.createElement('input'); share.type='number'; share.min='0.1'; share.step='0.1'; share.value=next.counts[i];
          share.setAttribute('aria-label', 'GGUF share for '+stage.label);
          share.onchange = () => { counts=[...next.counts]; counts[i]=Number(share.value); ++revision; apply.disabled=true; fetchButton.disabled=true; refresh(); };
          preview.append(text('small', 'GGUF device share (proportion, not MLX layer count): '), share);
        } else if (i < next.stages.length - 1) {
          const input = document.createElement("input"); input.type = "range"; input.step = "1";
          input.style.width = "100%";
          const start = stage.range[0], end = next.stages[i + 1].range[1];
          input.min = start + 1; input.max = end - 1; input.value = stage.range[1];
          input.setAttribute("aria-label", `Layer boundary after ${stage.label}`);
          input.addEventListener("input", () => {
            counts = [...(counts || next.counts)];
            const currentStart = counts.slice(0, i).reduce((a, b) => a + b, 0);
            const currentEnd = currentStart + counts[i] + counts[i + 1];
            const boundary = Math.max(currentStart + 1, Math.min(currentEnd - 1, Number(input.value)));
            counts[i] = boundary - currentStart;
            counts[i + 1] = currentEnd - boundary;
            ++revision; apply.disabled = true; fetchButton.disabled = true;
            clearTimeout(timer); timer = setTimeout(refresh, 140);
          });
          preview.append(input);
        }
      });
      preview.append(text("p", next.note));
      apply.disabled = !next.ready;
      fetchButton.disabled = !!jobId || next.stages.some(s => s.downloads === null) || !next.stages.some(s => s.downloads.length || !s.metadata_ready);
    } catch (error) {
      if (version !== revision) return;
      plan = null; preview.replaceChildren(text("p", error.message));
    }
  }
  $("balanceAuto").onclick = async () => {
    counts = null; clearTimeout(timer);
    try { await models(); await refresh(); } catch (error) { preview.replaceChildren(text('p',error.message)); }
  };
  $("balanceModel").onchange = () => { counts=null; ++revision; plan=null; fetchButton.disabled=true; refresh(); };
  [$("balanceRepo"), $("balanceFile")].forEach(el => el.oninput = () => { ++revision; plan=null; apply.disabled=true; fetchButton.disabled=true; });
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
    ++revision; clearTimeout(timer); counts = null; plan = null; apply.disabled = true; fetchButton.disabled=true;
    measuredModel = null; $("balanceSpeed").textContent = "Real speed will appear after reload and a reply.";
    preview.replaceChildren(text("p", "Model changed. Press Auto / refresh."));
  });
  apply.onclick = async () => {
    if (!plan || !plan.ready) return;
    apply.disabled = true;
    measuredModel = null;
    try {
      const response = await fetch("/api/models/load", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...request(), model_id: plan.model_id, node_ids: plan.node_ids, counts: plan.counts, balance: true})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Reload failed");
      measuredModel = plan.model_id;
      $("balanceSpeed").textContent = "Reload requested. Wait for Ready, then send a reply to measure speed.";
    } catch (error) {
      preview.append(text("p", error.message));
    }
    // Never re-enable from a stale preview: get a fresh memory/file plan.
    plan = null;
  };
  window.addEventListener("caravan-reply-stats", event => {
    const {stats, model: mid} = event.detail;
    if (measuredModel && mid === measuredModel && stats.write_tok_s != null) {
      $("balanceSpeed").textContent = `Measured after reload: ${Number(stats.write_tok_s).toFixed(2)} tok/s writing · first token ${stats.ttft_s == null ? "unknown" : Number(stats.ttft_s).toFixed(2) + " s"}`;
    }
  });
})();
