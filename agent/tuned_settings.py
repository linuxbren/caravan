#!/usr/bin/env python3
"""ROADMAP #13(b): learn best settings from real chats (Day 10).

Start from the Day 9 memory-based guess (or a previously saved winner).
Serve each real chat with the best settings so far, and now and then try a
nearby option for settings that can change live (pipeline chat count,
guess-ahead on/off). Settings that need a reload (packer layer cut K) are
queued and tried on the next load. Time each reply, normalize for length,
and require several samples per option before switching. Save winners per
model + hardware (single Mini vs spanned) to
~/.caravan/mlx/tuned-settings.json. Flags still win. One plain log reason
whenever a setting changes or is kept.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path("~/.caravan/mlx/tuned-settings.json").expanduser()
VERSION = 1
MIN_SAMPLES = 3          # replies per option before we trust a mean
EXPLORE_EVERY = 4        # try a neighbor on every Nth observed reply
SWITCH_MARGIN = 1.03     # challenger must beat incumbent by 3%
SLOW_RECHECK_EVERY = 24  # keep re-checking the winner slowly


def model_stem(model_dir) -> str:
    return Path(model_dir).expanduser().resolve().name


def hardware_label(*, spanned: bool) -> str:
    return "spanned" if spanned else "single"


def entry_key(model_dir, *, spanned: bool) -> str:
    return f"{model_stem(model_dir)}:{hardware_label(spanned=spanned)}"


def load_store(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else DEFAULT_PATH
    try:
        raw = json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": VERSION, "models": {}}
    if not isinstance(raw, dict):
        return {"version": VERSION, "models": {}}
    raw.setdefault("version", VERSION)
    raw.setdefault("models", {})
    if not isinstance(raw["models"], dict):
        raw["models"] = {}
    return raw


def save_store(store: dict, path: Optional[Path] = None) -> None:
    p = Path(path) if path else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = dict(store)
    payload["version"] = VERSION
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(p)


def ensure_entry(store: dict, key: str, *, model: str, hardware: str) -> dict:
    models = store.setdefault("models", {})
    e = models.get(key)
    if not isinstance(e, dict):
        e = {
            "model": model,
            "hardware": hardware,
            "winner": {},
            "stats": {},
            "pending_reload": {},
            "reply_n": 0,
            "updated_at": None,
        }
        models[key] = e
    e.setdefault("model", model)
    e.setdefault("hardware", hardware)
    e.setdefault("winner", {})
    e.setdefault("stats", {})
    e.setdefault("pending_reload", {})
    e.setdefault("reply_n", 0)
    return e


def normalized_tps(*, completion_tokens: int, total_s: float,
                   prefill_s: float = 0.0, prompt_tokens: int = 0) -> float:
    """Decode-rate style tok/s, floored so short replies don't explode."""
    n = max(int(completion_tokens), 0)
    decode = max(float(total_s) - max(float(prefill_s), 0.0), 0.001)
    # Mild length dampener: very short replies are noisier.
    damp = min(1.0, math.sqrt(max(n, 1) / 32.0))
    raw = n / decode
    return raw * (0.7 + 0.3 * damp)


def option_id(name: str, value: Any) -> str:
    if isinstance(value, bool):
        v = "on" if value else "off"
    else:
        v = str(value)
    return f"{name}:{v}"


def neighbors(name: str, value: Any, *, n_layers: Optional[int] = None) -> list:
    """Nearby options for exploration. Empty if none."""
    if name == "pipeline_chats":
        cur = int(value)
        out = []
        for n in (1, 2):
            if n != cur:
                out.append(n)
        return out
    if name == "guess_ahead":
        return [not bool(value)]
    if name == "packer_layers":
        cur = int(value)
        n = int(n_layers or 0)
        cands = []
        for d in (-2, -1, 1, 2):
            k = cur + d
            if n >= 2:
                k = max(1, min(n - 1, k))
            if k != cur and k not in cands:
                cands.append(k)
        return cands
    return []


