"""Day 33 (v0.9.15): prefer a shipped guesser, else the helper.

Pure rules, no MLX import. A "shipped guesser" is a guesser made for this
exact model: today that is a native MTP head installed beside an MLX
model (``caravan-mtp/``, Day 17; checked by ``native_mtp.validate_pair``).
The fallback is Caravan's paired Guess-ahead helper (``guessers.json`` for
MLX, ``helper_offer.HELPERS`` for GGUF), and on GGUF only, any other
smaller same-family file found on this Mac.

MLX order (first match wins):

1. Guess-ahead Off: no guesser.
2. Settings Guess-ahead = Native MTP (test): the shipped head, pinned.
3. An explicit ``--split-draft-model``: that helper.
4. Auto or On with an eligible shipped head (one Mac, 16-bit chat memory,
   Prompt lookup off, head matches this model):
   - an Auto-tune reload leaves the head to Auto-tune's own Native MTP
     trial, so the other arm is the helper;
   - a saved Auto-tune verdict decides first (helper won: helper);
   - then the cached first-load check for this head (lost: helper);
   - otherwise the shipped head, and the worker runs the first-load
     quality + speed check once. If it loses, the head is unloaded and
     the helper is set up instead.
5. Otherwise the paired helper (if any), as before.

GGUF has no shipped guesser in Caravan yet (llama.cpp MTP was never
measured here), so the order is: the helper Settings or Auto-tune saved,
then Caravan's paired helper, then another smaller same-family file.
"""
from __future__ import annotations

from typing import Optional
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

NATIVE = "native_mtp"
HELPER = "helper"
NONE = "none"

# reason code -> the "why" shown in the chip hint and the load notes.
# Literal T() calls so the locale checks can see every key.
WHY = {
    "off": lambda **kw: T("agent.guesser_choice.guess_ahead_is_off"),
    "native_mtp_test": lambda **kw: T("agent.guesser_choice.native_mtp_test_picked_in_settings"),
    "explicit_helper": lambda **kw: T("agent.guesser_choice.using_the_helper_you_named"),
    "shipped_first": lambda **kw: T("agent.guesser_choice.using_the_built_in_guesser"),
    "shipped_won_autotune": lambda **kw: T("agent.guesser_choice.built_in_guesser_won_autotune"),
    "shipped_won_first_load": lambda **kw: T("agent.guesser_choice.built_in_guesser_won_first_load"),
    "helper_won_autotune": lambda **kw: T("agent.guesser_choice.helper_won_autotune"),
    "helper_won_first_load": lambda **kw: T("agent.guesser_choice.helper_won_first_load"),
    "shipped_load_failed": lambda **kw: T("agent.guesser_choice.built_in_guesser_did_not_load"),
    "shipped_needs_one_mac": lambda **kw: T("agent.guesser_choice.built_in_guesser_needs_one_mac"),
    "shipped_needs_16bit": lambda **kw: T("agent.guesser_choice.built_in_guesser_needs_16_bit"),
    "shipped_not_with_lookup": lambda **kw: T("agent.guesser_choice.built_in_guesser_not_with_lookup"),
    "shipped_mismatch": lambda **kw: T("agent.guesser_choice.built_in_guesser_does_not_match"),
    "autotune_trial": lambda **kw: T("agent.guesser_choice.autotune_tries_built_in_separately"),
    "paired_helper": lambda **kw: T("agent.guesser_choice.no_built_in_guesser_paired_helper"),
    "no_guesser": lambda **kw: T("agent.guesser_choice.no_built_in_guesser_or_helper"),
    "gguf_paired_helper": lambda **kw: T("agent.guesser_choice.gguf_using_paired_helper", name=kw.get("name", "")),
    "gguf_found_helper": lambda **kw: T("agent.guesser_choice.gguf_using_found_helper", name=kw.get("name", "")),
}

SOURCES = ("off", "explicit", "shipped", "paired", "found", "none")


def why(reason: str, **kw) -> str:
    fn = WHY.get(reason)
    if fn is None:
        return str(reason or "")
    try:
        return fn(**kw)
    except Exception:  # noqa: BLE001  (never fail a load over a label)
        return str(reason)


