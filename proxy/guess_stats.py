"""Day 27: how many guessed words were kept (Prompt lookup / Guess-ahead).

Pure functions, no I/O. One shape for both engines so the reply line,
the bench and the docs say the same thing:

    {"guessed": int | None,   # words proposed by Prompt lookup / a helper
     "kept": int,             # proposed words the main model agreed with
     "kept_pct": float | None,  # kept / guessed (the hit rate)
     "reply_pct": float | None, # kept / words in the reply
     "words": int | None}       # words in the reply

GGUF (llama.cpp) reports ``timings.draft_n`` and ``timings.draft_n_accepted``
when it guessed at least once in a reply. MLX reports ``speculate`` with
``from_draft`` (kept) and, from Day 27, ``proposed``/``accepted``. A reply
with no guesses has no readout; nothing here invents a number.
"""
from __future__ import annotations

import math


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if not math.isfinite(float(v)) or v < 0:
        return None
    return v


def _pct(a, b):
    if a is None or not b:
        return None
    return round(100.0 * float(a) / float(b), 1)


def readout(guessed=None, kept=None, words=None):
    """Normalized readout, or None when nothing was guessed or kept."""
    g, k, w = _num(guessed), _num(kept), _num(words)
    if k is None and g is None:
        return None
    if g is not None and g <= 0 and not k:
        return None
    k = int(k or 0)
    g = int(g) if g is not None else None
    w = int(w) if w is not None else None
    if g is not None and k > g:
        k = g
    return {
        "guessed": g,
        "kept": k,
        "kept_pct": _pct(k, g) if g else None,
        "reply_pct": _pct(k, w) if w else None,
        "words": w,
    }


def from_llama_timings(timings):
    """Readout from a llama-server ``timings`` object, or None."""
    t = timings if isinstance(timings, dict) else {}
    if "draft_n" not in t and "draft_n_accepted" not in t:
        return None
    return readout(t.get("draft_n"), t.get("draft_n_accepted"), t.get("predicted_n"))


def from_speculate(spec, words=None):
    """Readout from a worker ``speculate`` dict (MLX or the GGUF mapping)."""
    s = spec if isinstance(spec, dict) else {}
    if not s:
        return None
    kept = s.get("accepted")
    if kept is None:
        kept = s.get("from_draft")
    guessed = s.get("proposed")
    if words is None:
        words = s.get("n_gen")
    return readout(guessed, kept, words)


def label(r) -> str:
    """Short wording for the line under a reply, or empty."""
    if not isinstance(r, dict):
        return ""
    if r.get("kept_pct") is not None:
        return f"guesses kept {_fmt_pct(r['kept_pct'])}"
    if r.get("reply_pct") is not None:
        return f"{_fmt_pct(r['reply_pct'])} of words guessed"
    return ""


def _fmt_pct(p) -> str:
    p = float(p)
    return f"{p:.0f}%"


def combine(items):
    """Sum several replies' readouts (for a bench row), or None."""
    g_sum, k_sum, w_sum = 0, 0, 0
    have_g = have_w = False
    n = 0
    for r in items or []:
        if not isinstance(r, dict):
            continue
        n += 1
        k_sum += int(r.get("kept") or 0)
        if r.get("guessed") is not None:
            g_sum += int(r["guessed"])
            have_g = True
        if r.get("words") is not None:
            w_sum += int(r["words"])
            have_w = True
    if not n:
        return None
    out = readout(g_sum if have_g else None, k_sum, w_sum if have_w else None)
    if out is not None:
        out["replies"] = n
    return out
