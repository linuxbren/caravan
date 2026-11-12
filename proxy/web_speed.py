"""Per-model, per-optimization-set reply speed averages for the chat page.

Stored in ~/.caravan/speed_averages.json so the numbers describe these Macs
and this model setup, not a single browser. The page shows one quiet line
such as "Average · Read 165 tok at 200 tok/s · Write 10 tok at 20.7 tok/s
· first token 0.34s · total 0.78s" when at least one reply has been
recorded for the current model and the current optimizations. The wording,
units, and rounding match the stats under each reply, with a leading
Average label. Fields with no data yet are left out. Changing an
optimization starts a separate average.
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
    if path is not None:
        return Path(path)
    return Path(os.environ.get(
        "CARAVAN_SPEED_AVERAGES",
        str(Path.home() / ".caravan" / "speed_averages.json"),
    )).expanduser()


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


def _ok_num(v) -> bool:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return False
    return n == n and n not in (float("inf"), float("-inf"))


def _fmt_fixed(n, digits: int) -> str:
    """Same rounding as the page's fmt() helper: Number.toFixed(digits)."""
    return f"{float(n):.{int(digits)}f}"


def _seg(label: str, n, rate, digits: int):
    """One Read or Write clause, matching the stats under each reply."""
    has_n = _ok_num(n)
    has_r = _ok_num(rate)
    if not has_n and not has_r:
        return None
    t = label
    if has_n:
        t += f" {int(round(float(n)))} tok"
    if has_r:
        t += f"{' at' if has_n else ''} {_fmt_fixed(rate, digits)} tok/s"
    return t


def format_reply_stats(
    write_tok_s=None,
    ttft_s=None,
    *,
    prompt_tokens=None,
    read_tok_s=None,
    completion_tokens=None,
    total_s=None,
) -> str:
    """Wording and rounding of the stats under each reply, or empty."""
    parts = [
        _seg("Read", prompt_tokens, read_tok_s, 0),
        _seg("Write", completion_tokens, write_tok_s, 1),
        f"first token {_fmt_fixed(ttft_s, 2)}s" if _ok_num(ttft_s) else None,
        f"total {_fmt_fixed(total_s, 2)}s" if _ok_num(total_s) else None,
    ]
    return " · ".join(p for p in parts if p)


def format_line(
    write_tok_s=None,
    ttft_s=None,
    *,
    prompt_tokens=None,
    read_tok_s=None,
    completion_tokens=None,
    total_s=None,
) -> str:
    """Average line for under the chat input, or empty if there is nothing to show."""
    body = format_reply_stats(
        write_tok_s, ttft_s,
        prompt_tokens=prompt_tokens,
        read_tok_s=read_tok_s,
        completion_tokens=completion_tokens,
        total_s=total_s,
    )
    return f"Average · {body}" if body else ""


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


def _mean(slot: dict, sum_key: str, n_key: str, ndigits: int):
    n = int(slot.get(n_key) or 0)
    if not n:
        return None
    try:
        v = float(slot.get(sum_key) or 0) / n
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return round(v, ndigits)


def _empty_view() -> dict:
    return {
        "count": 0,
        "write_tok_s": None,
        "ttft_s": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "read_tok_s": None,
        "total_s": None,
        "line": None,
    }


def _snapshot(slot: dict) -> dict:
    count = int(slot.get("count") or 0)
    write = _mean(slot, "write_sum", "write_n", 3)
    ttft = _mean(slot, "ttft_sum", "ttft_n", 4)
    prompt = _mean(slot, "prompt_sum", "prompt_n", 3)
    completion = _mean(slot, "completion_sum", "completion_n", 3)
    read = _mean(slot, "read_sum", "read_n", 3)
    total = _mean(slot, "total_sum", "total_n", 4)
    line = format_line(
        write, ttft,
        prompt_tokens=prompt,
        read_tok_s=read,
        completion_tokens=completion,
        total_s=total,
    ) if count else ""
    return {
        "count": count,
        "write_tok_s": write,
        "ttft_s": ttft,
        "prompt_tokens": int(round(prompt)) if prompt is not None else None,
        "completion_tokens": int(round(completion)) if completion is not None else None,
        "read_tok_s": read,
        "total_s": total,
        "line": line or None,
    }


def get(model_id: str, opts, path=None) -> dict:
    """Return the stored average for this model and optimization set."""
    if not str(model_id or "").strip():
        return _empty_view()
    data = _load(path)
    mid = str(model_id).strip()
    key = fingerprint(opts)
    slot = ((data.get("models") or {}).get(mid) or {}).get(key)
    if not isinstance(slot, dict) or not int(slot.get("count") or 0):
        return _empty_view()
    return _snapshot(slot)


