"""GGUF Optimize now runner (Day 18 item 6, step 2).

One llama-server option at a time (gguf_split.gguf_schedule): measure the
incumbent and the challenger with the same prompts after a reload each, keep
the challenger only if it beats the incumbent by MARGIN (3 %, same as MLX),
otherwise record it as a loser so it is not retried. Results live in
~/.caravan/gguf-tuned.json keyed by GGUF file + Mini count, and the web
launcher reads `best_tune()` so the next load uses the winner.

Everything that touches a Mini (reload, chat) is injected, so this module is
unit-tested offline and never runs on import.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

import gguf_split as G

import caravan_prompts as P

MARGIN = 0.03
STORE = Path("~/.caravan/gguf-tuned.json").expanduser()
# Five short prompts shared with caravan bench (the original pair first).
# measure_http_specs also adds one ~2k-token long prompt when it fits.
BENCH_PROMPTS = P.SHORT_PROMPTS


def entry_key(model_path, n_minis: int) -> str:
    return f"{Path(str(model_path)).name}|{int(n_minis)}mini"


def load_store(path: Optional[Path] = None) -> dict:
    p = Path(path or STORE)
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_store(store: dict, path: Optional[Path] = None) -> None:
    p = Path(path or STORE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=1, sort_keys=True))
    tmp.replace(p)


def entry(store: dict, key: str) -> dict:
    e = store.setdefault(key, {})
    e.setdefault("best", {})
    e.setdefault("losses", [])
    e.setdefault("trials", [])
    return e


def best_tune(model_path, n_minis: int, path: Optional[Path] = None) -> dict:
    """Saved winner for llama_args(tune=...); {} when nothing learned. Values
    outside the allowed knobs are dropped so a bad file can't break a load."""
    best = (load_store(path).get(entry_key(model_path, n_minis)) or {}).get("best") or {}
    out = {}
    if best.get("flash_attn") in ("on", "off"):
        out["flash_attn"] = best["flash_attn"]
    try:
        if int(best.get("ubatch") or 0) in G.GGUF_UBATCH:
            out["ubatch"] = int(best["ubatch"])
    except (TypeError, ValueError):
        pass
    ct = best.get("cache_type")
    if ct in G.GGUF_KV_TYPES:
        out["cache_type"] = ct
    # Day 28 tuning fix: Prompt lookup and Guess-ahead winners used to be
    # dropped here, so a kept win was lost on the next load, restart or
    # update. Guess-ahead On comes back only with a helper file that is
    # still on disk (the saved one, or the same family's helper found
    # again); otherwise it falls back cleanly to Off.
    if best.get("prompt_lookup") in ("on", "off"):
        out["prompt_lookup"] = best["prompt_lookup"]
    ga = best.get("guess_ahead")
    if ga == "on":
        draft = helper_on_disk(best.get("draft_path"), model_path)
        if draft:
            out["guess_ahead"] = "on"
            out["draft_path"] = draft
        else:
            out["guess_ahead"] = "off"
    elif ga == "off":
        out["guess_ahead"] = "off"
    return out


def helper_on_disk(draft_path, model_path=None):
    """The saved helper file if it still exists, else the same family's
    helper found next to the models, else None. Never downloads."""
    try:
        d = G._existing_draft_path(draft_path)
    except Exception:  # noqa: BLE001
        d = None
    if d:
        return d
    if model_path:
        try:
            found = G.find_gguf_draft(model_path)
            return (found or {}).get("path") or None
        except Exception:  # noqa: BLE001
            return None
    return None


