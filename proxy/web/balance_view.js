/* Pure presentation helpers; no network or model mutations. Shared with tests. */
(function (root) {
  const finite = n => typeof n === 'number' && Number.isFinite(n);
  function valid(plan) {
    return !!(plan && Array.isArray(plan.counts) && plan.counts.length &&
      Array.isArray(plan.stages) && plan.stages.length === plan.counts.length &&
      Array.isArray(plan.node_ids) && plan.node_ids.length === plan.counts.length &&
      new Set(plan.node_ids).size === plan.node_ids.length &&
      plan.counts.every(n => finite(n) && n > 0 && (plan.format === 'gguf' || Number.isInteger(n))));
  }
  function card(stage) {
    const known = finite(stage.capacity_gb) && stage.capacity_gb > 0 &&
      finite(stage.estimated_use_gb) && stage.estimated_use_gb >= 0 && finite(stage.headroom_gb);
    return {known, percent: known ? Math.max(0, Math.min(100, 100 * stage.estimated_use_gb / stage.capacity_gb)) : 0,
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
    if (adjusting) return `Preview: ${plan.stages.map((s,i) => `${s.label || s.id} ${plan.counts[i]} ${plan.format === 'gguf' ? 'share' : 'layers'}`).join(' · ')} · at least ${free} GB left per Mini.`;
    return `Preview: work shared automatically · at least ${free} GB left per Mini.`;
  }
  const api = {valid, card, moveBoundary, summary};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CaravanBalanceView = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
