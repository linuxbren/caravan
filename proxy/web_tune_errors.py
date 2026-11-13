"""Plain-language errors for Self-tuning and Auto-tune.

The page shows only a short sentence. Full exception text, HTTP bodies,
paths, and hostnames stay in the log.
"""
from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError

# Settings-row names, same words the page already uses.
KNOB_LABELS = {
    "kv_bits": "Memory compression",
    "cache_type": "Memory compression",
    "fuse_kernels": "Fused kernels",
    "keepalive": "GPU keep-warm",
    "shared_prefix": "Shared start",
    "shared_start": "Shared start",
    "slot_save": "Shared start",
    "guess_ahead": "Guess-ahead",
    "native_mtp": "Guess-ahead",
    "pipeline_chats": "Two chats",
    "adaptive_lookup": "Prompt lookup",
    "prompt_lookup": "Prompt lookup",
    "flash_attn": "Flash attention",
    "ubatch": "Prompt batch",
    "packer_layers": "the layer split",
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


def plain_tune_error(error, *, schedule=None, source=None, detail=None) -> str:
    """Short sentence for the page. Never interpolates raw exception text."""
    if source == "self_tune":
        who = "Self-tuning"
    elif source == "optimize_now" or source == "now":
        who = "Auto-tune"
    else:
        who = "The trial"
    label = knob_label(running_knob(schedule))
    trying = f" while trying {label}" if label else ""
    text = detail if detail is not None else detail_of(error)
    low = text.lower()

    def sentence(why: str, again: bool = False) -> str:
        tail = " Try loading again." if again else " The model is back on the previous settings."
        return f"{who} stopped{trying}. {why}{tail}"

    if "400" in text or "bad request" in low or "was rejected" in low:
        return sentence("A trial setting was rejected.")
    if "timed out" in low or "timeout" in low:
        return sentence("A trial took too long.")
    if "restore failed" in low:
        return sentence("The model couldn't return to the previous settings.", again=True)
    if "reload failed" in low or "load failed" in low:
        return sentence("The model didn't finish reloading.", again=True)
    if any(s in low for s in ("connection refused", "urlerror", "couldn't reach",
                              "network is unreachable", "connection reset")):
        return sentence("Couldn't reach the model.", again=True)
    if "model changed" in low:
        return f"{who} stopped because the model changed. Load the model and try again."
    if "500" in text or "internal server" in low or "httperror" in low:
        return sentence("A trial setting ran into a problem.")
    if "cancel" in low:
        return f"{who} was canceled. The model is back on the previous settings."
    return sentence("Something went wrong during a trial.")


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