def record_sample(entry: dict, name: str, value: Any, norm_tps: float) -> dict:
    """Append one timed sample under stats[option_id]. Returns the bucket."""
    oid = option_id(name, value)
    stats = entry.setdefault("stats", {})
    bucket = stats.setdefault(oid, {"n": 0, "sum": 0.0, "mean": 0.0, "samples": []})
    tps = float(norm_tps)
    bucket["samples"] = (bucket.get("samples") or [])[-19:] + [round(tps, 3)]
    bucket["n"] = int(bucket.get("n") or 0) + 1
    bucket["sum"] = float(bucket.get("sum") or 0.0) + tps
    bucket["mean"] = bucket["sum"] / bucket["n"]
    entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return bucket


def mean_of(entry: dict, name: str, value: Any) -> Optional[float]:
    bucket = (entry.get("stats") or {}).get(option_id(name, value))
    if not bucket or int(bucket.get("n") or 0) <= 0:
        return None
    return float(bucket["mean"])


def samples_of(entry: dict, name: str, value: Any) -> int:
    bucket = (entry.get("stats") or {}).get(option_id(name, value))
    return int((bucket or {}).get("n") or 0)


def maybe_promote(entry: dict, name: str, challenger: Any, incumbent: Any,
                  *, min_samples: int = MIN_SAMPLES,
                  margin: float = SWITCH_MARGIN) -> tuple[bool, str]:
    """If challenger has enough samples and beats incumbent, promote it."""
    n_c = samples_of(entry, name, challenger)
    n_i = samples_of(entry, name, incumbent)
    m_c = mean_of(entry, name, challenger)
    m_i = mean_of(entry, name, incumbent)
    if n_c < min_samples:
        return False, (f"keep {name}={incumbent}: challenger {name}={challenger} "
                       f"only has {n_c}/{min_samples} samples")
    if m_c is None:
        return False, f"keep {name}={incumbent}: no mean for challenger"
    if m_i is None or n_i < min_samples:
        # Incumbent unproven; adopt challenger once it has enough samples.
        return True, (f"switch {name} {incumbent}→{challenger}: challenger "
                      f"mean {m_c:.2f} tok/s over {n_c} replies; incumbent unproven")
    if m_c >= m_i * margin:
        return True, (f"switch {name} {incumbent}→{challenger}: {m_c:.2f} beats "
                      f"{m_i:.2f} tok/s over {n_c} vs {n_i} replies")
    return False, (f"keep {name}={incumbent}: {m_i:.2f} still ahead of "
                   f"challenger {m_c:.2f} tok/s")


LIVE_SETTINGS = ("pipeline_chats", "guess_ahead")
RELOAD_SETTINGS = ("packer_layers",)


