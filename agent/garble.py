"""Detect garbled model replies and plan a safe-settings fix.

A reply is garbled when it is empty, only special markers, or a short
chunk repeated many times. Short real answers like "Hello!" and ordinary
code that happens to repeat a line must not be flagged.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# ChatML / Llama / Gemma turn markers that can leak into a reply.
# Keep in sync with mlx_worker.END_MARKERS and the page strip list.
SPECIAL_MARKERS = (
    "<|im_start|>",
    "<|im_end|>",
    "<|endoftext|>",
    "<|end_of_text|>",
    "<|eot_id|>",
    "<|eom_id|>",
    "<|end|>",
    "<|return|>",
    "<turn|>",
    "<end_of_turn>",
    "<|turn|>",
    "<|turn>",
    "</s>",
    "<eos>",
    "<channel|>",
    "<|channel|>",
    "<|channel>",
    "<|message|>",
)

# Settings we may turn off when Memory compression is already 16.
EXTRAS = (
    ("guess_ahead", "Guess-ahead", ("on", "mtp", "true", "1")),
    ("prompt_lookup", "Prompt lookup", ("on", "adaptive", "true", "1")),
    ("fuse_kernels", "Fused kernels", ("on", "all", "true", "1")),
    ("shared_start", "Shared start", ("on", "true", "1")),
)

SAFE_NOTICE = (
    "This reply came out garbled. Settings are already on the usual safe "
    "values, so nothing else was changed."
)
KV_NOTICE = (
    "This reply came out garbled, so Memory compression was turned back to 16."
)

# Degenerate-loop knobs. "Hello!" is far shorter than this; a 24-token
# "<|im_start|>" loop is well above.
_MIN_REPEATS = 6
_MAX_UNIT = 24
_MIN_LOOP_CHARS = 16
# Banner / rule characters that show up in code and markdown.
_FILLER = set("=-_#*/ \t\n|+.>`'\"")


def strip_special_markers(text: Optional[str]) -> str:
    """Remove known special markers from reply text."""
    if not text:
        return text or ""
    out = text
    for m in SPECIAL_MARKERS:
        if m in out:
            out = out.replace(m, "")
    return out


def is_degenerate_repeat(text: Optional[str]) -> bool:
    """True when almost the whole string is one short chunk repeated many times."""
    s = (text or "").strip()
    if len(s) < _MIN_LOOP_CHARS:
        return False
    max_unit = min(_MAX_UNIT, len(s) // _MIN_REPEATS)
    if max_unit < 1:
        return False
    for unit_len in range(1, max_unit + 1):
        unit = s[:unit_len]
        if not unit.strip():
            continue
        # Whole-string fill with banner characters is code/markdown, not a loop.
        if set(unit) <= _FILLER:
            continue
        count, pos = 0, 0
        while pos + unit_len <= len(s) and s[pos:pos + unit_len] == unit:
            count += 1
            pos += unit_len
        rem = s[pos:]
        if rem and unit.startswith(rem):
            covered = pos + len(rem)
        else:
            covered = pos
        if count >= _MIN_REPEATS and covered >= 0.95 * len(s):
            return True
    return False


def is_garbled(text: Optional[str] = None, *, raw: Optional[str] = None) -> bool:
    """True for empty, marker-only, or degenerate-repeat replies.

    `raw` is the text before display stripping. When only one string is
    given, it is used as both.
    """
    raw_text = raw if raw is not None else (text or "")
    visible = strip_special_markers(text if text is not None else raw_text)
    if not (visible or "").strip():
        return True
    if is_degenerate_repeat(visible) or is_degenerate_repeat(raw_text):
        return True
    return False


def _as_map(settings) -> dict:
    if not isinstance(settings, dict):
        return {}
    out = {}
    for k, v in settings.items():
        if v is None:
            continue
        out[str(k)] = v
    return out


def _kv(settings: dict):
    """Resolved Memory compression value, or None if Auto/default/16."""
    for key in ("kv_bits", "cache_type"):
        if key not in settings:
            continue
        v = settings[key]
        if v in (None, "", "auto", "16", 16, 0, "0", "f16", "F16"):
            return 16
        if v in (8, "8", "q8_0", "q8"):
            return 8
        if v in (4, "4"):
            return 4
    return 16


def _extra_on(settings: dict, key: str, on_values: Iterable[str]) -> bool:
    v = str(settings.get(key, "off") or "off").strip().lower()
    return v in {s.lower() for s in on_values}


def already_safe(settings) -> bool:
    s = _as_map(settings)
    if _kv(s) != 16:
        return False
    for key, _label, on_values in EXTRAS:
        if _extra_on(s, key, on_values):
            return False
    return True


def plan_garble_fix(settings, *, backend: str = "mlx") -> dict:
    """Decide what to change. Does not apply anything.

    If Memory compression is 4 or 8, turn it back to 16 and leave the
    rest alone. If it is already 16, turn off Guess-ahead, Prompt lookup,
    Fused kernels, and Shared start when they are on. If everything is
    already safe, change nothing.
    """
    s = _as_map(settings)
    kv = _kv(s)
    changes = []
    new = dict(s)
    src = (backend or "mlx").lower()
    if kv != 16:
        changes.append(("kv_bits", "16"))
        new["kv_bits"] = "16"
        if src == "gguf":
            new["cache_type"] = "f16"
        message = KV_NOTICE
    else:
        for key, label, on_values in EXTRAS:
            if src == "gguf" and key == "fuse_kernels":
                continue
            if _extra_on(s, key, on_values):
                changes.append((key, "off"))
                new[key] = "off"
        message = _extras_notice(changes) if changes else SAFE_NOTICE
    return {
        "already_safe": not changes,
        "changes": changes,
        "new_settings": new,
        "message": message,
        "backend": src,
    }


def _extras_notice(changes) -> str:
    labels = []
    for key, _val in changes:
        for k, label, _on in EXTRAS:
            if k == key:
                labels.append(label)
                break
    if not labels:
        return SAFE_NOTICE
    if len(labels) == 1:
        return f"This reply came out garbled, so {labels[0]} was turned off."
    if len(labels) == 2:
        return f"This reply came out garbled, so {labels[0]} and {labels[1]} were turned off."
    return (
        "This reply came out garbled, so "
        + ", ".join(labels[:-1])
        + ", and "
        + labels[-1]
        + " were turned off."
    )


def loss_ids(changes) -> list:
    """(name, value) pairs to record as losses — the values that caused the garble.

    `changes` is the planned *new* values; callers should pass the
    *current* bad values instead. See `losses_from_used`.
    """
    return list(changes)


def losses_from_used(settings) -> list:
    """Settings currently in effect that should be recorded as a loss."""
    s = _as_map(settings)
    out = []
    kv = _kv(s)
    if kv in (4, 8):
        out.append(("kv_bits", kv))
    for key, _label, on_values in EXTRAS:
        if _extra_on(s, key, on_values):
            raw = s.get(key)
            out.append((key, raw if raw is not None else "on"))
    return out
