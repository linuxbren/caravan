"""Split point safety (Day 18): pick layer counts per Mini so every Mini keeps
the memory headroom margin, for any number of Minis.

Model (calibrated on Dark Champion 21B 8-bit, 32 layers, ~0.71 GB/layer, two
24 GB Minis, Nov 7 2026):
    free_i = capacity_i - layers_i * per_layer_gb - STAGE_OVERHEAD_GB
capacity_i is web_picker._node_capacity_gb (total - OS baseline 4 GB, or the
live reclaimable figure). 24/8 put 17.0 GB on EXO2 → 20 - 17.0 - 1.3 = 1.7 GB,
under the 1.75 GB margin; the packer measured 1.51-1.71 GB and every chat got
507. 16/16 → 7.3 GB free each (measured ~7.6 GB inactive on EXO2), which worked.

Stages are given in pipeline order: packer/front stages first, lead last (the
same order as packer_layers / layer_plan). Pure functions; no I/O.
"""
from __future__ import annotations

import os
from typing import Optional

MARGIN_GB = float(os.environ.get("CARAVAN_MEMORY_SAFETY_GB", "1.75"))
STAGE_OVERHEAD_GB = float(os.environ.get("CARAVAN_SPLIT_STAGE_OVERHEAD_GB", "1.3"))


def per_layer_gb(weights_gb: float, n_layers: int) -> float:
    return float(weights_gb) / max(1, int(n_layers))


def stage_free(counts, caps, per_layer: float, overhead: float = STAGE_OVERHEAD_GB) -> list:
    return [round(c - k * per_layer - overhead, 2) for k, c in zip(counts, caps)]


def balanced_counts(n_layers: int, caps, per_layer: float,
                    overhead: float = STAGE_OVERHEAD_GB) -> list:
    """Every stage gets >= 1 layer; each further layer goes to the stage that
    would have the most free memory after taking it (max-min free). Equal
    Minis → even split (32 on 2 → 16/16). Earlier stages win ties."""
    n, k = int(n_layers), len(caps)
    if k < 1 or n < k:
        raise ValueError("need at least one layer per Mini")
    counts = [1] * k
    for _ in range(n - k):
        free = stage_free(counts, caps, per_layer, overhead)
        i = max(range(k), key=lambda j: (free[j] - per_layer, -j))
        counts[i] += 1
    return counts


def counts_from_packer_layers(packer_layers: int, n_layers: int) -> list:
    """2-stage runtime: packer takes the front `packer_layers`, lead the rest."""
    return [int(packer_layers), int(n_layers) - int(packer_layers)]


def check(counts, caps, per_layer: float, labels=None, margin: float = MARGIN_GB,
          overhead: float = STAGE_OVERHEAD_GB) -> dict:
    """{ok, free, low: [{label, layers, free_gb}], balanced, balanced_free, better}."""
    labels = list(labels or [f"Mini {i + 1}" for i in range(len(caps))])
    n = sum(counts)
    free = stage_free(counts, caps, per_layer, overhead)
    low = [{"label": labels[i], "layers": counts[i], "free_gb": free[i]}
           for i in range(len(counts)) if free[i] < margin]
    bal = balanced_counts(n, caps, per_layer, overhead)
    bal_free = stage_free(bal, caps, per_layer, overhead)
    return {"ok": not low, "counts": list(counts), "free": free, "low": low,
            "balanced": bal, "balanced_free": bal_free,
            "balanced_ok": min(bal_free) >= margin, "margin_gb": margin,
            "better": bool(low) and bal != list(counts) and min(bal_free) > min(free)}


def message(chk: dict, labels, extra_files: Optional[dict] = None) -> str:
    """Plain-language note for the picker/load. extra_files: {label: [files]}."""
    if chk["ok"]:
        return ""
    lows = ", ".join(f"{x['label']} would have about {max(0.0, x['free_gb']):.1f} GB free"
                     for x in chk["low"])
    cur = "/".join(str(c) for c in chk["counts"])
    bal = "/".join(str(c) for c in chk["balanced"])
    msg = (f"The saved split ({cur} layers) is too tight: {lows}, under the "
           f"{chk['margin_gb']:.2f} GB safety margin, so chats would fail.")
    if chk["better"]:
        msg += f" A balanced split ({bal}) leaves " + ", ".join(
            f"{labels[i]} about {f:.1f} GB" for i, f in enumerate(chk["balanced_free"])) + " free."
        need = {k: v for k, v in (extra_files or {}).items() if v}
        if need:
            msg += " It needs these extra files first (Caravan won't download them by itself): " + "; ".join(
                f"{k}: {', '.join(v)}" for k, v in need.items()) + "."
        elif extra_files is not None:
            msg += " Every Mini already has the files for it, so Caravan will load it that way."
    else:
        msg += " No split across these Minis fits with the margin; try a smaller version of the model."
    return msg


def pipeline_order(stage_nodes) -> list:
    """Packer/front stages first (in the given order), lead last."""
    nodes = [n for n in stage_nodes or [] if isinstance(n, dict)]
    return [n for n in nodes if n.get("role") != "lead"] + [n for n in nodes if n.get("role") == "lead"]


