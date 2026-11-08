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

MARGIN = 0.03
STORE = Path("~/.caravan/gguf-tuned.json").expanduser()
BENCH_PROMPTS = (
    "Explain how a bicycle gear system works in about 150 words.",
    "Write a short Python function that checks whether a string is a palindrome, with a docstring.",
)


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
    return out


def measure_http(port: int, *, prompts=BENCH_PROMPTS, max_tokens: int = 192,
                 urlopen=None, timeout: float = 300.0) -> float:
    """Mean decode tok/s over the prompts, from llama-server's own timings
    (`timings.predicted_per_second`), falling back to tokens / wall time."""
    import urllib.request
    urlopen = urlopen or urllib.request.urlopen
    rates = []
    for p in prompts:
        body = json.dumps({"messages": [{"role": "user", "content": p}],
                           "max_tokens": int(max_tokens), "temperature": 0,
                           "seed": 1, "stream": False}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{int(port)}/v1/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        dt = time.time() - t0
        tps = ((d.get("timings") or {}).get("predicted_per_second"))
        if not tps:
            n = ((d.get("usage") or {}).get("completion_tokens")) or 0
            tps = n / dt if dt > 0 and n else 0.0
        rates.append(float(tps))
    return sum(rates) / len(rates) if rates else 0.0


class GgufTuner:
    """restart(tune) reloads llama-server with that tune (blocking until it
    answers); measure() returns decode tok/s for the running server."""

    def __init__(self, model_path, n_minis: int, *, restart: Callable[[dict], None],
                 measure: Callable[[], float], store_path: Optional[Path] = None,
                 log: Callable[[str], None] = print, cancelled: Callable[[], bool] = lambda: False,
                 repeats: int = 1):
        self.key = entry_key(model_path, n_minis)
        self.restart, self.measure, self.log = restart, measure, log
        self.store_path, self.cancelled, self.repeats = store_path, cancelled, max(1, int(repeats))

    def _score(self, tune: dict) -> float:
        self.restart(dict(tune))
        return sum(self.measure() for _ in range(self.repeats)) / self.repeats

    def run(self) -> dict:
        store = load_store(self.store_path)
        e = entry(store, self.key)
        best = dict(e["best"])
        result = {"key": self.key, "tried": [], "best": best, "status": "done"}
        try:
            for item in G.gguf_schedule(best, e["losses"]):
                if self.cancelled():
                    result["status"] = "cancelled"
                    break
                if item["skip"]:
                    self.log(f"gguf tune: {item['name']} skipped ({item['skip']})")
                    continue
                name, inc, ch = item["name"], item["incumbent"], item["challenger"]
                base = dict(best, **{name: inc})
                inc_tps = self._score(base)
                if self.cancelled():
                    result["status"] = "cancelled"
                    break
                ch_tps = self._score(dict(best, **{name: ch}))
                won = ch_tps > inc_tps * (1 + MARGIN)
                rec = {"name": name, "incumbent": inc, "challenger": ch,
                       "incumbent_tps": round(inc_tps, 2), "challenger_tps": round(ch_tps, 2),
                       "won": won, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                e["trials"].append(rec)
                result["tried"].append(rec)
                if won:
                    best[name] = ch
                else:
                    best.setdefault(name, inc)
                    e["losses"].append(f"{name}={ch}")
                self.log(f"gguf tune: {name} {inc}={inc_tps:.1f} vs {ch}={ch_tps:.1f} tok/s -> "
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
        return result
