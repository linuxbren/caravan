#!/usr/bin/env python3
"""ROADMAP #13(b): learn best settings from real chats (Day 10).

Start from the Day 9 memory-based guess (or a previously saved winner).
Serve each real chat with the best settings so far, and now and then try a
nearby option for settings that can change live (pipeline chat count,
guess-ahead on/off, shared-prefix cache on/off). Settings that need a reload
(packer layer cut K) are queued and tried on the next load. Time each reply,
normalize for length, and require several samples per option before switching.
Shared-prefix is scored by time-to-first-token on new chats that share a
system prompt (hits vs cold); the one-time store/materialize cost is sunk
before hits count, so a model that never hits (e.g. Day 12 Gemma) stays off.
Save winners per model + hardware (single Mini vs spanned) to
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
    if name == "shared_prefix":
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



# Day 13: shared-prefix is scored by TTFT (faster first token = better), not
# decode tok/s. Higher score wins (same maybe_promote path as other settings).
SHARED_PREFIX_MIN_PROMPT = 512   # tokens; must clear shared_prefix.min_tokens
SHARED_PREFIX_TRIAL_REPLIES = MIN_SAMPLES + 2  # 1 store + MIN_SAMPLES hits


def shared_prefix_score(ttft_s: float) -> float:
    """Inverse TTFT so maybe_promote's higher-is-better logic applies."""
    return 1.0 / max(float(ttft_s), 0.001)


def shared_prefix_eligible(*, prompt_tokens: int, how: str,
                           min_prompt: int = SHARED_PREFIX_MIN_PROMPT) -> bool:
    """New-chat cold or shared-prefix hit/miss with a long enough prompt."""
    if int(prompt_tokens or 0) < int(min_prompt):
        return False
    h = (how or "").lower()
    if h == "cold" or h.startswith("shared-prefix"):
        return True
    return False


def shared_prefix_is_hit(how: str) -> bool:
    h = (how or "").lower()
    return h.startswith("shared-prefix-hit")


def shared_prefix_is_store(how: str, *, enabled: bool, cached_tokens: int = 0) -> bool:
    """Cold path while cache is on = paying the one-time store/materialize cost."""
    if not enabled:
        return False
    if shared_prefix_is_hit(how):
        return False
    h = (how or "").lower()
    return h == "cold" or h.startswith("shared-prefix-miss")


