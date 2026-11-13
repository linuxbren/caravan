"""Plain-language Auto-tune step lines for the Settings page.

The page shows these while a run is in progress. Knob ids and raw
quant names stay off the page; sizes that were not run are simply
left out of the wording.
"""
from __future__ import annotations

import time

KNOB_LABELS = {
    "kv_bits": "Memory compression",
    "cache_type": "Memory compression",
    "flash_attn": "Flash attention",
    "ubatch": "Prompt batch",
    "shared_start": "Shared start",
    "shared_prefix": "Shared start",
    "pipeline_chats": "Two chats",
    "fuse_kernels": "Fused kernels",
    "keepalive": "GPU keep-warm",
    "guess_ahead": "Guess-ahead",
    "prompt_lookup": "Prompt lookup",
}

# Memory-compression raw values → the same numbers Settings uses (16 / 8).
_COMPRESSION = {
    "f16": "16", "float16": "16", "16": "16",
    "q8_0": "8", "q8": "8", "8": "8",
    "q4_0": "4", "q4": "4", "4": "4",
}


def knob_label(name) -> str:
    if not name:
        return ""
    key = str(name).strip()
    return KNOB_LABELS.get(key, key.replace("_", " ").strip().capitalize())


def friendly_value(knob, value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "On" if value else "Off"
    s = str(value).strip()
    low = s.lower()
    knob = str(knob or "")
    if knob in ("kv_bits", "cache_type") and low in _COMPRESSION:
        return _COMPRESSION[low]
    if low in ("on", "true"):
        return "On"
    if low in ("off", "false"):
        return "Off"
    return s


def _prompt_bit(kind=None, index=None, total=None) -> str:
    if kind == "long":
        return "long prompt"
    if index and total:
        label = "short prompt" if kind in (None, "short") else "prompt"
        return f"{label} {int(index)} of {int(total)}"
    if index:
        return f"prompt {int(index)}"
    return ""


def format_step(*, action="starting", knob=None, value=None,
                kind=None, index=None, total=None) -> str:
    """One plain line for the live Auto-tune step.

    Actions: starting, measuring, trying, reloading, reloading_winner,
    paused, waiting, done, canceled, error.
    """
    action = (action or "starting").strip().lower()
    extra = _prompt_bit(kind, index, total)
    label = knob_label(knob)
    val = friendly_value(knob, value)
    target = " ".join(p for p in (label, val) if p)

    if action in ("paused", "pause"):
        return "Paused"
    if action in ("waiting", "waiting for your chat"):
        return "Waiting for your chat to finish…"
    if action in ("reloading_winner", "restoring", "restoring winners"):
        return "Reloading with the winner…"
    if action in ("reloading", "reload"):
        if target:
            return f"Reloading to try {target}…"
        return "Reloading…"
    if action == "starting":
        return "Starting…"
    if action == "done":
        return "Done"
    if action in ("canceled", "cancelled"):
        return "Stopped"
    if action in ("error", "stopped (error)"):
        return "Stopped"
    if action in ("trying", "try", "challenger"):
        head = f"Trying {target}" if target else "Trying a new setting"
        return f"{head} · {extra}" if extra else head
    # measuring the current / incumbent setup
    head = "Measuring the current setup"
    return f"{head} · {extra}" if extra else head


def elapsed_s(started, *, now=None) -> int | None:
    if not started:
        return None
    try:
        t = float(started)
    except (TypeError, ValueError):
        return None
    if t <= 0:
        return None
    return max(0, int((now if now is not None else time.time()) - t))


def decorate(snap: dict, *, now=None) -> dict:
    """Add elapsed_s to a snapshot copy. Leaves other fields as they are."""
    out = dict(snap or {})
    if out.get("running") and out.get("started"):
        out["elapsed_s"] = elapsed_s(out["started"], now=now)
    return out


def format_elapsed(seconds) -> str:
    if seconds is None:
        return ""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        return ""
    if s < 90:
        return f"{s}s"
    m, r = divmod(s, 60)
    return f"{m} min {r}s" if r else f"{m} min"
