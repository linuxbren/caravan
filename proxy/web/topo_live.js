/** Topology helpers: one-Mac section visibility and stale/offline presence. */
(function (root) {
  const STALE_MS = 15000;
  const OFF_REASON = "Caravan is off";

  function isOffline(node, now, freshAt) {
    if (node && node.offline) return true;
    if (freshAt && (now - freshAt) > STALE_MS) return true;
    return false;
  }

  function liveCount(nodes, now, freshAtMap) {
    let n = 0;
    for (const node of nodes || []) {
      const id = node && (node.id || node.label);
      const freshAt = freshAtMap && id != null ? freshAtMap[id] : undefined;
      if (!isOffline(node, now, freshAt)) n += 1;
    }
    return n;
  }

  function shouldShowSplitSections(nodes, now, freshAtMap) {
    return liveCount(nodes, now, freshAtMap) >= 2;
  }

  function offlineLabel(node, stale) {
    if (stale && !(node && node.offline)) return "offline";
    if (node && node.error === OFF_REASON) return "offline · Caravan is off";
    return "offline";
  }

  const api = { STALE_MS, OFF_REASON, isOffline, liveCount, shouldShowSplitSections, offlineLabel };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CaravanTopoLive = api;
})(typeof window !== "undefined" ? window : globalThis);