def record_shared_prefix_probe(entry: dict, *, enabled: bool, ttft_s: float,
                               how: str, prompt_tokens: int = 0,
                               cached_tokens: int = 0,
                               min_prompt: int = SHARED_PREFIX_MIN_PROMPT,
                               min_samples: int = MIN_SAMPLES,
                               margin: float = SWITCH_MARGIN) -> dict:
    """Score shared_prefix on/off from one new-chat TTFT sample.

    Hits while on count toward shared_prefix=True. Cold while off counts toward
    False. The one-time store/materialize cold while on is recorded under
    stats['shared_prefix:on_store'] only (does not inflate the on mean), so a
    model that never hits cannot promote on. Promotion still uses maybe_promote
    on the hit vs cold means (higher shared_prefix_score wins).

    Returns {recorded, kind, promotions, keep_reasons, winner}.
    """
    out = {"recorded": False, "kind": None, "promotions": [], "keep_reasons": [],
           "winner": dict(entry.get("winner") or {})}
    if not shared_prefix_eligible(prompt_tokens=prompt_tokens, how=how,
                                  min_prompt=min_prompt):
        return out
    ttft = float(ttft_s or 0.0)
    if ttft <= 0.0:
        return out
    score = shared_prefix_score(ttft)
    winner = entry.setdefault("winner", {})
    if shared_prefix_is_store(how, enabled=enabled, cached_tokens=cached_tokens):
        # One-time cost: track separately; do not sample into on/off means.
        bucket = entry.setdefault("stats", {}).setdefault(
            "shared_prefix:on_store",
            {"n": 0, "sum_ttft": 0.0, "mean_ttft": 0.0, "samples_ttft": []})
        bucket["samples_ttft"] = (bucket.get("samples_ttft") or [])[-19:] + [round(ttft, 3)]
        bucket["n"] = int(bucket.get("n") or 0) + 1
        bucket["sum_ttft"] = float(bucket.get("sum_ttft") or 0.0) + ttft
        bucket["mean_ttft"] = bucket["sum_ttft"] / bucket["n"]
        entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        out["recorded"] = True
        out["kind"] = "store"
        out["winner"] = dict(winner)
        return out

    if enabled and not shared_prefix_is_hit(how):
        # On but neither hit nor store (e.g. short-reuse path) — skip.
        return out

    record_sample(entry, "shared_prefix", bool(enabled), score)
    out["recorded"] = True
    out["kind"] = "hit" if enabled else "cold_off"

    # Amortize: if we have store + hits, require amortized TTFT still beats off.
    # amortized_ttft = (mean_store + n_hits * mean_hit_ttft) / (1 + n_hits)
    # Compare 1/amortized vs off score. Without a store sample yet, fall back to
    # plain maybe_promote on hit vs cold scores.
    incumb = winner.get("shared_prefix", False)
    used = bool(enabled)
    promotions, keep_reasons = [], []

    def hit_ttft_mean():
        # score = 1/ttft ⇒ ttft = 1/score
        m = mean_of(entry, "shared_prefix", True)
        return (1.0 / m) if m and m > 0 else None

    def amortized_on_score():
        store = (entry.get("stats") or {}).get("shared_prefix:on_store") or {}
        n_store = int(store.get("n") or 0)
        mean_store = float(store.get("mean_ttft") or 0.0) if n_store else None
        n_hits = samples_of(entry, "shared_prefix", True)
        hit_t = hit_ttft_mean()
        if n_hits < min_samples or hit_t is None:
            return None, n_hits
        if mean_store is None or n_store <= 0:
            # No store observed in this process; use hit mean alone.
            return mean_of(entry, "shared_prefix", True), n_hits
        amort_ttft = (mean_store + n_hits * hit_t) / (1.0 + n_hits)
        return shared_prefix_score(amort_ttft), n_hits

    def try_promote(challenger, incumbent):
        # Fair: both on (hits) and off (cold) need min_samples before a switch.
        # Prevents a lucky early hit streak from flipping on before cold is measured.
        if challenger is True:
            m_c, n_c = amortized_on_score()
            n_c = n_c or 0
        else:
            n_c = samples_of(entry, "shared_prefix", challenger)
            m_c = mean_of(entry, "shared_prefix", challenger)
        if incumbent is True:
            m_i, n_i = amortized_on_score()
            n_i = n_i or 0
        else:
            n_i = samples_of(entry, "shared_prefix", incumbent)
            m_i = mean_of(entry, "shared_prefix", incumbent)
        if n_c < min_samples or n_i < min_samples:
            return False, (f"keep shared_prefix={'on' if incumbent else 'off'}: need "
                           f"{min_samples} TTFT samples each (have off="
                           f"{samples_of(entry, 'shared_prefix', False)} on_hits="
                           f"{samples_of(entry, 'shared_prefix', True)})")
        if m_c is None or m_i is None:
            return False, f"keep shared_prefix={'on' if incumbent else 'off'}: missing means"
        if m_c >= m_i * margin:
            return True, (f"switch shared_prefix {'on' if incumbent else 'off'}→"
                          f"{'on' if challenger else 'off'}: score {m_c:.3f} beats "
                          f"{m_i:.3f} over {n_c} vs {n_i} chats "
                          f"(TTFT-based; store amortized when present)")
        return False, (f"keep shared_prefix={'on' if incumbent else 'off'}: "
                       f"score {m_i:.3f} still ahead of challenger {m_c:.3f}")

    if used != incumb:
        ok, reason = try_promote(used, incumb)
        if ok:
            winner["shared_prefix"] = used
            promotions.append(("shared_prefix", used, reason))
        else:
            keep_reasons.append(reason)
    else:
        for nb in neighbors("shared_prefix", used):
            ok, reason = try_promote(nb, used)
            if ok:
                winner["shared_prefix"] = nb
                promotions.append(("shared_prefix", nb, reason))
                break
        else:
            if samples_of(entry, "shared_prefix", used) >= min_samples:
                m = mean_of(entry, "shared_prefix", used)
                if m is not None and int(entry.get("reply_n") or 0) % EXPLORE_EVERY == 0:
                    keep_reasons.append(
                        f"keep shared_prefix={'on' if used else 'off'}: best so far "
                        f"at score {m:.3f} over {samples_of(entry, 'shared_prefix', used)} chats")

    out["promotions"] = promotions
    out["keep_reasons"] = keep_reasons
    out["winner"] = dict(winner)
    return out