def _finite(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")) or n < 0:
        return None
    return n


_ACCUM = (
    ("write_tok_s", "write_sum", "write_n"),
    ("ttft_s", "ttft_sum", "ttft_n"),
    ("prompt_tokens", "prompt_sum", "prompt_n"),
    ("completion_tokens", "completion_sum", "completion_n"),
    ("read_tok_s", "read_sum", "read_n"),
    ("total_s", "total_sum", "total_n"),
)


def record(
    model_id: str,
    opts,
    *,
    write_tok_s=None,
    ttft_s=None,
    prompt_tokens=None,
    completion_tokens=None,
    read_tok_s=None,
    total_s=None,
    path=None,
) -> dict:
    """Add one reply's measurements and return the updated average.

    Replies with no usable numbers are ignored and do not change the store.
    Fields present on older store entries (write and first-token only)
    still produce a line; missing fields are left out.
    """
    mid = str(model_id or "").strip()
    values = {
        "write_tok_s": _finite(write_tok_s),
        "ttft_s": _finite(ttft_s),
        "prompt_tokens": _finite(prompt_tokens),
        "completion_tokens": _finite(completion_tokens),
        "read_tok_s": _finite(read_tok_s),
        "total_s": _finite(total_s),
    }
    if not mid or all(v is None for v in values.values()):
        return get(mid, opts, path=path)
    data = _load(path)
    slot = _entry(data, mid, opts)
    for key, sum_key, n_key in _ACCUM:
        v = values[key]
        if v is not None:
            slot[sum_key] = float(slot.get(sum_key) or 0) + v
            slot[n_key] = int(slot.get(n_key) or 0) + 1
    slot["count"] = int(slot.get("count") or 0) + 1
    _save(data, path)
    return _snapshot(slot)


def format_specs(write_tok_s=None, ttft_s=None) -> str:
    """One side of the before/after line, e.g. '31 words/s, first word in 2.1 s'."""
    parts = []
    if write_tok_s is not None:
        parts.append(f"{_fmt_rate(float(write_tok_s))} words/s")
    if ttft_s is not None:
        parts.append(f"first word in {_fmt_secs(float(ttft_s))}")
    return ", ".join(parts)


def format_tuning_line(before=None, after=None) -> str:
    """'Before: 31 words/s, first word in 2.1 s. After: 42 words/s, first word in 1.2 s.'"""
    before = before or {}
    after = after or {}
    b = format_specs(before.get("write_tok_s"), before.get("ttft_s"))
    a = format_specs(after.get("write_tok_s"), after.get("ttft_s"))
    bits = []
    if b:
        bits.append(f"Before: {b}.")
    if a:
        bits.append(f"After: {a}.")
    return " ".join(bits)


def _specs(write_tok_s=None, ttft_s=None) -> dict:
    write = _finite(write_tok_s)
    ttft = _finite(ttft_s)
    return {
        "write_tok_s": round(write, 3) if write is not None else None,
        "ttft_s": round(ttft, 4) if ttft is not None else None,
    }


def _has_specs(s) -> bool:
    return bool(s) and (s.get("write_tok_s") is not None or s.get("ttft_s") is not None)


def _tuning_slot(data: dict, model_id: str) -> dict:
    mid = str(model_id or "").strip()
    tun = data.setdefault("tuning", {})
    if not isinstance(tun, dict):
        tun = {}
        data["tuning"] = tun
    slot = tun.get(mid)
    if not isinstance(slot, dict):
        slot = {}
        tun[mid] = slot
    return slot


def _tuning_view(slot: dict) -> dict:
    before = slot.get("before") if isinstance(slot.get("before"), dict) else {}
    after = slot.get("after") if isinstance(slot.get("after"), dict) else {}
    line = format_tuning_line(before, after) if _has_specs(before) and _has_specs(after) else None
    return {
        "before": dict(before) if before else None,
        "after": dict(after) if after else None,
        "line": line,
        "source": slot.get("source"),
    }


def get_tuning(model_id: str, path=None) -> dict:
    """Persisted before/after for one completed tuning run of this model.

    Empty (line is None) when no run has finished yet.
    """
    mid = str(model_id or "").strip()
    empty = {"before": None, "after": None, "line": None, "source": None}
    if not mid:
        return empty
    data = _load(path)
    slot = ((data.get("tuning") or {}).get(mid) or {})
    if not isinstance(slot, dict):
        return empty
    return _tuning_view(slot)


def record_tuning(model_id: str, *, before, after, source="optimize_now", path=None) -> dict:
    """Save a finished run's baseline and winner speeds. Per model, last run wins."""
    mid = str(model_id or "").strip()
    b = _specs((before or {}).get("write_tok_s"), (before or {}).get("ttft_s"))
    a = _specs((after or {}).get("write_tok_s"), (after or {}).get("ttft_s"))
    if not mid or not _has_specs(b) or not _has_specs(a):
        return get_tuning(mid, path=path)
    import time
    data = _load(path)
    slot = _tuning_slot(data, mid)
    slot.clear()
    slot["before"] = b
    slot["after"] = a
    slot["source"] = source
    slot["updated"] = time.time()
    _save(data, path)
    return _tuning_view(slot)


def snapshot_pending_before(model_id: str, specs, path=None) -> dict:
    """Remember the pre-tune average so a later finish can use it as Before."""
    mid = str(model_id or "").strip()
    b = _specs((specs or {}).get("write_tok_s"), (specs or {}).get("ttft_s"))
    if not mid or not _has_specs(b):
        return get_tuning(mid, path=path)
    data = _load(path)
    slot = _tuning_slot(data, mid)
    # Do not overwrite a finished optimize_now result's before until a new finish.
    slot["pending_before"] = b
    _save(data, path)
    return _tuning_view(slot)


def _accum_specs(bucket: dict, write, ttft) -> dict:
    bucket = dict(bucket or {})
    w, t = _finite(write), _finite(ttft)
    if w is not None:
        bucket["write_sum"] = float(bucket.get("write_sum") or 0) + w
        bucket["write_n"] = int(bucket.get("write_n") or 0) + 1
    if t is not None:
        bucket["ttft_sum"] = float(bucket.get("ttft_sum") or 0) + t
        bucket["ttft_n"] = int(bucket.get("ttft_n") or 0) + 1
    return bucket


def _bucket_specs(bucket: dict) -> dict:
    bucket = bucket or {}
    wn, tn = int(bucket.get("write_n") or 0), int(bucket.get("ttft_n") or 0)
    write = (float(bucket["write_sum"]) / wn) if wn else None
    ttft = (float(bucket["ttft_sum"]) / tn) if tn else None
    return _specs(write, ttft)


def observe_tuning(model_id: str, *, write_tok_s=None, ttft_s=None,
                   has_winners=False, settling=False, path=None) -> dict:
    """Fold a real-chat reply into a self-tuning before/after record.

    Before winners exist, replies build the baseline. After winners are
    chosen and any trial has settled, the next replies become After, and
    the pair is frozen. A finished Optimize now result is left alone.
    """
    mid = str(model_id or "").strip()
    if not mid or (_finite(write_tok_s) is None and _finite(ttft_s) is None):
        return get_tuning(mid, path=path)
    data = _load(path)
    slot = _tuning_slot(data, mid)
    # A completed Optimize now (or an already-frozen self-tune) stays.
    if _has_specs(slot.get("before")) and _has_specs(slot.get("after")):
        return _tuning_view(slot)
    if not has_winners:
        slot["pending_before"] = _accum_specs(slot.get("pending_before"), write_tok_s, ttft_s)
        _save(data, path)
        return _tuning_view(slot)
    # Winners exist. Freeze the baseline if we have one.
    if not _has_specs(slot.get("before")):
        frozen = slot.get("pending_before")
        if isinstance(frozen, dict) and ("write_n" in frozen or "ttft_n" in frozen):
            slot["before"] = _bucket_specs(frozen)
        elif isinstance(frozen, dict):
            slot["before"] = _specs(frozen.get("write_tok_s"), frozen.get("ttft_s"))
    if not _has_specs(slot.get("before")):
        # No baseline to compare against: do not show a one-sided result.
        _save(data, path)
        return _tuning_view(slot)
    if settling:
        _save(data, path)
        return _tuning_view(slot)
    slot["pending_after"] = _accum_specs(slot.get("pending_after"), write_tok_s, ttft_s)
    after = _bucket_specs(slot["pending_after"])
    after_n = int((slot["pending_after"] or {}).get("write_n") or 0) + int(
        (slot["pending_after"] or {}).get("ttft_n") or 0)
    # One solid reply after winners is enough to close the run.
    if after_n and _has_specs(after):
        import time
        slot["after"] = after
        slot["source"] = "self_tune"
        slot["updated"] = time.time()
    _save(data, path)
    return _tuning_view(slot)
