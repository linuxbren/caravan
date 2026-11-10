/* Pure presentation helpers; no network or model mutations. Shared with tests. */
(function (root) {
  const finite = n => typeof n === 'number' && Number.isFinite(n);
  function valid(plan) {
    return !!(plan && typeof plan.model_id === 'string' && plan.model_id && Array.isArray(plan.counts) && plan.counts.length &&
      Array.isArray(plan.stages) && plan.stages.length === plan.counts.length &&
      Array.isArray(plan.node_ids) && plan.node_ids.length === plan.counts.length &&
      new Set(plan.node_ids).size === plan.node_ids.length &&
      plan.counts.every(n => finite(n) && n > 0 && (plan.format === 'gguf' || Number.isInteger(n))));
  }
  function card(stage) {
    // Existing GGUF previews give use + headroom, without a separate capacity.
    const capacity = stage.capacity_gb === undefined && finite(stage.estimated_use_gb) && finite(stage.headroom_gb)
      ? stage.estimated_use_gb + stage.headroom_gb : stage.capacity_gb;
    const known = finite(capacity) && capacity > 0 &&
      finite(stage.estimated_use_gb) && stage.estimated_use_gb >= 0 && finite(stage.headroom_gb);
    return {known, capacity, percent: known ? Math.max(0, Math.min(100, 100 * stage.estimated_use_gb / capacity)) : 0,
      safe: known && stage.safe === true, label: stage.label || stage.id || 'Mini'};
  }
  function moveBoundary(counts, index, value) {
    if (!Array.isArray(counts) || !counts.every(n => Number.isInteger(n) && n > 0) ||
        !Number.isInteger(index) || index < 0 || index >= counts.length - 1 || !finite(Number(value))) throw Error('Invalid layer boundary');
    const out = [...counts], start = counts.slice(0, index).reduce((a,b) => a+b, 0);
    const end = start + counts[index] + counts[index+1];
    const boundary = Math.max(start+1, Math.min(end-1, Math.round(Number(value))));
    out[index] = boundary-start; out[index+1] = end-boundary;
    return out;
  }
  function summary(plan, adjusting) {
    if (!valid(plan)) return 'Preview unavailable; refresh before applying.';
    const safe = plan.stages.every(s => card(s).safe);
    if (!safe) return 'Preview: not enough known free memory on every Mini. Apply is blocked.';
    const free = Math.min(...plan.stages.map(s => s.headroom_gb)).toFixed(1);
    if (adjusting) {
      const split = plan.counts.length <= 2 ? `${plan.counts.join(' / ')} ${plan.format === 'gguf' ? 'shares' : 'layers'}` : `${plan.counts.length} Minis`;
      return `Preview: ${split} · ≥${free} GB free per Mini.`;
    }
    return `Preview: Auto · ≥${free} GB free per Mini.`;
  }
  function matches(plan, worker) {
    const b=plan?.format==='gguf' ? (worker?.gguf ? {counts:worker.gguf.shares,node_ids:worker.gguf.nodes}:null) : worker?.balance;
    return !!(valid(plan) && worker && worker.model_id===plan.model_id && b &&
      JSON.stringify(b.counts)===JSON.stringify(plan.counts) && JSON.stringify(b.node_ids)===JSON.stringify(plan.node_ids));
  }
  function changed(plan, snapshot) {
    return !!(valid(plan) && snapshot?.worker?.status==='ready' && snapshot.lead_healthy && !matches(plan,snapshot.worker));
  }
  function reloadSettings(snapshot) {
    const a=snapshot?.active || {}, out={...(snapshot?.worker?.settings || {})};
    for (const key of ['self_tune','guess_ahead','shared_start','keepalive']) if (typeof a[key]==='boolean') out[key]=a[key]?'on':'off';
    if (a.prompt_lookup && typeof a.prompt_lookup.enabled==='boolean') out.prompt_lookup=a.prompt_lookup.enabled?(a.prompt_lookup.adaptive?'auto':'on'):'off';
    if ([4,8,16].includes(a.kv_bits)) out.kv_bits=String(a.kv_bits);
    if ([1,2].includes(a.pipeline_chats)) out.pipeline_chats=String(a.pipeline_chats);
    if (['on','off'].includes(a.fuse_kernels)) out.fuse_kernels=a.fuse_kernels;
    return out;
  }
  const api = {valid, card, moveBoundary, summary, matches, changed, reloadSettings};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CaravanBalanceView = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