def caps_for(nodes, cap_fn=None) -> list:
    if cap_fn is None:
        from web_picker import _node_capacity_gb as cap_fn
    return [float(cap_fn(n) or 0) for n in nodes]


def balanced_packer_layers(n_layers, weights_gb, stage_nodes, cap_fn=None) -> Optional[int]:
    """2-stage runtime default for a split download: the packer's share of a
    balanced split. None when RAM is unknown (caller keeps its old default)."""
    nodes = pipeline_order(stage_nodes)
    if len(nodes) < 2 or not n_layers or not weights_gb:
        return None
    caps = caps_for(nodes, cap_fn)
    if not all(c > 0 for c in caps):
        return None
    counts = balanced_counts(int(n_layers), caps, per_layer_gb(weights_gb, n_layers))
    return counts[0] if len(counts) == 2 else counts[0]


def preview(n_layers, weights_gb, nodes, counts=None, *, config=None, index=None,
            inventories=None, sizes=None):
    """Read-only Balance API contract, shared by web and future TUI.

    Nodes are in forward order (lead last); inventories are keyed by node ID.
    Unknown files/RAM never become a green reload button. Estimates are NOT a
    speed prediction or a guarantee for a long context's growing KV cache.
    """
    import math
    from mlx_split import plan_ranges
    nodes = list(nodes)
    if len(nodes) < 2 or len({n.get("id") for n in nodes}) != len(nodes) or any(not n.get("id") for n in nodes):
        raise ValueError("need at least two uniquely identified Minis")
    if sum(n.get("role") == "lead" for n in nodes) != 1 or nodes[-1].get("role") != "lead":
        raise ValueError("pipeline order must be packers first, lead last")
    try:
        weights = float(weights_gb)
    except (ValueError, TypeError):
        raise ValueError("model weight size is unknown") from None
    if not math.isfinite(weights) or weights <= 0:
        raise ValueError("model weight size is unknown")
    caps = []
    for node in nodes:
        ram = node.get("ram") or {}
        available = ram.get("available_gb", ram.get("free_gb"))
        if node.get("offline") or node.get("error") or available is None:
            raise ValueError(f"live free memory is unknown for {node['id']}")
        # Reclaim only the running worker footprint, never assume total-OS is free.
        cap = float(available) + max(0.0, float(node.get("active_gb") or node.get("weights_gb") or 0))
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError(f"live free memory is unknown for {node['id']}")
        caps.append(cap)
    # A second worker on the same Mini does not create another stick of RAM.
    # Explicit physical_id handles SSH aliases; matching host/SSH also dedupes.
    groups = {}
    for i, node in enumerate(nodes):
        host = node.get("physical_id") or node.get("ssh") or node.get("host") or node["id"]
        if host in ("local", "localhost", "127.0.0.1"):
            host = "local"
        groups.setdefault(host, []).append(i)
    for members in groups.values():
        if len(members) > 1:
            budget = min(caps[i] for i in members) / len(members)
            for i in members:
                caps[i] = budget
    per_layer = per_layer_gb(weights, n_layers)
    auto = balanced_counts(n_layers, caps, per_layer)
    chosen = auto if counts is None else list(counts)
    ranges = plan_ranges(n_layers, chosen)
    if len(chosen) != len(nodes):
        raise ValueError("one layer count is required for each Mini")
    raw_free = [cap - k * per_layer - STAGE_OVERHEAD_GB for cap, k in zip(caps, chosen)]
    free = [round(value, 2) for value in raw_free]
    files = None
    if config is not None and index is not None:
        from mlx_split_fetch import plan_stage_files
        files = plan_stage_files(config, index, chosen)["stages"]
    stages = []
    for i, node in enumerate(nodes):
        inv = (inventories or {}).get(node["id"]) or {}
        have = inv.get("shards_present")
        missing = None if files is None or have is None else sorted(files[i] - set(have))
        # Inventory distinguishes present-but-incomplete files; never count those ready.
        if missing is not None:
            missing = sorted(set(missing) | (set(files[i]) & set(inv.get("incomplete") or [])))
        stages.append({"id": node["id"], "label": node.get("label") or node["id"],
                       "role": node.get("role"), "range": list(ranges[i]), "layers": chosen[i],
                       "capacity_gb": round(caps[i], 2),
                       "estimated_use_gb": round(chosen[i] * per_layer + STAGE_OVERHEAD_GB, 2),
                       "headroom_gb": free[i], "safe": raw_free[i] >= MARGIN_GB,
                       "downloads": missing,
                       "metadata_ready": all(inv.get(k) for k in ("has_config", "has_index", "has_tokenizer")),
                       "download_bytes": (sum(sizes[f] for f in missing)
                                          if missing is not None and all(f in (sizes or {}) for f in missing) else None)})
    safe = min(raw_free) >= MARGIN_GB
    ready = safe and all(s["downloads"] == [] and s["metadata_ready"] for s in stages)
    return {"mode": "auto" if counts is None else "manual", "counts": chosen,
            "auto_counts": auto, "margin_gb": MARGIN_GB, "safe": safe,
            "ready": ready, "stages": stages, "reload_required": True,
            "speed": None, "note": "Memory is estimated; real speed appears after reload and a reply. No downloads have started."}