def choice(kind: str, source: str, reason: str, *, gate: bool = False, **kw) -> dict:
    return {"kind": kind, "source": source, "reason": reason,
            "why": why(reason, **kw), "gate": bool(gate)}


def head_eligible(*, head_present: bool, head_error: Optional[str], split: bool,
                  kv_bits, prompt_lookup: bool) -> Optional[str]:
    """None when an installed shipped head can be used automatically,
    else the reason code it cannot (head missing returns "missing")."""
    if not head_present:
        return "missing"
    if split:
        return "shipped_needs_one_mac"
    try:
        kv = int(kv_bits or 16)
    except (TypeError, ValueError):
        kv = 16
    if kv != 16:
        return "shipped_needs_16bit"
    if prompt_lookup:
        return "shipped_not_with_lookup"
    if head_error:
        return "shipped_mismatch"
    return None


def mlx_choice(*, off: bool = False, native_mtp_flag: bool = False,
               explicit_draft: bool = False, head_present: bool = False,
               head_error: Optional[str] = None, split: bool = False,
               kv_bits=None, prompt_lookup: bool = False,
               sweep_paused: bool = False, autotune_verdict=None,
               first_load: Optional[dict] = None) -> dict:
    """Which guesser an MLX worker should set up, and why.

    autotune_verdict: the saved Auto-tune winner for ``native_mtp`` on this
    model and hardware (True, False, or None when never measured).
    first_load: the cached first-load result for this model + head, or None.
    """
    if off:
        return choice(NONE, "off", "off")
    if native_mtp_flag:
        return choice(NATIVE, "explicit", "native_mtp_test")
    if explicit_draft:
        return choice(HELPER, "explicit", "explicit_helper")
    blocked = head_eligible(head_present=head_present, head_error=head_error,
                            split=split, kv_bits=kv_bits, prompt_lookup=prompt_lookup)
    if blocked == "missing":
        return choice(HELPER, "paired", "paired_helper")
    if blocked:
        return choice(HELPER, "paired", blocked)
    if sweep_paused:
        return choice(HELPER, "paired", "autotune_trial")
    if autotune_verdict is False:
        return choice(HELPER, "paired", "helper_won_autotune")
    if autotune_verdict is True:
        return choice(NATIVE, "shipped", "shipped_won_autotune")
    if isinstance(first_load, dict):
        if first_load.get("keep"):
            return choice(NATIVE, "shipped", "shipped_won_first_load")
        return choice(HELPER, "paired", "helper_won_first_load")
    return choice(NATIVE, "shipped", "shipped_first", gate=True)


def helper_outcome(base: dict, *, loaded: bool) -> dict:
    """Finish a helper choice once the worker knows whether one loaded.

    A helper choice whose helper is missing, declined, does not fit, or
    has no pairing becomes "no guesser" (the reason that the shipped head
    was passed over is kept in ``passed_over``)."""
    out = dict(base or {})
    if out.get("kind") != HELPER or loaded:
        return out
    if out.get("source") == "explicit":
        return out
    passed = out.get("reason")
    out = choice(NONE, "none", "no_guesser")
    if passed and passed != "paired_helper":
        out["passed_over"] = passed
        out["passed_over_why"] = why(passed)
    return out


def gguf_source(draft_path: Optional[str], *, main_name: str = "") -> Optional[dict]:
    """Where a GGUF helper came from: Caravan's paired helper (the one
    ``helper_offer.HELPERS`` names for this model) or another smaller
    same-family file found on this Mac. None when there is no helper."""
    if not draft_path:
        return None
    from pathlib import Path
    name = Path(str(draft_path)).name
    label = name[:-5] if name.lower().endswith(".gguf") else name
    if is_paired_gguf(name, main_name):
        return choice(HELPER, "paired", "gguf_paired_helper", name=label)
    return choice(HELPER, "found", "gguf_found_helper", name=label)


def is_paired_gguf(helper_name: str, main_name: str) -> bool:
    """True when helper_name is the helper Caravan pairs with main_name."""
    try:
        import helper_offer as HO
        h = HO.match_gguf(main_name) if main_name else None
    except Exception:  # noqa: BLE001
        return False
    return bool(h and str(h.get("gguf_file") or "").lower() == str(helper_name or "").lower())