def resolve_startup(*, model_dir, spanned: bool,
                    day9_packer_layers: Optional[int],
                    day9_pipeline_chats: Optional[int],
                    day9_guess_ahead: Optional[bool],
                    explicit: dict,
                    store: Optional[dict] = None,
                    path: Optional[Path] = None,
                    n_layers: Optional[int] = None) -> dict:
    """Pick startup settings. Flags in `explicit` always win.

    Returns dict with keys: packer_layers, pipeline_chats, guess_ahead,
    reasons (list of plain strings), store, entry, key, exploring (None).
    """
    st = store if store is not None else load_store(path)
    hw = hardware_label(spanned=spanned)
    key = entry_key(model_dir, spanned=spanned)
    entry = ensure_entry(st, key, model=model_stem(model_dir), hardware=hw)
    winner = dict(entry.get("winner") or {})
    pending = dict(entry.get("pending_reload") or {})
    reasons = []

    # Base = Day 9 guess, then overlay saved winner, then pending reload trial.
    packer = day9_packer_layers
    pipe = day9_pipeline_chats
    guess = day9_guess_ahead

    if "packer_layers" in winner and packer is not None:
        packer = int(winner["packer_layers"])
        reasons.append(f"learned split: packer_layers={packer} (saved winner for {hw})")
    if "pipeline_chats" in winner and pipe is not None:
        pipe = int(winner["pipeline_chats"])
        reasons.append(f"learned pipeline: chats={pipe} (saved winner for {hw})")
    if "guess_ahead" in winner and guess is not None:
        guess = bool(winner["guess_ahead"])
        on = "on" if guess else "off"
        reasons.append(f"learned guess-ahead: {on} (saved winner for {hw})")

    # Pending reload trials override the winner once, then clear.
    if pending.get("packer_layers") is not None and "packer_layers" not in explicit:
        trial_k = int(pending["packer_layers"])
        if n_layers and not (1 <= trial_k <= n_layers - 1):
            reasons.append(f"skip pending packer_layers={trial_k}: out of range")
        else:
            packer = trial_k
            reasons.append(f"try split: packer_layers={packer} (queued from last run)")
        entry["pending_reload"] = {k: v for k, v in pending.items() if k != "packer_layers"}

    # Explicit flags win last.
    if "packer_layers" in explicit:
        packer = int(explicit["packer_layers"])
        reasons.append(f"flag split: packer_layers={packer}")
    if "pipeline_chats" in explicit:
        pipe = int(explicit["pipeline_chats"])
        reasons.append(f"flag pipeline: chats={pipe}")
    if "guess_ahead" in explicit:
        guess = bool(explicit["guess_ahead"])
        reasons.append(f"flag guess-ahead: {'on' if guess else 'off'}")

    if not reasons:
        if packer is not None:
            reasons.append(f"auto split: packer_layers={packer} (Day 9 memory guess; no saved winner yet)")
        if pipe is not None:
            reasons.append(f"auto pipeline: chats={pipe} (Day 9 memory guess; no saved winner yet)")

    # Seed winner with current if empty so second load has something.
    w = entry.setdefault("winner", {})
    if packer is not None and "packer_layers" not in w and "packer_layers" not in explicit:
        w["packer_layers"] = int(packer)
    if pipe is not None and "pipeline_chats" not in w and "pipeline_chats" not in explicit:
        w["pipeline_chats"] = int(pipe)
    if guess is not None and "guess_ahead" not in w and "guess_ahead" not in explicit:
        w["guess_ahead"] = bool(guess)

    return {
        "packer_layers": packer,
        "pipeline_chats": pipe,
        "guess_ahead": guess,
        "reasons": reasons,
        "store": st,
        "entry": entry,
        "key": key,
        "hardware": hw,
    }


