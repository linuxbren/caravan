"""Per-model, per-optimization-set reply speed averages for the chat page.

Stored in ~/.caravan/speed_averages.json so the numbers describe these Macs
and this model setup, not a single browser. The page shows one quiet line
such as "Usually 42 words/s, first word in 1.2 s" when at least one reply
has been recorded for the current model and the current optimizations.
The rate is the model's measured token rate, shown as words/s in plain
language (one token is roughly one word). Changing an optimization starts
a separate average.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# Option ids that identify a setup. Order is fixed for a stable key.
OPT_IDS = (
    "self_tune",
    "guess_ahead",
    "prompt_lookup",
    "shared_start",
    "pipeline_chats",
    "fuse_kernels",
    "kv_bits",
    "keepalive",
)

STORE_PATH = Path(os.environ.get(
    "CARAVAN_SPEED_AVERAGES",
    str(Path.home() / ".caravan" / "speed_averages.json"),
)).expanduser()


def fingerprint(opts) -> str:
    """Stable key for one set of optimizations."""
    opts = opts if isinstance(opts, dict) else {}
    clean = {k: str(opts.get(k, "")).strip().lower() for k in OPT_IDS}
    return json.dumps(clean, separators=(",", ":"), sort_keys=True)


def _path(path=None) -> Path:
    return Path(path) if path is not None else STORE_PATH


def _load(path=None) -> dict:
    p = _path(path)
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError, TypeError):
        return {"models": {}}
    if not isinstance(data, dict):
        return {"models": {}}
    models = data.get("models")
    if not isinstance(models, dict):
        data["models"] = {}
    return data


def _save(data: dict, path=None) -> None:
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".speed_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(blob)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _fmt_rate(n: float) -> str:
    if n >= 10:
        return str(int(round(n)))
    return f"{n:.1f}".rstrip("0").rstrip(".") if f"{n:.1f}" != "10.0" else "10"


def _fmt_secs(n: float) -> str:
    if n >= 10:
        return f"{int(round(n))} s"
    if n >= 1:
        return f"{n:.1f} s"
    return f"{n:.2f} s".replace("0.00 s", "0.01 s") if n > 0 else "0 s"


def format_line(write_tok_s, ttft_s) -> str:
    """Plain-language average line, or empty if there is nothing to show."""
    parts = []
    if write_tok_s is not None:
        parts.append(f"Usually {_fmt_rate(float(write_tok_s))} words/s")
    if ttft_s is not None:
        first = f"first word in {_fmt_secs(float(ttft_s))}"
        if parts:
            parts.append(first)
        else:
            parts.append(f"Usually {first}")
    return ", ".join(parts)


def _entry(data: dict, model_id: str, opts) -> dict:
    mid = str(model_id or "").strip()
    key = fingerprint(opts)
    models = data.setdefault("models", {})
    slots = models.setdefault(mid, {})
    slot = slots.get(key)
    if not isinstance(slot, dict):
        slot = {"count": 0, "write_sum": 0.0, "write_n": 0, "ttft_sum": 0.0, "ttft_n": 0}
        slots[key] = slot
    return slot


def _snapshot(slot: dict) -> dict:
    count = int(slot.get("count") or 0)
    write_n = int(slot.get("write_n") or 0)
    ttft_n = int(slot.get("ttft_n") or 0)
    write = (float(slot["write_sum"]) / write_n) if write_n else None
    ttft = (float(slot["ttft_sum"]) / ttft_n) if ttft_n else None
    line = format_line(write, ttft) if count else ""
    return {
        "count": count,
        "write_tok_s": round(write, 3) if write is not None else None,
        "ttft_s": round(ttft, 4) if ttft is not None else None,
        "line": line or None,
    }


def get(model_id: str, opts, path=None) -> dict:
    """Return the stored average for this model and optimization set."""
    if not str(model_id or "").strip():
        return {"count": 0, "write_tok_s": None, "ttft_s": None, "line": None}
    data = _load(path)
    mid = str(model_id).strip()
    key = fingerprint(opts)
    slot = ((data.get("models") or {}).get(mid) or {}).get(key)
    if not isinstance(slot, dict) or not int(slot.get("count") or 0):
        return {"count": 0, "write_tok_s": None, "ttft_s": None, "line": None}
    return _snapshot(slot)


def _finite(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")) or n < 0:
        return None
    return n


def record(model_id: str, opts, *, write_tok_s=None, ttft_s=None, path=None) -> dict:
    """Add one reply's measurements and return the updated average.

    Replies with no usable numbers are ignored and do not change the store.
    """
    mid = str(model_id or "").strip()
    write = _finite(write_tok_s)
    ttft = _finite(ttft_s)
    if not mid or (write is None and ttft is None):
        return get(mid, opts, path=path)
    data = _load(path)
    slot = _entry(data, mid, opts)
    if write is not None:
        slot["write_sum"] = float(slot.get("write_sum") or 0) + write
        slot["write_n"] = int(slot.get("write_n") or 0) + 1
    if ttft is not None:
        slot["ttft_sum"] = float(slot.get("ttft_sum") or 0) + ttft
        slot["ttft_n"] = int(slot.get("ttft_n") or 0) + 1
    slot["count"] = int(slot.get("count") or 0) + 1
    _save(data, path)
    return _snapshot(slot)