def record_helper_failure(model_path, n_minis: int, reason: str = "",
                          path: Optional[Path] = None) -> None:
    """The helper could not run with this model on these Macs (for example
    out of GPU memory). Auto stops trying it until a fresh Auto-tune."""
    store = load_store(path)
    e = entry(store, entry_key(model_path, n_minis))
    e["best"]["guess_ahead"] = "off"
    e["best"].pop("draft_path", None)
    if "guess_ahead=on" not in e["losses"]:
        e["losses"].append("guess_ahead=on")
    e["helper_failed"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": str(reason)[:300]}
    save_store(store, path)


def _median(values):
    xs = [float(v) for v in values]
    if not xs:
        return None
    xs.sort()
    n = len(xs)
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def specs_from_response(data: dict) -> dict:
    """write_tok_s, read_tok_s, ttft_s from a llama-server chat response."""
    timings = (data or {}).get("timings") or {}
    usage = G.usage_from_timings((data or {}).get("usage"), timings) or {}
    cv = usage.get("caravan") or {}
    out = {}
    for key, fallback in (
        ("write_tok_s", "predicted_per_second"),
        ("read_tok_s", "prompt_per_second"),
    ):
        v = cv.get(key)
        if v is None:
            v = timings.get(fallback)
        if isinstance(v, (int, float)) and v >= 0:
            out[key] = float(v)
    ttft = cv.get("ttft_s")
    if ttft is None and timings.get("prompt_ms") is not None:
        ttft = float(timings["prompt_ms"]) / 1000.0
    if isinstance(ttft, (int, float)) and ttft >= 0:
        out["ttft_s"] = float(ttft)
    return out


def as_specs(measure) -> dict:
    """A measure() return is either a write-speed float or a specs dict."""
    if isinstance(measure, dict):
        out = {k: float(v) for k, v in measure.items()
               if k in ("write_tok_s", "read_tok_s", "long_read_tok_s",
                        "ttft_s", "total_s", "short_write_tok_s",
                        "short_total_s", "edit_write_tok_s")
               and isinstance(v, (int, float))}
        if measure.get("garbled"):
            out["garbled"] = True
        return out
    try:
        return {"write_tok_s": float(measure)}
    except (TypeError, ValueError):
        return {}


def combined_score(specs: dict) -> float:
    """Higher is better. Geometric mean of write, long-prompt read, and 1/total.

    Long-prompt read is preferred (falls back to overall read) so a setting
    that hurts reading is not picked, even if it writes a little faster.
    First-token time is included when total is not available, so older
    saved scores still compare fairly.
    """
    parts = []
    s = specs or {}
    w = s.get("write_tok_s")
    r = s.get("long_read_tok_s") or s.get("read_tok_s")
    total = s.get("total_s")
    t = s.get("ttft_s")
    if w and w > 0:
        parts.append(float(w))
    if r and r > 0:
        parts.append(float(r))
    if total and total > 0:
        parts.append(1.0 / float(total))
    elif t and t > 0:
        parts.append(1.0 / float(t))
    if not parts:
        return 0.0
    prod = 1.0
    for p in parts:
        prod *= p
    return prod ** (1.0 / len(parts))


def beats(challenger, incumbent, margin: float = MARGIN) -> bool:
    return combined_score(as_specs(challenger)) > combined_score(as_specs(incumbent)) * (1 + margin)


# Day 28 tuning fix: Guess-ahead and Prompt lookup change how fast the
# reply is written, not how fast a prompt is read. The combined score
# above also counted long-prompt read speed, which a helper lowers a
# little (it reads the prompt too), so a +9% writing win scored +2% and
# was thrown away. These two are judged on the reply instead: writing
# speed and total reply time on the chat prompts, with long-prompt read
# only as a guard. A code-edit win also counts when chats are not slower.
SPEC_KNOBS = ("guess_ahead", "prompt_lookup")
LONG_READ_GUARD = 0.15   # reject when long-prompt read drops more than 15%
EDIT_GAIN = 0.10         # code edits at least 10% faster ...
CHAT_TOLERANCE = 0.02    # ... while chats are at most 2% slower (noise)


def chat_score(specs: dict) -> float:
    """Geometric mean of chat writing speed and 1 / chat reply time."""
    s = specs or {}
    w = s.get("short_write_tok_s") or s.get("write_tok_s")
    t = s.get("short_total_s") or s.get("total_s")
    parts = []
    if w and w > 0:
        parts.append(float(w))
    if t and t > 0:
        parts.append(1.0 / float(t))
    if not parts:
        return 0.0
    prod = 1.0
    for p in parts:
        prod *= p
    return prod ** (1.0 / len(parts))


def spec_verdict(challenger, incumbent, margin: float = MARGIN) -> dict:
    """{"won": bool, "why": str} for a Guess-ahead / Prompt lookup trial."""
    ch, inc = as_specs(challenger), as_specs(incumbent)
    lr_c, lr_i = ch.get("long_read_tok_s"), inc.get("long_read_tok_s")
    if lr_c and lr_i and lr_c < lr_i * (1 - LONG_READ_GUARD):
        return {"won": False, "why": f"long-prompt read {lr_c:.0f} vs {lr_i:.0f} tok/s (guard)"}
    cs_c, cs_i = chat_score(ch), chat_score(inc)
    if cs_i <= 0 or cs_c <= 0:
        return {"won": False, "why": "no chat measurement"}
    if cs_c > cs_i * (1 + margin):
        return {"won": True, "why": f"chats {100 * (cs_c / cs_i - 1):+.0f}%"}
    ed_c, ed_i = ch.get("edit_write_tok_s"), inc.get("edit_write_tok_s")
    if ed_c and ed_i and ed_c >= ed_i * (1 + EDIT_GAIN) and cs_c >= cs_i * (1 - CHAT_TOLERANCE):
        return {"won": True, "why": f"code edits {100 * (ed_c / ed_i - 1):+.0f}%, chats {100 * (cs_c / cs_i - 1):+.0f}%"}
    return {"won": False, "why": f"chats {100 * (cs_c / cs_i - 1):+.0f}%"}


def trial_won(name: str, challenger, incumbent, margin: float = MARGIN) -> bool:
    if name in SPEC_KNOBS:
        return bool(spec_verdict(challenger, incumbent, margin)["won"])
    return beats(challenger, incumbent, margin)


def measure_http_specs(port: int, *, prompts=None, max_tokens: int = 192,
                       urlopen=None, timeout: float = 300.0,
                       chat_window=None, prompt_kinds=None,
                       on_prompt=None) -> dict:
    """Median write, read, first-token, and total over the Auto-tune prompts.

    Default is the five short prompts plus one ~2k-token long prompt when
    it fits the chat window. `long_read_tok_s` is the median read speed
    of the long prompt(s) only. `on_prompt(index, total, kind)` is called
    just before each prompt (index is 1-based within that kind).
    """
    import urllib.request
    urlopen = urlopen or urllib.request.urlopen
    kinds = list(prompt_kinds or [])
    if prompts is None:
        prompts, kinds, _note = P.autotune_prompt_list(chat_window)
    prompts = list(prompts)
    if len(kinds) < len(prompts):
        kinds = kinds + ["short"] * (len(prompts) - len(kinds))
    samples = []
    n_short = sum(1 for k in kinds if k == "short")
    short_i = 0
    for i, p in enumerate(prompts):
        kind = kinds[i] if i < len(kinds) else "short"
        if kind in ("long", "edit"):
            if on_prompt:
                on_prompt(1, 1, kind)
        else:
            short_i += 1
            if on_prompt:
                on_prompt(short_i, n_short or len(prompts), "short")
        body = json.dumps({"messages": [{"role": "user", "content": p}],
                           "max_tokens": int(max_tokens), "temperature": 0,
                           "seed": 1, "stream": False}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{int(port)}/v1/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
        except Exception as exc:
            # Keep the HTTP body for the log; the wrapper turns it into a
            # plain page sentence.
            try:
                from urllib.error import HTTPError
                import web_tune_errors
                if isinstance(exc, HTTPError):
                    web_tune_errors.http_body(exc)
            except Exception:
                pass
            raise
        dt = time.time() - t0
        specs = specs_from_response(d)
        if "total_s" not in specs and dt > 0:
            specs["total_s"] = dt
        usage = (d or {}).get("usage") or {}
        for k in ("prompt_tokens", "completion_tokens"):
            if k not in specs and isinstance(usage.get(k), (int, float)):
                specs[k] = usage[k]
        if "write_tok_s" not in specs:
            n = ((d.get("usage") or {}).get("completion_tokens")) or 0
            if dt > 0 and n:
                specs["write_tok_s"] = n / dt
        content = ""
        try:
            for ch in (d.get("choices") or []):
                msg = ch.get("message") or {}
                if isinstance(msg.get("content"), str):
                    content += msg["content"]
            from garble import is_garbled
            if is_garbled(content):
                specs["garbled"] = True
        except Exception:
            pass
        samples.append(specs)
    out = {}
    # Code-edit replies are reported on their own (edit_write_tok_s) so the
    # overall numbers stay comparable with runs that had no edit prompts.
    plain = [s for s, k in zip(samples, kinds) if k != "edit"] or samples
    for key in ("write_tok_s", "read_tok_s", "ttft_s", "total_s",
                "prompt_tokens", "completion_tokens"):
        med = _median(s[key] for s in plain if key in s)
        if med is not None:
            out[key] = round(med, 4) if key in ("write_tok_s", "read_tok_s",
                                                 "ttft_s", "total_s") else med
    for kind, key, src in (("short", "short_write_tok_s", "write_tok_s"),
                           ("short", "short_total_s", "total_s"),
                           ("edit", "edit_write_tok_s", "write_tok_s")):
        vals = [s[src] for s, k in zip(samples, kinds) if k == kind and src in s]
        med = _median(vals)
        if med is not None:
            out[key] = round(med, 4)
    long_reads = [
        s["read_tok_s"] for s, k in zip(samples, kinds)
        if k == "long" and "read_tok_s" in s
    ]
    if long_reads:
        med = _median(long_reads)
        if med is not None:
            out["long_read_tok_s"] = round(med, 4)
    if any(s.get("garbled") for s in samples):
        out["garbled"] = True
    return out


def measure_http(port: int, *, prompts=None, max_tokens: int = 192,
                 urlopen=None, timeout: float = 300.0, chat_window=None) -> float:
    """Median write tok/s. Prefer measure_http_specs for the full score."""
    specs = measure_http_specs(port, prompts=prompts, max_tokens=max_tokens,
                               urlopen=urlopen, timeout=timeout,
                               chat_window=chat_window)
    return specs.get("write_tok_s") or 0.0


class GgufTuner:
    """restart(tune) reloads llama-server with that tune (blocking until ready);
    measure() returns a write-speed float or a {write, read, ttft} specs dict."""

    def __init__(self, model_path, n_minis: int, *, restart: Callable[[dict], None],
                 measure: Callable, store_path: Optional[Path] = None,
                 log: Callable[[str], None] = print, cancelled: Callable[[], bool] = lambda: False,
                 repeats: int = 1, schedule_kw: Optional[dict] = None, fresh: bool = False):
        self.key = entry_key(model_path, n_minis)
        # Day 28 tuning fix: a fresh Auto-tune retries every option. Old
        # losses used to be skipped silently ("not run" on the page).
        self.fresh = bool(fresh)
        self.restart, self.measure, self.log = restart, measure, log
        self.store_path, self.cancelled, self.repeats = store_path, cancelled, max(1, int(repeats))
        self.schedule_kw = dict(schedule_kw or {})

    def _score(self, tune: dict) -> dict:
        self.restart(dict(tune))
        acc = [as_specs(self.measure()) for _ in range(self.repeats)]
        out = {}
        for key in ("write_tok_s", "read_tok_s", "long_read_tok_s", "ttft_s", "total_s",
                    "short_write_tok_s", "short_total_s", "edit_write_tok_s"):
            med = _median(s[key] for s in acc if key in s)
            if med is not None:
                out[key] = med
        if any(s.get("garbled") for s in acc):
            out["garbled"] = True
        return out

    def run(self) -> dict:
        store = load_store(self.store_path)
        e = entry(store, self.key)
        if self.fresh:
            e["losses"] = []
            e.pop("helper_failed", None)
        best = dict(e["best"])
        result = {"key": self.key, "tried": [], "best": best, "status": "done",
                  "before": None, "after": None}
        scored = []  # (tune, specs)
        try:
            for item in G.gguf_schedule(best, e["losses"], **self.schedule_kw):
                if self.cancelled():
                    result["status"] = "cancelled"
                    break
                if item["skip"]:
                    self.log(f"gguf tune: {item['name']} skipped ({item['skip']})")
                    continue
                name, inc, ch = item["name"], item["incumbent"], item["challenger"]
                # Memory-compression trials always keep flash attention on.
                extra = {"flash_attn": "on"} if name == "cache_type" else {}
                if name == "guess_ahead":
                    # Day 27: the helper already on disk rides along with
                    # "on"; "off" never carries a helper path.
                    extra = {"draft_path": item.get("draft_path")}
                base = dict(best, **extra, **{name: inc})
                if name == "guess_ahead" and inc != "on":
                    base.pop("draft_path", None)
                try:
                    inc_specs = self._score(base)
                except Exception as ex:  # noqa: BLE001 - one option, not the run
                    # The current settings did not load or reply: skip this
                    # option and keep going with the next one.
                    self.log(f"gguf tune: {name} skipped, current settings failed: {ex}")
                    e["trials"].append({"name": name, "incumbent": inc, "challenger": ch,
                                        "failed": f"incumbent: {str(ex)[:300]}", "won": False,
                                        "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                    save_store(store, self.store_path)
                    continue
                scored.append((dict(base), dict(inc_specs)))
                if result["before"] is None:
                    result["before"] = dict(inc_specs)
                if self.cancelled():
                    result["status"] = "cancelled"
                    break
                chal = dict(best, **extra, **{name: ch})
                if name == "guess_ahead" and ch != "on":
                    chal.pop("draft_path", None)
                failed = None
                try:
                    ch_specs = self._score(chal)
                except Exception as ex:  # noqa: BLE001 - a failed trial is a loss
                    # Day 28 tuning fix: a trial that does not load or reply
                    # (for example the helper runs out of GPU memory) is a
                    # loss. Auto-tune keeps going instead of stopping.
                    failed = str(ex)[:300] or type(ex).__name__
                    ch_specs = {}
                    self.log(f"gguf tune: {name}={ch} failed ({failed}); counted as a loss")
                if not failed:
                    scored.append((dict(chal), dict(ch_specs)))
                if failed:
                    won = False
                elif ch_specs.get("garbled") and not inc_specs.get("garbled"):
                    won = False
                elif inc_specs.get("garbled") and not ch_specs.get("garbled"):
                    won = True
                elif ch_specs.get("garbled") and inc_specs.get("garbled"):
                    won = False
                else:
                    won = trial_won(name, ch_specs, inc_specs)
                rec = {"name": name, "incumbent": inc, "challenger": ch,
                       "incumbent_tps": round(inc_specs.get("write_tok_s") or 0, 2),
                       "challenger_tps": round(ch_specs.get("write_tok_s") or 0, 2),
                       "incumbent_specs": dict(inc_specs),
                       "challenger_specs": dict(ch_specs),
                       "won": won, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                if failed:
                    rec["failed"] = failed
                elif name in SPEC_KNOBS:
                    rec["why"] = spec_verdict(ch_specs, inc_specs)["why"]
                e["trials"].append(rec)
                result["tried"].append(rec)
                if won:
                    best[name] = ch
                    if name == "cache_type":
                        best["flash_attn"] = "on"
                else:
                    best.setdefault(name, inc)
                    e["losses"].append(f"{name}={ch}")
                if name == "guess_ahead":
                    if best.get("guess_ahead") == "on":
                        best["draft_path"] = item.get("draft_path")
                    else:
                        best.pop("draft_path", None)
                score = chat_score if name in SPEC_KNOBS else combined_score
                inc_s = score(inc_specs)
                ch_s = score(ch_specs)
                self.log(f"gguf tune: {name} {inc}={inc_s:.1f} vs {ch}={ch_s:.1f} -> "
                         f"{'keep ' + str(ch) if won else 'stay ' + str(inc)}")
                e["best"] = dict(best)
                save_store(store, self.store_path)
        except Exception as ex:  # noqa: BLE001 - always restore the winner
            result["status"] = f"error: {ex}"
        e["best"] = dict(best)
        save_store(store, self.store_path)
        try:
            self.restart(dict(best))  # leave the winner running
        except Exception as ex:  # noqa: BLE001
            result["status"] += f"; restore failed: {ex}"
        result["best"] = dict(best)
        result["after"] = result.get("before")
        for tune, specs in scored:
            if all(tune.get(k) == best.get(k) for k in best):
                result["after"] = specs
        return result