def pick_exploration(entry: dict, current: dict, *,
                     n_layers: Optional[int] = None,
                     explicit: Optional[dict] = None,
                     explore_every: int = EXPLORE_EVERY,
                     slow_recheck_every: int = SLOW_RECHECK_EVERY) -> Optional[dict]:
    """Maybe return {name, value, reason} for a live setting to try next.

    Returns None to keep current settings. Never explores an explicit flag.
    """
    explicit = explicit or {}
    reply_n = int(entry.get("reply_n") or 0) + 1
    # Explore on a cadence; also occasionally re-check even after a winner.
    due = (reply_n % explore_every == 0) or (reply_n % slow_recheck_every == 0)
    if not due:
        return None

    # Prefer a live setting whose challenger still needs samples.
    # For pipeline_chats, wait until the incumbent has enough concurrent /
    # serial probes before wandering off — otherwise we never finish scoring
    # the Day 9 starting guess.
    for name in LIVE_SETTINGS:
        if name in explicit:
            continue
        if name not in current or current[name] is None:
            continue
        cur = current[name]
        if name == "pipeline_chats" and samples_of(entry, name, cur) < MIN_SAMPLES:
            continue
        for nb in neighbors(name, cur, n_layers=n_layers):
            if samples_of(entry, name, nb) < MIN_SAMPLES:
                return {
                    "name": name,
                    "value": nb,
                    "reason": (f"try {name}={nb}: exploring near {name}={cur} "
                               f"(have {samples_of(entry, name, nb)}/{MIN_SAMPLES} samples)"),
                    "trial_replies": (MIN_SAMPLES * 2 if name == "pipeline_chats" else MIN_SAMPLES),
                }

    # All neighbors sampled: pick the best-looking under-tested or next neighbor
    # for a slow re-check against the winner.
    for name in LIVE_SETTINGS:
        if name in explicit:
            continue
        if name not in current or current[name] is None:
            continue
        cur = current[name]
        if name == "pipeline_chats" and samples_of(entry, name, cur) < MIN_SAMPLES:
            continue
        nbs = neighbors(name, cur, n_layers=n_layers)
        if not nbs:
            continue
        # Prefer neighbor with fewer samples, else first.
        nbs.sort(key=lambda v: samples_of(entry, name, v))
        nb = nbs[0]
        return {
            "name": name,
            "value": nb,
            "reason": f"re-check {name}={nb} against current {name}={cur}",
            "trial_replies": (MIN_SAMPLES * 2 if name == "pipeline_chats" else MIN_SAMPLES),
        }

    # Queue a packer_layers trial for next reload if not explicit and we have room.
    if "packer_layers" not in explicit and current.get("packer_layers") is not None:
        cur_k = int(current["packer_layers"])
        pending = entry.setdefault("pending_reload", {})
        if pending.get("packer_layers") is None:
            nbs = neighbors("packer_layers", cur_k, n_layers=n_layers)
            # Prefer a neighbor that lacks samples.
            nbs.sort(key=lambda v: samples_of(entry, "packer_layers", v))
            if nbs and samples_of(entry, "packer_layers", nbs[0]) < MIN_SAMPLES:
                pending["packer_layers"] = int(nbs[0])
                return {
                    "name": "packer_layers",
                    "value": int(nbs[0]),
                    "reason": (f"queue split packer_layers={nbs[0]} for next load "
                               f"(near current {cur_k})"),
                    "deferred": True,
                }
    return None


def observe_reply(entry: dict, *, settings_used: dict,
                  completion_tokens: int, total_s: float,
                  prefill_s: float = 0.0, prompt_tokens: int = 0,
                  explicit: Optional[dict] = None,
                  n_layers: Optional[int] = None,
                  record_names: Optional[list] = None) -> dict:
    """Record one reply under settings in force; maybe promote.

    `record_names` limits which settings get a sample from this reply.
    Default records guess_ahead + packer_layers only — NOT pipeline_chats —
    because single-chat decode tok/s cannot tell N=1 from N=2. Pipeline
    width is scored via record_pipeline_probe() under concurrent load.

    Returns {norm_tps, promotions: [(name, new, reason)], keep_reasons: [...],
             explore: optional dict from pick_exploration after increment}.
    """
    explicit = explicit or {}
    norm = normalized_tps(completion_tokens=completion_tokens, total_s=total_s,
                          prefill_s=prefill_s, prompt_tokens=prompt_tokens)
    entry["reply_n"] = int(entry.get("reply_n") or 0) + 1
    if record_names is None:
        record_names = ["guess_ahead", "packer_layers"]
    for name in record_names:
        if name in settings_used and settings_used[name] is not None and name not in explicit:
            record_sample(entry, name, settings_used[name], norm)

    promotions = []
    keep_reasons = []
    winner = entry.setdefault("winner", {})
    # pipeline_chats is scored only via record_pipeline_probe (concurrent /
    # serial bursts). Single-reply promote would always see 0 samples for the
    # neighbor and spam keep-reasons without teaching us anything.
    for name in ("guess_ahead", "packer_layers"):
        if name in explicit:
            continue
        if name not in settings_used or settings_used[name] is None:
            continue
        used = settings_used[name]
        incumb = winner.get(name, used)
        # Compare used against incumbent when they differ and used has samples.
        if used != incumb:
            ok, reason = maybe_promote(entry, name, used, incumb)
            if ok:
                winner[name] = used
                promotions.append((name, used, reason))
            else:
                keep_reasons.append(reason)
        else:
            # Same as winner: check whether any neighbor should steal it.
            for nb in neighbors(name, used, n_layers=n_layers):
                ok, reason = maybe_promote(entry, name, nb, used)
                if ok:
                    winner[name] = nb
                    promotions.append((name, nb, reason))
                    break
            else:
                if samples_of(entry, name, used) >= MIN_SAMPLES and entry["reply_n"] % EXPLORE_EVERY == 0:
                    m = mean_of(entry, name, used)
                    if m is not None:
                        keep_reasons.append(
                            f"keep {name}={used}: best so far at {m:.2f} tok/s "
                            f"over {samples_of(entry, name, used)} replies")

    explore = pick_exploration(
        entry,
        {
            "pipeline_chats": winner.get("pipeline_chats", settings_used.get("pipeline_chats")),
            "guess_ahead": winner.get("guess_ahead", settings_used.get("guess_ahead")),
            "packer_layers": winner.get("packer_layers", settings_used.get("packer_layers")),
        },
        n_layers=n_layers,
        explicit=explicit,
    )
    return {
        "norm_tps": norm,
        "promotions": promotions,
        "keep_reasons": keep_reasons,
        "explore": explore,
        "winner": dict(winner),
    }


