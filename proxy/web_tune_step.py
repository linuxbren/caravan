"""Plain-language Auto-tune step lines for the Settings page.

The page shows these while a run is in progress. Knob ids and raw
quant names stay off the page; sizes that were not run are simply
left out of the wording.
"""
from __future__ import annotations

import time
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

KNOB_LABELS = {
    "kv_bits": T("server.gguf_self_tune.memory_compression"),
    "cache_type": T("server.gguf_self_tune.memory_compression"),
    "flash_attn": T("server.gguf_self_tune.flash_attention"),
    "ubatch": T("server.gguf_self_tune.prompt_batch"),
    "shared_start": T("server.web_tune_errors.shared_start"),
    "shared_prefix": T("server.web_tune_errors.shared_start"),
    "pipeline_chats": T("server.web_settings.two_chats"),
    "fuse_kernels": T("server.web_settings.fused_kernels"),
    "keepalive": T("server.web_settings.gpu_keep_warm"),
    "guess_ahead": "Guess-ahead",
    "prompt_lookup": T("server.web_tune_errors.prompt_lookup"),
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
        return T("server.gguf_self_tune.on") if value else T("server.gguf_self_tune.off")
    s = str(value).strip()
    low = s.lower()
    knob = str(knob or "")
    if knob in ("kv_bits", "cache_type") and low in _COMPRESSION:
        return _COMPRESSION[low]
    if low in ("on", "true"):
        return T("server.gguf_self_tune.on")
    if low in ("off", "false"):
        return T("server.gguf_self_tune.off")
    return s


def _prompt_bit(kind=None, index=None, total=None) -> str:
    if kind == "long":
        return T("server.web_tune_step.long_prompt")
    if index and total:
        label = T("server.web_tune_step.short_prompt") if kind in (None, "short") else "prompt"
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
        return T("server.web_tune_step.paused")
    if action in ("waiting", "waiting for your chat"):
        return T("server.web_tune_step.waiting_for_your_chat_to_finish")
    if action in ("reloading_winner", "restoring", "restoring winners"):
        return T("server.web_tune_step.reloading_with_the_winner")
    if action in ("reloading", "reload"):
        if target:
            return T("server.web_tune_step.reloading_to_try_target", target=target)
        return T("server.web_tune_step.reloading")
    if action == "starting":
        return T("server.web_tune_step.starting")
    if action == "done":
        return T("server.web_tune_step.done")
    if action in ("canceled", "cancelled"):
        return T("server.web_tune_step.stopped")
    if action in ("error", "stopped (error)"):
        return T("server.web_tune_step.stopped")
    if action in ("trying", "try", "challenger"):
        head = T("server.web_tune_step.trying_target", target=target) if target else T("server.web_tune_step.trying_a_new_setting")
        return f"{head} · {extra}" if extra else head
    # measuring the current / incumbent setup
    head = T("server.web_tune_step.measuring_the_current_setup")
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
    return T("server.web_tune_step.m_min_r_s", m=m, r=r) if r else f"{m} min"
