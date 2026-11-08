"""Models the Caravan web UI can load.

Settings dropdown is built from *on-disk* MLX trees across configured Minis
(see model_inventory.py + web_server._api_models). The static CATALOG below is
optional metadata only (pretty name, default packer_layers) — it must never
make a phantom appear in the list.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import model_inventory as inv

# Thunderbolt address of EXO2 as seen from EXO1 (Packer 1 listen target).
DEFAULT_PACKER_PEER = os.environ.get("CARAVAN_WEB_PACKER_PEER", "169.254.103.191:5560")
DEFAULT_PACKER_SSH = os.environ.get("CARAVAN_WEB_PACKER_SSH", "brenden@169.254.103.191")

# Optional metadata for known lab models (NOT a source of list entries).
CATALOG = [
    {
        "id": "qwen3-30b-a3b-4bit",
        "name": "Qwen3 30B-A3B 4-bit",
        "hf": "mlx-community/Qwen3-30B-A3B-4bit",
        "packer_layers": 24,
        "notes": "Day 12 scoreboard workhorse",
    },
    {
        "id": "gemma-4-26b-a4b-4bit",
        "name": "Gemma 4 26B-A4B 4-bit",
        "hf": "mlx-community/gemma-4-26b-a4b-it-4bit",
        "packer_layers": 15,
        "notes": "Day 13 shared-start fix",
    },
    {
        "id": "gpt-oss-20b-mxfp4",
        "name": "GPT-OSS 20B MXFP4",
        "hf": "mlx-community/gpt-oss-20b-MXFP4-Q8",
        "packer_layers": 12,
        "notes": "No draft pair yet",
    },
]

_CATALOG_BY_HF = {e["hf"]: e for e in CATALOG}
_CATALOG_BY_ID = {e["id"]: e for e in CATALOG}


def _expand(p: str) -> Path:
    return Path(p).expanduser()


def first_existing(paths) -> Optional[str]:
    for p in paths or []:
        ep = _expand(p)
        if ep.is_dir():
            return str(ep)
    return None


def meta_for(repo_or_id: str) -> dict:
    """Optional pretty name / packer_layers from CATALOG; empty if unknown."""
    if repo_or_id in _CATALOG_BY_ID:
        return dict(_CATALOG_BY_ID[repo_or_id])
    if repo_or_id in _CATALOG_BY_HF:
        return dict(_CATALOG_BY_HF[repo_or_id])
    # folder form
    hf = repo_or_id.replace("--", "/")
    if hf in _CATALOG_BY_HF:
        return dict(_CATALOG_BY_HF[hf])
    return {}


def slug_id(repo_id: str) -> str:
    """Stable short id for UI / WorkerManager (catalog id when known)."""
    m = meta_for(repo_id)
    if m.get("id"):
        return m["id"]
    leaf = repo_id.split("/")[-1].lower()
    leaf = re.sub(r"[^a-z0-9]+", "-", leaf).strip("-")
    return leaf or repo_id.replace("/", "-")


def resolve_entry(entry: dict, *, lead_home: Optional[Path] = None) -> dict:
    """Back-compat for callers that still pass a catalog-shaped dict."""
    out = dict(entry)
    paths = entry.get("lead_paths") or []
    if not paths and entry.get("hf"):
        folder = inv.repo_to_folder(entry["hf"])
        paths = [
            f"~/.exo/models/{folder}",
            f"~/.caravan/mlx-models/{folder}",
        ]
    lead = first_existing(paths)
    out["lead_path"] = lead
    out["available_lead"] = lead is not None
    prefs = entry.get("packer_paths") or (
        [f"~/.caravan/mlx-models/{inv.repo_to_folder(entry['hf'])}",
         f"~/.exo/models/{inv.repo_to_folder(entry['hf'])}"]
        if entry.get("hf") else []
    )
    out["packer_path"] = str(_expand(prefs[0])) if prefs else None
    out["packer_path_candidates"] = [str(_expand(p)) for p in prefs]
    return out


def _default_packer_layers(repo_id: str, n_layers: Optional[int]) -> int:
    m = meta_for(repo_id)
    if m.get("packer_layers"):
        return int(m["packer_layers"])
    # Day 18: match the download default (24, what every split download so far
    # used); only models with 24 layers or fewer split in half.
    if n_layers and 1 < n_layers <= 24:
        return max(1, n_layers // 2)
    return 24


def build_entries_from_inventories(
    *,
    node_inventories: list,
    nodes: Optional[list] = None,
    current_id: Optional[str] = None,
    current_hf: Optional[str] = None,
    fit_nodes: Optional[list] = None,
    max_split_stages: int = 2,
    include_unusable: bool = True,
) -> list:
    """Merge per-node inventories into Settings model rows.

    node_inventories: [{id, label, role, models: {repo_id: status_dict}}, ...]
    Status dict from model_inventory.inventory_payload()['models'][repo].

    Policy: omit models that appear on *no* node as a real tree. Models that
    are on disk but not loadable are included disabled with `disabled_reason`
    (clearer than a silent omission when shards are mid-download). Currently
    loaded model is always kept and selectable.
    """
    import web_picker
    import web_nodes

    nodes = nodes or []
    fit_nodes = fit_nodes if fit_nodes is not None else [
        n for n in nodes
        if isinstance(n, dict) and not n.get("offline") and not n.get("error")
    ]
    stages = web_nodes.split_stage_nodes(
        [n for n in nodes if isinstance(n, dict)] or fit_nodes,
        max_stages=max_split_stages,
    )
    if not stages:
        stages = fit_nodes[:max_split_stages] or nodes[:max_split_stages]

    # Union of repo ids seen on any node
    repos = set()
    by_node = {}
    for ni in node_inventories or []:
        nid = ni.get("id") or ni.get("label") or "node"
        by_node[nid] = ni
        for rid in (ni.get("models") or {}):
            repos.add(rid)

    # Also accept current even if inventory race-missed it
    if current_hf:
        repos.add(current_hf)

    rows = []
    for rid in sorted(repos):
        meta = meta_for(rid)
        mid = meta.get("id") or slug_id(rid)
        name = meta.get("name") or inv.pretty_name(rid)
        # Collect per-node status
        per = {}
        n_layers = None
        weights = None
        lead_path = None
        packer_path = None
        for ni in node_inventories or []:
            st = (ni.get("models") or {}).get(rid) or {}
            if not st:
                continue
            label = ni.get("label") or ni.get("id")
            role = ni.get("role") or "packer"
            per[label] = st
            if st.get("n_layers"):
                n_layers = st["n_layers"]
            if st.get("weights_gb") is not None:
                weights = max(weights or 0, float(st["weights_gb"]))
            if role == "lead" and st.get("path"):
                lead_path = st["path"]
            elif role != "lead" and st.get("path") and packer_path is None:
                packer_path = st["path"]

        # If lead_path missing but local scan has it
        if lead_path is None:
            local = inv.scan_local().get(rid)
            if local and local.get("path"):
                lead_path = local["path"]
                weights = weights or local.get("weights_gb")
                n_layers = n_layers or local.get("n_layers")

        pk = _default_packer_layers(rid, n_layers)

        # Placement saved at download time (one / split / all)
        placement = None
        for st in per.values():
            if isinstance(st, dict) and st.get("placement"):
                placement = st["placement"]
                break
        # Day 18: load at the split the shards were fetched for (saved, else detected).
        saved_pk = (placement or {}).get("packer_layers")
        if saved_pk:
            pk = int(saved_pk)
        else:
            for st in per.values():
                if isinstance(st, dict) and st.get("packer_layers") and not st.get("full_ok"):
                    pk = int(st["packer_layers"])
                    break

        # Usability across stages
        reasons = []
        usable = True
        is_current = bool(
            current_id and (mid == current_id or rid == current_id or rid == current_hf)
            or (current_hf and rid == current_hf)
        )

        if not per and not lead_path and not is_current:
            continue  # true phantom — never on disk

        # Format: MLX only today
        source = "hf-mlx"

        # Per-stage shard presence
        need_split = False
        fit = None
        if weights and fit_nodes:
            fit = web_picker.fit_check(
                weights_gb=float(weights),
                nodes=fit_nodes,
                split_ok=True,
                max_split_stages=max_split_stages,
            )
            if fit.get("color") == "red":
                usable = False
                reasons.append(fit.get("reason") or "too big")
            elif fit.get("nodes_needed") and fit["nodes_needed"] >= 2:
                need_split = True

        # Completeness requirements — honor saved placement when present.
        place_mode = (placement or {}).get("mode")
        place_ids = set((placement or {}).get("node_ids") or [])
        place_labels = set((placement or {}).get("node_labels") or [])

        def _st_for(stg):
            label = stg.get("label") or stg.get("id")
            st = per.get(label) or {}
            if not st:
                st = (by_node.get(stg.get("id") or "") or {}).get("models", {}).get(rid) or {}
            return label, st

        if place_mode == "one":
            # Usable as a single-Mini model on the Mini that holds the full copy.
            found = False
            want_keys = {str(x).lower() for x in (place_ids | place_labels)}
            for ni in node_inventories or []:
                label = ni.get("label") or ni.get("id")
                nid = ni.get("id")
                if want_keys and str(nid).lower() not in want_keys and str(label).lower() not in want_keys:
                    continue
                st = (ni.get("models") or {}).get(rid) or {}
                if st.get("full_ok") or st.get("lead_ok"):
                    found = True
                    # Prefer this node's path as lead
                    if st.get("path"):
                        lead_path = st["path"]
                    need_split = False
                    break
            if not found:
                usable = False
                want = ", ".join(place_labels or place_ids) or "target Mini"
                reasons.append(f"placement is 1 Mini ({want}) but full copy not ready")
        elif place_mode == "all":
            # Full copy on every Mini — usable on any one with full_ok.
            any_full = False
            for label, st in per.items():
                if st and (st.get("full_ok") or st.get("lead_ok")):
                    any_full = True
                    if st.get("path") and not lead_path:
                        lead_path = st["path"]
            if not any_full:
                usable = False
                reasons.append("copy-to-all placement incomplete on every Mini")
            need_split = False
        elif place_mode == "split" or need_split or (fit and fit.get("nodes_needed", 1) and fit.get("nodes_needed") >= 2):
            need_split = True
            for stg in stages:
                label, st = _st_for(stg)
                role = stg.get("role") or "packer"
                if place_ids and (stg.get("id") not in place_ids) and (label not in place_labels):
                    continue
                if role == "lead":
                    if not st.get("lead_ok") and not st.get("full_ok"):
                        usable = False
                        reasons.append(f"missing shards on {label}" if st else f"not on {label}")
                else:
                    if not st.get("packer_ok") and not st.get("full_ok"):
                        usable = False
                        reasons.append(f"missing shards on {label}" if st else f"not on {label}")
        else:
            # Single-node load: lead must be complete (full or lead_ok covering all)
            lead_stg = next((s for s in stages if s.get("role") == "lead"), stages[0] if stages else None)
            label = (lead_stg or {}).get("label") or "lead"
            st = per.get(label) or {}
            if not st and lead_path:
                local_i = inv.inspect_tree(lead_path, packer_layers=pk)
                st = {
                    "full_ok": local_i.get("full_ok"),
                    "lead_ok": local_i.get("lead_ok"),
                    "reason": local_i.get("reason"),
                }
            if not (st.get("full_ok") or st.get("lead_ok")):
                # Not on the lead: accept a full copy on ANY configured Mini and run
                # the single-Mini worker there (any node count).
                alt = None
                for ni in node_inventories or []:
                    nst = (ni.get("models") or {}).get(rid) or {}
                    if nst.get("full_ok"):
                        alt = (ni, nst)
                        break
                if alt:
                    ni, nst = alt
                    if nst.get("path"):
                        lead_path = nst["path"]
                    placement = {
                        "mode": "one", "k": 1,
                        "node_ids": [ni.get("id")], "node_labels": [ni.get("label") or ni.get("id")],
                        "full_copy": True, "inferred": True,
                    }
                    need_split = False
                else:
                    usable = False
                    why = st.get("reason") or (f"missing shards on {label}" if st else f"not on {label}")
                    reasons.append(why)

        # Architecture support (e.g. qwen3_5_text remapped; truly unknown flagged)
        try:
            from mlx_arch import architecture_status
            arch_path = lead_path or next(
                (st.get("path") for st in per.values() if st and st.get("path")), None)
            arch = architecture_status(arch_path) if arch_path else {"supported": True}
        except Exception:
            arch = {"supported": True}
        if not arch.get("supported"):
            usable = False
            reasons.append(arch.get("reason") or "unsupported architecture")

        if is_current:
            usable = True  # always keep loaded model selectable
            reasons = []

        if not usable and not include_unusable and not is_current:
            continue

        # Deduplicate reasons
        uniq = []
        for r in reasons:
            if r and r not in uniq:
                uniq.append(r)
        disabled_reason = "; ".join(uniq)

        row = {
            "id": mid,
            "name": name,
            "hf": rid,
            "packer_layers": pk,
            "notes": meta.get("notes") or "",
            "source": source,
            "native_mtp_available": any(st.get("native_mtp_available") for st in per.values()),
            "lead_path": lead_path,
            "packer_path": packer_path,
            "available_lead": bool(lead_path) and usable,
            "usable": usable,
            "disabled": not usable,
            "disabled_reason": disabled_reason,
            "weights_gb": weights,
            "fit": fit,
            "nodes": {
                (ni.get("label") or ni.get("id")): (ni.get("models") or {}).get(rid)
                for ni in (node_inventories or [])
            },
            "need_split": need_split if (placement or {}).get("mode") != "one" else False,
            "run_mode": (
                "single" if (placement or {}).get("mode") in ("one", "all")
                else ("split" if need_split or (placement or {}).get("mode") == "split" else "single")
            ),
            "placement": placement,
            "architecture": arch if isinstance(arch, dict) else None,
            "held_on": sorted({
                (ni.get("label") or ni.get("id"))
                for ni in (node_inventories or [])
                if (ni.get("models") or {}).get(rid)
            }),
        }
        rows.append(row)

    # Sort: usable first, then name; current pinned conceptually by UI select
    rows.sort(key=lambda r: (0 if r.get("usable") else 1, (r.get("name") or "").lower()))
    return rows


def list_models() -> list:
    """Local-only fallback (no SSH). Prefer App.list_loadable_models()."""
    inv_local = inv.inventory_payload()
    node = {
        "id": "local", "label": "local", "role": "lead",
        "models": inv_local.get("models") or {},
    }
    return build_entries_from_inventories(
        node_inventories=[node],
        nodes=[{"id": "local", "label": "local", "role": "lead",
                "ram": {"available_gb": 64, "total_gb": 64},
                "disk": {"free_gb": 500}}],
        include_unusable=True,
    )


def get_model(model_id: str) -> Optional[dict]:
    """Resolve a model for WorkerManager.switch — disk path required."""
    if not model_id:
        return None
    meta = meta_for(model_id)
    scanned = inv.scan_local()
    hf = meta.get("hf")
    if not hf and "/" in model_id:
        hf = model_id
    if not hf:
        for rid, info in scanned.items():
            if slug_id(rid) == model_id or rid == model_id:
                hf = rid
                break
    if not hf and model_id in scanned:
        hf = model_id
    if not hf:
        # Unknown id with no on-disk match
        if not meta:
            return None
        hf = meta.get("hf") or model_id

    folder = inv.repo_to_folder(hf)
    lead_paths = [
        f"~/.exo/models/{folder}",
        f"~/.caravan/mlx-models/{folder}",
    ]
    # Prefer live scanned path first
    if hf in scanned and scanned[hf].get("path"):
        lead_paths.insert(0, scanned[hf]["path"])
    packer_paths = [
        f"~/.caravan/mlx-models/{folder}",
        f"~/.exo/models/{folder}",
    ]
    entry = {
        "id": meta.get("id") or slug_id(hf),
        "name": meta.get("name") or inv.pretty_name(hf),
        "hf": hf,
        "packer_layers": meta.get("packer_layers") or _default_packer_layers(
            hf, (scanned.get(hf) or {}).get("n_layers")),
        "lead_paths": lead_paths,
        "packer_paths": packer_paths,
        "notes": meta.get("notes") or "",
    }
    resolved = resolve_entry(entry)
    # Placement + architecture from the on-disk tree (if any).
    try:
        from placement import read_placement
        from mlx_arch import architecture_status
    except ImportError:
        read_placement = architecture_status = None  # type: ignore
    place = None
    if read_placement and resolved.get("lead_path"):
        place = read_placement(resolved["lead_path"])
    if place is None and hf in scanned:
        place = (scanned[hf] or {}).get("placement")
    resolved["placement"] = place
    local = scanned.get(hf) or {}
    # Run mode: placement wins; else infer from shards on this Mini.
    mode = (place or {}).get("mode")
    if mode == "one" or mode == "all":
        resolved["need_split"] = False
        resolved["run_mode"] = "single"
    elif mode == "split":
        resolved["need_split"] = True
        resolved["run_mode"] = "split"
    else:
        # No placement file: split only when this tree is clearly a lead half
        # (split-lead) and not a full copy.
        kind = local.get("kind") or ""
        if kind == "full" or local.get("full_ok"):
            resolved["need_split"] = False
            resolved["run_mode"] = "single"
        elif kind == "split-lead" or (local.get("lead_ok") and not local.get("full_ok")):
            resolved["need_split"] = True
            resolved["run_mode"] = "split"
        else:
            # Default historical behavior for unknown trees: try split
            # (web UI used to always start packer). Prefer single when the
            # folder looks complete enough for one Mini.
            resolved["need_split"] = False
            resolved["run_mode"] = "single"
    if architecture_status and resolved.get("lead_path"):
        arch = architecture_status(resolved["lead_path"])
        resolved["architecture"] = arch
        if not arch.get("supported"):
            resolved["available_lead"] = False
            resolved["usable"] = False
            resolved["disabled"] = True
            resolved["disabled_reason"] = arch.get("reason") or "unsupported architecture"
    # Catalog-only metadata with nothing on disk: still return (available_lead
    # False) so switch() can raise FileNotFoundError with a clear id. Truly
    # unknown names (no meta, no disk) already returned None above.
    return resolved
