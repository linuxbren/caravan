"""Models the Caravan web UI can load. Only lists copies that already exist
on the Minis — never downloads. Paths match Day 12/13 lab scripts.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Thunderbolt address of EXO2 as seen from EXO1 (Packer 1 listen target).
DEFAULT_PACKER_PEER = os.environ.get("CARAVAN_WEB_PACKER_PEER", "169.254.103.191:5560")
DEFAULT_PACKER_SSH = os.environ.get("CARAVAN_WEB_PACKER_SSH", "brenden@169.254.103.191")

# id → display + per-role local paths + default packer layer count.
# lead_paths / packer_paths are tried in order; first existing wins.
CATALOG = [
    {
        "id": "qwen3-30b-a3b-4bit",
        "name": "Qwen3 30B-A3B 4-bit",
        "hf": "mlx-community/Qwen3-30B-A3B-4bit",
        "packer_layers": 24,
        "lead_paths": [
            "~/.exo/models/mlx-community--Qwen3-30B-A3B-4bit",
            "~/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit",
        ],
        "packer_paths": [
            "~/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit",
            "~/.exo/models/mlx-community--Qwen3-30B-A3B-4bit",
        ],
        "notes": "Day 12 scoreboard workhorse",
    },
    {
        "id": "gemma-4-26b-a4b-4bit",
        "name": "Gemma 4 26B-A4B 4-bit",
        "hf": "mlx-community/gemma-4-26b-a4b-it-4bit",
        "packer_layers": 15,
        "lead_paths": [
            "~/.exo/models/mlx-community--gemma-4-26b-a4b-it-4bit",
            "~/.caravan/mlx-models/mlx-community--gemma-4-26b-a4b-it-4bit",
        ],
        "packer_paths": [
            "~/.caravan/mlx-models/mlx-community--gemma-4-26b-a4b-it-4bit",
            "~/.exo/models/mlx-community--gemma-4-26b-a4b-it-4bit",
        ],
        "notes": "Day 13 shared-start fix",
    },
    {
        "id": "gpt-oss-20b-mxfp4",
        "name": "GPT-OSS 20B MXFP4",
        "hf": "mlx-community/gpt-oss-20b-MXFP4-Q8",
        "packer_layers": 12,
        "lead_paths": [
            "~/.exo/models/mlx-community--gpt-oss-20b-MXFP4-Q8",
            "~/.caravan/mlx-models/mlx-community--gpt-oss-20b-MXFP4-Q8",
        ],
        "packer_paths": [
            "~/.caravan/mlx-models/mlx-community--gpt-oss-20b-MXFP4-Q8",
            "~/.exo/models/mlx-community--gpt-oss-20b-MXFP4-Q8",
        ],
        "notes": "No draft pair yet",
    },
]


def _expand(p: str) -> Path:
    return Path(p).expanduser()


def first_existing(paths) -> Optional[str]:
    for p in paths or []:
        ep = _expand(p)
        if ep.is_dir():
            return str(ep)
    return None


def resolve_entry(entry: dict, *, lead_home: Optional[Path] = None) -> dict:
    """Return a copy with lead_path filled for *this* machine. packer_path is
    the preferred remote path string (not verified here — verified via SSH).
    """
    out = dict(entry)
    lead = first_existing(entry.get("lead_paths") or [])
    out["lead_path"] = lead
    out["available_lead"] = lead is not None
    # Preferred packer path (what we ask EXO2 to use).
    prefs = entry.get("packer_paths") or []
    out["packer_path"] = str(_expand(prefs[0])) if prefs else None
    out["packer_path_candidates"] = [str(_expand(p)) for p in prefs]
    return out


def list_models() -> list:
    return [resolve_entry(e) for e in CATALOG]


def get_model(model_id: str) -> Optional[dict]:
    for e in CATALOG:
        if e["id"] == model_id or e.get("hf") == model_id:
            return resolve_entry(e)
    return None