LIVE_SETTINGS = ("shared_prefix", "pipeline_chats", "guess_ahead")
RELOAD_SETTINGS = ("packer_layers",)


def resolve_startup(*, model_dir, spanned: bool,
                    day9_packer_layers: Optional[int],
                    day9_pipeline_chats: Optional[int],
                    day9_guess_ahead: Optional[bool],
                    explicit: dict,
                    store: Optional[dict] = None,
                    path: Optional[Path] = None,
                    n_layers: Optional[int] = None,
                    day9_shared_prefix: Optional[bool] = False) -> dict:
    """Pick startup settings. Flags in `explicit` always win.

    Returns dict with keys: packer_layers, pipeline_chats, guess_ahead,
    shared_prefix, reasons (list of plain strings), store, entry, key.
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
    sp = False if day9_shared_prefix is None else bool(day9_shared_prefix)

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
    if "shared_prefix" in winner:
        sp = bool(winner["shared_prefix"])
        reasons.append(
            f"learned shared-prefix: {'on' if sp else 'off'} (saved winner for {hw})")

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
    if "shared_prefix" in explicit:
        sp = bool(explicit["shared_prefix"])
        reasons.append(f"flag shared-prefix: {'on' if sp else 'off'}")

    if not reasons:
        if packer is not None:
            reasons.append(f"auto split: packer_layers={packer} (Day 9 memory guess; no saved winner yet)")
        if pipe is not None:
            reasons.append(f"auto pipeline: chats={pipe} (Day 9 memory guess; no saved winner yet)")
        reasons.append(
            f"auto shared-prefix: {'on' if sp else 'off'} "
            f"(default off until learned; no saved winner yet)")

    # Seed winner with current if empty so second load has something.
    w = entry.setdefault("winner", {})
    if packer is not None and "packer_layers" not in w and "packer_layers" not in explicit:
        w["packer_layers"] = int(packer)
    if pipe is not None and "pipeline_chats" not in w and "pipeline_chats" not in explicit:
        w["pipeline_chats"] = int(pipe)
    if guess is not None and "guess_ahead" not in w and "guess_ahead" not in explicit:
        w["guess_ahead"] = bool(guess)
    if "shared_prefix" not in w and "shared_prefix" not in explicit:
        w["shared_prefix"] = bool(sp)

    return {
        "packer_layers": packer,
        "pipeline_chats": pipe,
        "guess_ahead": guess,
        "shared_prefix": sp,
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
    # Shared-prefix (Day 13): once the default-off side has enough cold TTFT
    # samples, try on promptly (do not wait for pipeline/guess to monopolize).
    due = (reply_n % explore_every == 0) or (reply_n % slow_recheck_every == 0)
    sp_ready_to_try_on = (
        "shared_prefix" not in explicit
        and current.get("shared_prefix") is False
        and samples_of(entry, "shared_prefix", False) >= MIN_SAMPLES
        and samples_of(entry, "shared_prefix", True) < MIN_SAMPLES
    )
    if not due and not sp_ready_to_try_on:
        return None

    # Prefer a live setting whose challenger still needs samples.
    # For pipeline_chats, wait until the incumbent has enough concurrent /
    # serial probes before wandering off — otherwise we never finish scoring
    # the Day 9 starting guess. When only sp_unproven triggered entry (not
    # due), restrict to shared_prefix so other knobs do not steal early chats.
    live_names = LIVE_SETTINGS if due else ("shared_prefix",)  # early path: shared_prefix only
    for name in live_names:
        if name in explicit:
            continue
        if name not in current or current[name] is None:
            continue
        cur = current[name]
        if name == "pipeline_chats" and samples_of(entry, name, cur) < MIN_SAMPLES:
            continue
        if name == "shared_prefix" and samples_of(entry, name, cur) < MIN_SAMPLES:
            continue
        for nb in neighbors(name, cur, n_layers=n_layers):
            if samples_of(entry, name, nb) < MIN_SAMPLES:
                if name == "pipeline_chats":
                    trial_n = MIN_SAMPLES * 2
                elif name == "shared_prefix":
                    trial_n = SHARED_PREFIX_TRIAL_REPLIES
                else:
                    trial_n = MIN_SAMPLES
                return {
                    "name": name,
                    "value": nb,
                    "reason": (f"try {name}={nb}: exploring near {name}={cur} "
                               f"(have {samples_of(entry, name, nb)}/{MIN_SAMPLES} samples)"),
                    "trial_replies": trial_n,
                }

    # Early shared-prefix-only pass found nothing to try.
    if not due:
        return None

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
        if name == "pipeline_chats":
            trial_n = MIN_SAMPLES * 2
        elif name == "shared_prefix":
            trial_n = SHARED_PREFIX_TRIAL_REPLIES
        else:
            trial_n = MIN_SAMPLES
        return {
            "name": name,
            "value": nb,
            "reason": f"re-check {name}={nb} against current {name}={cur}",
            "trial_replies": trial_n,
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
            "shared_prefix": winner.get("shared_prefix", settings_used.get("shared_prefix")),
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



# ---- Day 15: reload trials for every Optimizations option ------------------
# Self-tuning covers ALL options in the web Optimizations panel (design
# decision, docs/ROADMAP.md). The three below only change when the model is
# loaded, so trials are queued in pending_reload, applied on the next load
# (Load / Apply & restart / Deep optimize auto-reload), scored over
# RELOAD_TRIAL_REPLIES replies, then kept (promoted) or rolled back.
RELOAD_TRIO = ("kv_bits", "fuse_kernels", "keepalive")
RELOAD_DEFAULTS = {"kv_bits": 16, "fuse_kernels": "off", "keepalive": True}
RELOAD_VALUES = {"kv_bits": (16, 8, 4), "fuse_kernels": ("off", "on"),
                 "keepalive": (True, False)}
RELOAD_TRIAL_REPLIES = MIN_SAMPLES
RELOAD_LABEL = {"kv_bits": "memory compression", "fuse_kernels": "fused kernels",
                "keepalive": "GPU keep-warm"}


def reload_value_label(name: str, value: Any) -> str:
    if name == "kv_bits":
        return f"{int(value)}-bit"
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def reload_neighbors(name: str, value: Any, entry: Optional[dict] = None) -> list:
    bad = set(blocked_values(entry, name))
    return [v for v in RELOAD_VALUES.get(name, ()) if v != value and v not in bad]


# Models whose attention can't run on a quantized KV cache. mlx's quantized
# SDPA refuses attention sinks ("Quantized SDPA does not support attention
# sinks"), and gpt-oss uses sinks, so kv_bits 8/4 crash the load there.
NO_KV_QUANT_TYPES = ("gpt_oss",)


def kv_quant_supported(model_dir) -> bool:
    """False when the model's config says it can't take kv_bits 8/4."""
    try:
        cfg = json.loads((Path(model_dir) / "config.json").read_text())
    except (OSError, ValueError, TypeError):
        return True
    if str(cfg.get("model_type") or "") in NO_KV_QUANT_TYPES:
        return False
    return not any("sink" in str(k).lower() for k in cfg)


def blocked_values(entry: Optional[dict], name: str) -> list:
    """Reload values self-tuning must never try for this model (entry['reload_blocked'])."""
    vals = ((entry or {}).get("reload_blocked") or {}).get(name) or []
    return [_norm_reload(name, v) for v in vals]


def block_value(entry: dict, name: str, value: Any, reason: str = "") -> None:
    """Record a reload value as rejected (e.g. the load crashed with it)."""
    b = entry.setdefault("reload_blocked", {})
    v = _norm_reload(name, value)
    cur = [_norm_reload(name, x) for x in b.get(name) or []]
    if v not in cur:
        cur.append(v)
    b[name] = cur
    if reason:
        entry.setdefault("reload_blocked_why", {})[f"{name}={v}"] = reason[:200]
    pend = entry.get("pending_reload") or {}
    if pend.get(name) is not None and _norm_reload(name, pend[name]) == v:
        pend.pop(name, None)


def _norm_reload(name: str, value: Any) -> Any:
    if name == "kv_bits":
        return int(value or 16)
    if name == "fuse_kernels":
        return "off" if str(value or "off").lower() in ("off", "0", "false", "no") else "on"
    if name == "keepalive":
        return bool(value)
    return value


def plan_reload(entry: dict, auto_names) -> dict:
    """At load time: pick values for auto reload options. Mutates entry.

    Uses the saved winner (or default), then one queued pending trial.
    Returns {values: {name: value}, trial: dict|None, reasons: [str]}.
    """
    auto = [n for n in RELOAD_TRIO if n in set(auto_names or ())]
    winner = entry.setdefault("winner", {})
    pending = entry.setdefault("pending_reload", {})
    values, reasons, trial = {}, [], None
    for n in auto:
        if n not in winner:
            winner[n] = RELOAD_DEFAULTS[n]
        values[n] = _norm_reload(n, winner[n])
    for n in auto:
        bad = blocked_values(entry, n)
        if values[n] in bad:
            values[n] = _norm_reload(n, RELOAD_DEFAULTS[n])
            winner[n] = values[n]
        if pending.get(n) is not None and _norm_reload(n, pending[n]) in bad:
            reasons.append(f"skip {RELOAD_LABEL[n]} {reload_value_label(n, pending.pop(n))} "
                           f"(this model can't use it)")
    for n in auto:
        if pending.get(n) is not None:
            v = _norm_reload(n, pending.pop(n))
            if v != values[n]:
                trial = {"name": n, "value": v, "incumbent": values[n],
                         "remaining": RELOAD_TRIAL_REPLIES}
                values[n] = v
                reasons.append(f"try {RELOAD_LABEL[n]} {reload_value_label(n, v)} "
                               f"(queued; winner is {reload_value_label(n, trial['incumbent'])})")
            break  # one reload trial at a time
    for n in auto:
        if not trial or trial["name"] != n:
            reasons.append(f"learned {RELOAD_LABEL[n]}: {reload_value_label(n, values[n])}")
    entry["reload_trial"] = trial
    return {"values": values, "trial": trial, "reasons": reasons}


def observe_reload(entry: dict, *, settings_used: dict, norm_tps: float,
                   auto_names) -> dict:
    """After each reply: score auto reload options, finish/queue trials."""
    auto = [n for n in RELOAD_TRIO if n in set(auto_names or ())]
    out = {"promotions": [], "rolled_back": [], "queued": None, "reasons": []}
    if not auto:
        return out
    used = {n: _norm_reload(n, settings_used.get(n)) for n in auto if n in settings_used}
    for n, v in used.items():
        record_sample(entry, n, v, norm_tps)
    winner = entry.setdefault("winner", {})
    trial = entry.get("reload_trial")
    if trial and trial.get("name") in used and used[trial["name"]] == trial["value"]:
        trial["remaining"] = int(trial.get("remaining") or 0) - 1
        if trial["remaining"] <= 0:
            n = trial["name"]
            ok, reason = maybe_promote(entry, n, trial["value"], trial["incumbent"])
            if ok:
                winner[n] = trial["value"]
                out["promotions"].append((n, trial["value"], reason))
            else:
                winner[n] = trial["incumbent"]
                out["rolled_back"].append((n, trial["incumbent"], reason))
            out["reasons"].append(reason)
            entry["reload_trial"] = None
            trial = None
    pending = entry.setdefault("pending_reload", {})
    if not trial and not any(pending.get(n) is not None for n in RELOAD_TRIO):
        for n in auto:
            inc = _norm_reload(n, winner.get(n, used.get(n, RELOAD_DEFAULTS[n])))
            if samples_of(entry, n, inc) < MIN_SAMPLES:
                continue
            nbs = sorted(reload_neighbors(n, inc, entry), key=lambda v: samples_of(entry, n, v))
            if nbs and samples_of(entry, n, nbs[0]) < MIN_SAMPLES:
                pending[n] = nbs[0]
                out["queued"] = {"name": n, "value": nbs[0]}
                out["reasons"].append(
                    f"queue {RELOAD_LABEL[n]} {reload_value_label(n, nbs[0])} for next load "
                    f"(winner {reload_value_label(n, inc)} has {samples_of(entry, n, inc)} replies)")
                break
    return out


def reload_status(entry: Optional[dict], running: Optional[dict], auto_names) -> dict:
    """Plain status for the UI: running trial and any reload that is wanted."""
    entry = entry or {}
    running = running or {}
    auto = [n for n in RELOAD_TRIO if n in set(auto_names or ())]
    winner = entry.get("winner") or {}
    pending = entry.get("pending_reload") or {}
    trial = entry.get("reload_trial")
    changes = []
    for n in auto:
        if running.get(n) is None:
            continue
        cur = _norm_reload(n, running[n])
        if pending.get(n) is not None:
            want, why = _norm_reload(n, pending[n]), "try"
        elif trial and trial.get("name") == n:
            continue
        else:
            want, why = _norm_reload(n, winner.get(n, cur)), "back to winner"
        if want != cur:
            changes.append({"name": n, "label": RELOAD_LABEL[n],
                            "from": reload_value_label(n, cur),
                            "to": reload_value_label(n, want), "why": why})
    return {
        "trial": ({"name": trial["name"], "label": RELOAD_LABEL[trial["name"]],
                   "value": reload_value_label(trial["name"], trial["value"]),
                   "remaining": int(trial.get("remaining") or 0)} if trial else None),
        "reload_wanted": changes,
    }


# ---- Day 15: Deep / Quick optimize coverage ------------------------------
LIVE_VALUES = {"guess_ahead": (True, False), "shared_prefix": (False, True),
               "pipeline_chats": (1, 2)}


def coverage(entry: Optional[dict], *, mode: str = "deep", pinned=()) -> dict:
    """Samples each option value has vs needs. done when all reach MIN_SAMPLES."""
    entry = entry or {}
    pinned = set(pinned or ())
    vals = dict(LIVE_VALUES)
    if mode == "deep":
        vals.update(RELOAD_VALUES)
    items, need = [], 0
    for n, vs in vals.items():
        if n in pinned:
            continue
        for v in vs:
            if n in RELOAD_VALUES and v in blocked_values(entry, n):
                continue
            have = samples_of(entry, n, v)
            need += max(0, MIN_SAMPLES - have)
            items.append({"name": n, "value": reload_value_label(n, v),
                          "have": have, "need": MIN_SAMPLES})
    return {"items": items, "missing": need, "done": need == 0}
