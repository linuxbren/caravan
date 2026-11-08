"""Download placement: one Mini, K-way split, or copy-to-all.

Saved next to the model as caravan-placement.json so Settings/load respect it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

PLACEMENT_FILE = "caravan-placement.json"


def _caps(nodes: list) -> list:
    out = []
    for i, n in enumerate(nodes or []):
        if not isinstance(n, dict) or n.get("offline") or n.get("error"):
            continue
        ram = n.get("ram") or {}
        avail = float(ram.get("available_gb") or ram.get("free_gb") or 0)
        active = float(n.get("active_gb") or n.get("weights_gb") or 0)
        total = float(ram.get("total_gb") or 0)
        cap = avail + active
        if total:
            cap = min(cap, max(0.0, total - 4.0)) if cap else max(0.0, total - 4.0)
        disk = float((n.get("disk") or {}).get("free_gb") or 0)
        out.append({
            "node": n,
            "id": n.get("id") or n.get("label") or f"n{i}",
            "label": n.get("label") or n.get("id") or f"n{i}",
            "role": n.get("role") or ("lead" if i == 0 else "packer"),
            "cap": cap,
            "disk": disk,
        })
    out.sort(key=lambda x: (-x["cap"], -x["disk"], x["label"]))
    return out


def read_placement(model_dir: str | Path) -> Optional[dict]:
    p = Path(model_dir).expanduser() / PLACEMENT_FILE
    if not p.is_file():
        return None
    try:
        blob = json.loads(p.read_text())
        return blob if isinstance(blob, dict) else None
    except (OSError, ValueError):
        return None


def write_placement(model_dir: str | Path, placement: dict) -> Path:
    d = Path(model_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    p = d / PLACEMENT_FILE
    blob = {
        "mode": placement.get("mode"),
        "k": placement.get("k"),
        "node_ids": list(placement.get("node_ids") or []),
        "node_labels": list(placement.get("node_labels") or []),
        "repo_id": placement.get("repo_id"),
        "full_copy": bool(placement.get("full_copy")),
    }
    # Day 18: the split point the shards were fetched for, so catalog + load agree.
    for k in ("packer_layers", "n_stages", "layer_plan"):
        if placement.get(k) is not None:
            blob[k] = placement[k]
    p.write_text(json.dumps(blob, indent=2) + "\n")
    return p


def placement_options(
    *,
    fit: dict,
    nodes: list,
    max_split_stages: int = 2,
    weights_gb: Optional[float] = None,
) -> dict:
    """Build UI choices. Default = smallest placement that fits."""
    ranked = _caps(nodes)
    fits_on = list(fit.get("fits_on") or [])
    color = fit.get("color") or "gray"
    options = []

    # --- one Mini (each online node as a target) ---
    best_one = ranked[0] if ranked else None
    one_fits = 1 in fits_on
    for r in ranked:
        enabled = one_fits and r["disk"] >= (weights_gb or 0) * 0.9
        reason = ""
        if not one_fits:
            reason = fit.get("reason") or "does not fit on 1 Mini"
        elif not enabled:
            reason = f"not enough disk on {r['label']} (~{r['disk']:.0f} GB free)"
        options.append({
            "id": f"one:{r['id']}",
            "mode": "one",
            "k": 1,
            "node_ids": [r["id"]],
            "node_labels": [r["label"]],
            "label": f"1 Mini · {r['label']}",
            "enabled": bool(enabled),
            "reason": reason,
            "full_copy": True,
            "default_candidate": bool(best_one and r["id"] == best_one["id"] and enabled),
        })

    # --- K-way split (only runtime-supported K that fit) ---
    n_online = len(ranked)
    for k in range(2, n_online + 1):
        runtime_ok = k <= int(max_split_stages)
        fit_ok = k in fits_on
        enabled = runtime_ok and fit_ok
        reason = ""
        if not runtime_ok:
            reason = f"{k}-Mini split coming later; runtime loads on {max_split_stages} today"
        elif not fit_ok:
            reason = f"does not fit across {k} Minis"
        chosen = ranked[:k]
        options.append({
            "id": f"split:{k}",
            "mode": "split",
            "k": k,
            "node_ids": [c["id"] for c in chosen],
            "node_labels": [c["label"] for c in chosen],
            "label": f"Split across {k} Minis ({', '.join(c['label'] for c in chosen)})",
            "enabled": bool(enabled),
            "reason": reason,
            "full_copy": False,
            "default_candidate": bool(enabled and not one_fits and k == min(
                [x for x in fits_on if 2 <= x <= max_split_stages] or [999]
            )),
        })

    # --- copy to all ---
    all_ids = [r["id"] for r in ranked]
    all_labels = [r["label"] for r in ranked]
    share = float(weights_gb or 0)
    disk_ok = all(r["disk"] >= share * 0.9 for r in ranked) if ranked and share else bool(ranked)
    # Copy-all needs the model to fit on each Mini individually (full copy).
    all_enabled = one_fits and disk_ok and len(ranked) >= 1
    all_reason = ""
    if not ranked:
        all_reason = "no online nodes"
    elif not one_fits:
        all_reason = "model does not fit as a full copy on one Mini"
    elif not disk_ok:
        all_reason = "not enough disk on every Mini for a full copy"
    options.append({
        "id": "all",
        "mode": "all",
        "k": len(ranked),
        "node_ids": all_ids,
        "node_labels": all_labels,
        "label": f"Copy to all ({', '.join(all_labels) or 'none'})",
        "enabled": bool(all_enabled),
        "reason": all_reason,
        "full_copy": True,
        "default_candidate": False,
    })

    default_id = None
    for o in options:
        if o.get("default_candidate") and o.get("enabled"):
            default_id = o["id"]
            break
    if default_id is None:
        for o in options:
            if o.get("enabled"):
                default_id = o["id"]
                break

    return {
        "options": options,
        "default_id": default_id,
        "fits_on": fits_on,
        "color": color,
        "max_split_stages": int(max_split_stages),
        "online": [{"id": r["id"], "label": r["label"], "cap_gb": round(r["cap"], 1),
                    "disk_gb": round(r["disk"], 1)} for r in ranked],
    }


def resolve_option(options_blob: dict, placement_id: Optional[str] = None,
                   body: Optional[dict] = None) -> Optional[dict]:
    """Pick an option by id or by {mode, node_ids, k} from the request body."""
    opts = (options_blob or {}).get("options") or []
    if body and isinstance(body, dict):
        if body.get("placement_id"):
            placement_id = body["placement_id"]
        elif body.get("placement"):
            p = body["placement"]
            if isinstance(p, dict):
                if p.get("id"):
                    placement_id = p["id"]
                else:
                    mode = p.get("mode")
                    k = p.get("k")
                    nids = list(p.get("node_ids") or [])
                    for o in opts:
                        if o.get("mode") != mode:
                            continue
                        if mode == "one" and nids and o.get("node_ids") == nids:
                            return o
                        if mode == "split" and int(o.get("k") or 0) == int(k or 0):
                            return o
                        if mode == "all":
                            return o
    if not placement_id:
        placement_id = (options_blob or {}).get("default_id")
    for o in opts:
        if o.get("id") == placement_id:
            return o
    return None