def record_pipeline_probe(entry: dict, *, n_chats: int, aggregate_tps: float,
                          explicit: Optional[dict] = None,
                          min_samples: int = MIN_SAMPLES,
                          margin: float = SWITCH_MARGIN) -> dict:
    """Score pipeline_chats under a concurrent probe (aggregate tok/s).

    Both the incumbent and the challenger need min_samples before a switch;
    a Day 9 / saved winner is not displaced by one lucky probe.
    Returns {promotions, keep_reasons, winner}.
    """
    explicit = explicit or {}
    if "pipeline_chats" in explicit:
        return {"promotions": [], "keep_reasons": ["flag pins pipeline_chats"], "winner": dict(entry.get("winner") or {})}
    n = max(1, int(n_chats))
    record_sample(entry, "pipeline_chats", n, float(aggregate_tps))
    winner = entry.setdefault("winner", {})
    incumb = int(winner.get("pipeline_chats", n))
    promotions, keep_reasons = [], []

    def fair_promote(challenger, incumbent):
        n_c = samples_of(entry, "pipeline_chats", challenger)
        n_i = samples_of(entry, "pipeline_chats", incumbent)
        m_c = mean_of(entry, "pipeline_chats", challenger)
        m_i = mean_of(entry, "pipeline_chats", incumbent)
        if n_c < min_samples or n_i < min_samples:
            return False, (f"keep pipeline_chats={incumbent}: need {min_samples} concurrent "
                           f"probes each (have {n_i} vs challenger {challenger}={n_c})")
        if m_c is None or m_i is None:
            return False, f"keep pipeline_chats={incumbent}: missing means"
        if m_c >= m_i * margin:
            return True, (f"switch pipeline_chats {incumbent}→{challenger}: "
                          f"concurrent {m_c:.2f} beats {m_i:.2f} tok/s "
                          f"over {n_c} vs {n_i} probes")
        return False, (f"keep pipeline_chats={incumbent}: concurrent {m_i:.2f} "
                       f"still ahead of {m_c:.2f} tok/s")

    if n != incumb:
        ok, reason = fair_promote(n, incumb)
        if ok:
            winner["pipeline_chats"] = n
            promotions.append(("pipeline_chats", n, reason))
        else:
            keep_reasons.append(reason)
    else:
        for nb in neighbors("pipeline_chats", n):
            ok, reason = fair_promote(nb, n)
            if ok:
                winner["pipeline_chats"] = nb
                promotions.append(("pipeline_chats", nb, reason))
                break
        else:
            m = mean_of(entry, "pipeline_chats", n)
            if m is not None and samples_of(entry, "pipeline_chats", n) >= min_samples:
                keep_reasons.append(
                    f"keep pipeline_chats={n}: best concurrent probe so far at "
                    f"{m:.2f} tok/s over {samples_of(entry, 'pipeline_chats', n)} probes")
    return {"promotions": promotions, "keep_reasons": keep_reasons, "winner": dict(winner)}

