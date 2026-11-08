"""On-disk MLX model inventory + completeness for the Settings dropdown.

Settings must never list static catalog phantoms. A model is *usable* only when
every node its load plan needs has a complete tree (config, tokenizer, shards,
no .incomplete), the format can run today (MLX), and capacity fit is not red.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "agent"))

MODEL_ROOTS = [
    Path.home() / ".caravan" / "mlx-models",
    Path.home() / ".exo" / "models",
]

TOKENIZER_NAMES = (
    "tokenizer.json", "tokenizer.model", "tokenizer.tiktoken",
    "vocab.json", "spiece.model",
)
SKIP_DIR_NAMES = {"drafts", "caches", ".cache"}


def folder_to_repo(name: str) -> str:
    return name.replace("--", "/")


def repo_to_folder(repo: str) -> str:
    return repo.replace("/", "--")


def pretty_name(repo_or_folder: str) -> str:
    leaf = repo_or_folder.split("/")[-1].replace("--", "/")
    leaf = re.sub(r"[-_]+", " ", leaf)
    return leaf.strip() or repo_or_folder


def _has_tokenizer(d: Path) -> bool:
    return any((d / n).exists() for n in TOKENIZER_NAMES)


def _incomplete_files(d: Path) -> list:
    out = []
    cache = d / ".cache" / "huggingface" / "download"
    if cache.is_dir():
        for p in cache.rglob("*"):
            if p.is_file() and p.name.endswith(".incomplete"):
                out.append(str(p.relative_to(d)))
    # also stray *.incomplete next to shards
    for p in d.glob("*.incomplete"):
        out.append(p.name)
    return out


def _weights_gb_from_tree(d: Path, index: Optional[dict] = None) -> Optional[float]:
    total = 0
    if index and isinstance(index.get("weight_map"), dict):
        files = set(index["weight_map"].values())
        for f in files:
            p = d / f
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        if total:
            return round(total / 1e9, 2)
    # single-file or sum of present safetensors
    for p in d.glob("*.safetensors"):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return round(total / 1e9, 2) if total else None


def inspect_tree(path: str | Path, *, packer_layers: Optional[int] = None) -> dict:
    """Completeness of one local MLX model directory.

    Returns keys: path, ok, kind ('full'|'split-lead'|'split-packer'|'partial'|'empty'),
    missing, incomplete, weights_gb, n_layers, has_config, has_tokenizer, has_index,
    lead_ok, packer_ok, reason.
    """
    d = Path(path).expanduser()
    base = {
        "path": str(d),
        "ok": False,
        "kind": "empty",
        "missing": [],
        "incomplete": [],
        "weights_gb": None,
        "n_layers": None,
        "has_config": False,
        "has_tokenizer": False,
        "has_index": False,
        "lead_ok": False,
        "packer_ok": False,
        "full_ok": False,
        "native_mtp_available": (d / "caravan-mtp" / "model.safetensors").is_file() and (d / "caravan-mtp" / "config.json").is_file(),
        "reason": "",
        "warnings": [],
    }
    if not d.is_dir():
        base["reason"] = "missing folder"
        return base

    cfg_p, idx_p = d / "config.json", d / "model.safetensors.index.json"
    base["has_config"] = cfg_p.is_file()
    base["has_index"] = idx_p.is_file()
    base["has_tokenizer"] = _has_tokenizer(d)
    base["incomplete"] = _incomplete_files(d)
    base["placement"] = None
    place_p = d / "caravan-placement.json"
    if place_p.is_file():
        try:
            base["placement"] = json.loads(place_p.read_text())
        except (OSError, ValueError):
            base["placement"] = None

    if not base["has_config"]:
        base["reason"] = "missing config.json"
        base["kind"] = "partial"
        return base
    if not base["has_tokenizer"]:
        base["reason"] = "missing tokenizer"
        base["kind"] = "partial"
        return base
    if base["incomplete"]:
        base["reason"] = f"{len(base['incomplete'])} incomplete download file(s)"
        base["kind"] = "partial"
        # still compute what we can below

    try:
        cfg = json.loads(cfg_p.read_text())
    except (OSError, ValueError) as e:
        base["reason"] = f"bad config.json: {e}"
        base["kind"] = "partial"
        return base

    try:
        from mlx_arch import model_warnings
        base["warnings"] = model_warnings(cfg)
    except Exception:  # noqa: BLE001
        pass

    # Single-file MLX (no index)
    single = d / "model.safetensors"
    if not base["has_index"]:
        if single.is_file() and not base["incomplete"]:
            base["weights_gb"] = round(single.stat().st_size / 1e9, 2)
            base["ok"] = True
            base["full_ok"] = base["lead_ok"] = base["packer_ok"] = True
            base["kind"] = "full"
            base["reason"] = ""
            return base
        base["reason"] = base["reason"] or "missing model.safetensors.index.json"
        base["kind"] = "partial"
        return base

    try:
        index = json.loads(idx_p.read_text())
    except (OSError, ValueError) as e:
        base["reason"] = f"bad index: {e}"
        base["kind"] = "partial"
        return base

    wm = index.get("weight_map") or {}
    try:
        from mlx_arch import model_warnings
        base["warnings"] = model_warnings(cfg, wm)
    except Exception:  # noqa: BLE001
        pass
    all_shards = sorted(set(wm.values()))
    base["weights_gb"] = _weights_gb_from_tree(d, index)

    # Role plans (2-stage runtime). The split saved at download time wins over
    # the caller's default (Day 18: catalog said 16, shards were fetched for 24).
    saved_pk = (base["placement"] or {}).get("packer_layers")
    if saved_pk:
        packer_layers = int(saved_pk)
    try:
        from mlx_split_fetch import plan_files, n_layers_of
        base["n_layers"] = n_layers_of(cfg)
        present0 = {f for f in all_shards if (d / f).is_file()}
        plan = plan_files(cfg, index, packer_layers)
        if (not saved_pk and (base["placement"] or {}).get("mode") == "split"
                and not set(all_shards) <= present0):
            # Older split download without a saved split: find one the shards satisfy,
            # trying the old server default (24) first.
            def _fits(pk):
                pl = plan_files(cfg, index, pk)
                return set(pl["head"]) <= present0 or set(pl["front"]) <= present0
            if not _fits(packer_layers):
                n = base["n_layers"] or 0
                for pk in [24] + list(range(1, n)):
                    if pk < n and _fits(pk):
                        packer_layers = pk
                        plan = plan_files(cfg, index, pk)
                        base["packer_layers_detected"] = True
                        break
        base["packer_layers"] = packer_layers
        need_lead = set(plan["head"])
        need_pack = set(plan["front"])
    except Exception as e:  # noqa: BLE001
        # Fall back: require every weight_map shard
        need_lead = need_pack = set(all_shards)
        base["n_layers"] = None
        plan_err = str(e)
    else:
        plan_err = None

    present = {f for f in all_shards if (d / f).is_file()}
    missing_all = [f for f in all_shards if f not in present]
    missing_lead = sorted(need_lead - present)
    missing_pack = sorted(need_pack - present)

    base["missing"] = missing_all
    base["lead_ok"] = not missing_lead and not base["incomplete"] and base["has_tokenizer"]
    base["packer_ok"] = not missing_pack and not base["incomplete"] and base["has_tokenizer"]
    base["full_ok"] = not missing_all and not base["incomplete"] and base["has_tokenizer"]

    if base["full_ok"]:
        base["ok"] = True
        base["kind"] = "full"
        base["reason"] = ""
    elif base["lead_ok"] and not base["packer_ok"]:
        base["ok"] = True  # usable as lead half
        base["kind"] = "split-lead"
        base["reason"] = "" if not missing_pack else f"lead shards ok; packer would need {len(missing_pack)} more"
    elif base["packer_ok"] and not base["lead_ok"]:
        base["ok"] = True
        base["kind"] = "split-packer"
        base["reason"] = "" if not missing_lead else f"packer shards ok; lead would need {len(missing_lead)} more"
    else:
        base["ok"] = False
        base["kind"] = "partial"
        if base["incomplete"]:
            base["reason"] = f"{len(base['incomplete'])} incomplete download file(s)"
        elif missing_lead and missing_pack:
            base["reason"] = f"missing {len(missing_all)} shard(s)"
        elif missing_lead:
            base["reason"] = f"missing {len(missing_lead)} lead shard(s)"
        elif missing_pack:
            base["reason"] = f"missing {len(missing_pack)} packer shard(s)"
        else:
            base["reason"] = plan_err or "incomplete"
    return base


def scan_local(*, roots: Optional[list] = None, packer_layers: Optional[int] = None) -> dict:
    """Map repo_id -> best local inspect (prefers fuller trees)."""
    roots = roots or MODEL_ROOTS
    out = {}
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for p in sorted(root.iterdir()):
            if not p.is_dir() or p.name in SKIP_DIR_NAMES or p.name.startswith("."):
                continue
            # skip non-model litter (logs live as files; caches dir skipped)
            if not ((p / "config.json").exists() or list(p.glob("*.safetensors"))
                    or (p / "model.safetensors.index.json").exists()):
                continue
            rid = folder_to_repo(p.name)
            info = inspect_tree(p, packer_layers=packer_layers)
            info["repo_id"] = rid
            info["folder"] = p.name
            prev = out.get(rid)
            if prev is None or _rank(info) > _rank(prev):
                out[rid] = info
    return out


def _rank(info: dict) -> tuple:
    return (
        1 if info.get("full_ok") else 0,
        1 if info.get("lead_ok") else 0,
        1 if info.get("packer_ok") else 0,
        float(info.get("weights_gb") or 0),
    )


def inventory_payload(*, packer_layers: Optional[int] = None) -> dict:
    """JSON-friendly scan for local or remote (`picker_disk_sizes --inventory`)."""
    models = scan_local(packer_layers=packer_layers)
    return {
        "models": {
            rid: {
                "path": m.get("path"),
                "folder": m.get("folder"),
                "weights_gb": m.get("weights_gb"),
                "kind": m.get("kind"),
                "ok": m.get("ok"),
                "full_ok": m.get("full_ok"),
                "lead_ok": m.get("lead_ok"),
                "packer_ok": m.get("packer_ok"),
                "reason": m.get("reason") or "",
                "n_layers": m.get("n_layers"),
                "incomplete_n": len(m.get("incomplete") or []),
                "missing_n": len(m.get("missing") or []),
                "placement": m.get("placement"),
                "native_mtp_available": bool(m.get("native_mtp_available")),
                "warnings": list(m.get("warnings") or []),
            }
            for rid, m in models.items()
        }
    }
