"""Plain-language errors for Self-tuning and Auto-tune.

The page shows only a short sentence. Full exception text, HTTP bodies,
paths, and hostnames stay in the log.
"""
from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

# Settings-row names, same words the page already uses.
KNOB_LABELS = {
    "kv_bits": T("server.gguf_self_tune.memory_compression"),
    "cache_type": T("server.gguf_self_tune.memory_compression"),
    "fuse_kernels": T("server.web_settings.fused_kernels"),
    "keepalive": T("server.web_settings.gpu_keep_warm"),
    "shared_prefix": T("server.web_tune_errors.shared_start"),
    "shared_start": T("server.web_tune_errors.shared_start"),
    "slot_save": T("server.web_tune_errors.shared_start"),
    "guess_ahead": "Guess-ahead",
    "native_mtp": "Guess-ahead",
    "pipeline_chats": T("server.web_settings.two_chats"),
    "adaptive_lookup": T("server.web_tune_errors.prompt_lookup"),
    "prompt_lookup": T("server.web_tune_errors.prompt_lookup"),
    "flash_attn": T("server.gguf_self_tune.flash_attention"),
    "ubatch": T("server.gguf_self_tune.prompt_batch"),
    "packer_layers": T("server.web_tune_errors.the_layer_split"),
}

log = logging.getLogger("caravan-web")


def knob_label(name) -> str | None:
    if not name:
        return None
    return KNOB_LABELS.get(str(name))


def running_knob(schedule) -> str | None:
    for item in schedule or []:
        if isinstance(item, dict) and item.get("state") == "running":
            return item.get("name")
    return None


def http_body(exc) -> str:
    """Read an HTTPError body once; safe if it was already consumed."""
    raw = getattr(exc, "_caravan_body", None)
    if raw is not None:
        return raw
    body = ""
    try:
        data = exc.read() if hasattr(exc, "read") else b""
        body = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data or "")
    except Exception:
        body = ""
    try:
        setattr(exc, "_caravan_body", body)
    except Exception:
        pass
    return body


def http_json_error(body: str) -> str:
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return ""
    if isinstance(parsed, dict) and parsed.get("error"):
        err = parsed["error"]
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)[:1000]
        return str(err)[:1000]
    return ""


def detail_of(error, *, body: str = "") -> str:
    """Full text for the log, never for the page."""
    if isinstance(error, HTTPError):
        body = body or http_body(error)
        parsed = http_json_error(body)
        parts = [f"HTTPError: HTTP Error {error.code}: {error.reason}"]
        if parsed:
            parts.append(parsed)
        elif body.strip():
            parts.append(body.strip()[:2000])
        return " ".join(parts)
    if isinstance(error, BaseException):
        return f"{type(error).__name__}: {error}"
    return str(error or "")


def log_tune_error(detail: str, *, source: str | None = None) -> None:
    who = source or "trial"
    log.warning("optimize/%s failed: %s", who, detail)
    print(f"[caravan-web] optimize/{who} failed: {detail}", flush=True)


def _own(key: str) -> str:
    """The fixed start of one of Caravan's own messages (lowercase, before its
    first value), so the checks below also know it in the active language."""
    return T(key).split("{", 1)[0].rstrip(": ").lower() or "\0"


def plain_tune_error(error, *, schedule=None, source=None, detail=None) -> str:
    """Short sentence for the page. Never interpolates raw exception text."""
    if source == "self_tune":
        who = T("server.web_tune_errors.self_tuning")
    elif source == "optimize_now" or source == "now":
        who = T("server.web_tune_errors.auto_tune")
    else:
        who = T("server.web_tune_errors.the_trial")
    label = knob_label(running_knob(schedule))
    trying = T("server.web_tune_errors.while_trying_label", label=label) if label else ""
    text = detail if detail is not None else detail_of(error)
    low = text.lower()

    def sentence(why: str, again: bool = False) -> str:
        tail = T("server.web_tune_errors.try_loading_again") if again else T("server.web_tune_errors.the_model_is_back_on_the")
        return T("server.web_tune_errors.who_stopped_trying_why_tail", who=who, trying=trying, why=why, tail=tail)

    if "400" in text or "bad request" in low or "was rejected" in low:
        return sentence(T("server.web_tune_errors.a_trial_setting_was_rejected"))
    if "timed out" in low or "timeout" in low:
        return sentence(T("server.web_tune_errors.a_trial_took_too_long"))
    # English words come from workers and HTTP; _own(...) is Caravan's own text.
    if "restore failed" in low or _own("server.web_optimize.restore_failed_error") in low:
        return sentence(T("server.web_tune_errors.the_model_couldnt_return_to_the"), again=True)
    if ("reload failed" in low or "load failed" in low or _own("server.web_optimize.reload_failed_error") in low
            or _own("server.web_workers.load_failed_e") in low):
        return sentence(T("server.web_tune_errors.the_model_didnt_finish_reloading"), again=True)
    if any(s in low for s in ("connection refused", "urlerror", "couldn't reach",
                              "network is unreachable", "connection reset",
                              _own("server.web_tunnels.couldnt_reach_who_try_loading_again"))):
        return sentence(T("server.web_tune_errors.couldnt_reach_the_model"), again=True)
    if "model changed" in low or _own("server.web_optimize.model_changed_during_auto_tune") in low:
        return T("server.web_tune_errors.who_stopped_because_the_model_changed", who=who)
    if "500" in text or "internal server" in low or "httperror" in low:
        return sentence(T("server.web_tune_errors.a_trial_setting_ran_into_a"))
    if "cancel" in low:
        return T("server.web_tune_errors.who_was_canceled_the_model_is", who=who)
    return sentence(T("server.web_tune_errors.something_went_wrong_during_a_trial"))


def public_error(snap: dict | None) -> str | None:
    """Plain error from an optimize snapshot, or None."""
    snap = snap or {}
    err = snap.get("error")
    if not err:
        return None
    return plain_tune_error(
        err, schedule=snap.get("schedule"),
        source=snap.get("source"),
        detail=snap.get("error_detail") or err,
    )


def public_optimize_status(snap: dict | None) -> dict:
    """Subset of the snapshot used by GET /api/status (no raw detail)."""
    snap = dict(snap or {})
    err = public_error(snap)
    return {
        "running": snap.get("running"),
        "mode": snap.get("mode"),
        "phase": snap.get("phase"),
        "step": snap.get("step"),
        "started": snap.get("started"),
        "elapsed_s": snap.get("elapsed_s"),
        "paused": snap.get("paused"),
        "eta_s": snap.get("eta_s"),
        "error": err,
        "source": snap.get("source"),
        "unchanged": (snap.get("summary") or {}).get("unchanged")
        if isinstance(snap.get("summary"), dict) else snap.get("unchanged"),
    }
