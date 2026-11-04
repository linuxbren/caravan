"""Day 15: optimization toggles the web page can set per model load.

Each option is "auto" (Caravan's learned/default behavior) or a pinned value.
Only real agent/mlx_worker.py flags are used; nothing here is invented.
"""
from __future__ import annotations

# id -> label, plain help, allowed values (first is "auto")
OPTIONS = [
    {"id": "guess_ahead", "label": "Guess-ahead",
     "help": "A small helper model guesses the next few words; the big model checks them in one go.",
     "values": ["auto", "on", "off"]},
    {"id": "self_tune", "label": "Self-tuning",
     "help": "Caravan tries settings on real chats and keeps the faster ones (saved per model).",
     "values": ["auto", "off"]},
    {"id": "shared_start", "label": "Shared start (trim / rebuild)",
     "help": "Reuse the already-read start of a repeated system prompt. Trims memory back to it, "
             "or rebuilds it on both Minis for models that can't be trimmed (Gemma).",
     "values": ["auto", "on", "off"]},
    {"id": "pipeline_chats", "label": "Two chats",
     "help": "Overlap two chats across the Minis so neither waits on the other.",
     "values": ["auto", "1", "2"]},
    {"id": "fuse_kernels", "label": "Fused kernels",
     "help": "Experimental combined GPU steps (off by default).",
     "values": ["auto", "on"]},
    {"id": "kv_bits", "label": "Memory compression",
     "help": "Store the chat memory in 8 or 4 bits instead of 16 (less RAM, slightly lower quality).",
     "values": ["auto", "8", "4"]},
    {"id": "keepalive", "label": "GPU keep-warm",
     "help": "Keep the lead's GPU warm while waiting on the other Mini.",
     "values": ["auto", "off"]},
]
_BY_ID = {o["id"]: o for o in OPTIONS}


def normalize(settings) -> dict:
    """Fill defaults, validate. Raises ValueError on unknown keys/values."""
    settings = settings or {}
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    out = {}
    for k, v in settings.items():
        if k not in _BY_ID:
            raise ValueError(f"unknown setting: {k}")
        v = str(v).strip().lower()
        if v not in _BY_ID[k]["values"]:
            raise ValueError(f"{k}: want one of {_BY_ID[k]['values']}, got {v!r}")
    for o in OPTIONS:
        out[o["id"]] = str(settings.get(o["id"], "auto")).strip().lower()
    return out


def to_args(settings) -> tuple[list, list]:
    """Return (lead_args, packer_args) for mlx_worker.py."""
    s = normalize(settings)
    lead, packer = [], []
    if s["guess_ahead"] == "off":
        lead.append("--no-split-draft")
    elif s["guess_ahead"] == "on":
        lead.append("--pin-guess-ahead")
    if s["self_tune"] == "off":
        lead.append("--no-learn")
    if s["shared_start"] == "on":
        lead.append("--split-shared-prefix-cache")
    elif s["shared_start"] == "off":
        lead.append("--no-split-shared-prefix-cache")
    if s["pipeline_chats"] in ("1", "2"):
        lead += ["--split-pipeline-chats", s["pipeline_chats"]]
    if s["fuse_kernels"] == "on":
        lead += ["--fuse-kernels", "all"]
        packer += ["--fuse-kernels", "all"]
    if s["kv_bits"] in ("8", "4"):
        lead += ["--kv-bits", s["kv_bits"]]
        packer += ["--kv-bits", s["kv_bits"]]
    if s["keepalive"] == "off":
        lead.append("--no-split-keepalive")
    return lead, packer
