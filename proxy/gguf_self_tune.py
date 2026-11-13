"""GGUF Self-tuning from real chat averages (Day 25, Phase 2).

Learns one llama-server option at a time from everyday chats, not from
canned Optimize now prompts. After enough replies at the current
settings, proposes one quiet trial, reloads when the chat is idle,
collects the same number of replies, and keeps the change only if it
beats the baseline by the same 3% margin Optimize now uses. The Before
and After line uses the same wording as Auto-tune.

Pinned Settings are never trialed. Chat window and Two chats are left
to the user: they change how much conversation and how many chats fit,
not a single-reply speed score, so Self-tuning does not flip them.

Everything that touches a Mini (reload) is injected, so this module is
unit-tested offline and never runs a model on import.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import gguf_split as G
import gguf_tune as T
import web_speed as S

STORE = Path("~/.caravan/gguf-self-tune.json").expanduser()
MIN_SAMPLES = 3
# Learn in this order, matching the GGUF optimization plan.
LEARN_ORDER = ("ubatch", "cache_type", "flash_attn")
LABELS = {
    "ubatch": "Prompt batch",
    "cache_type": "Memory compression",
    "flash_attn": "Flash attention",
}
VALUE_LABELS = {
    ("cache_type", "f16"): "16",
    ("cache_type", "q8_0"): "8",
    ("flash_attn", "on"): "On",
    ("flash_attn", "off"): "Off",
}


def store_path(path=None) -> Path:
    return Path(path or STORE)


def load_store(path=None) -> dict:
    p = store_path(path)
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_store(store: dict, path=None) -> None:
    p = store_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=1, sort_keys=True))
    tmp.replace(p)


def entry_key(model_path, n_minis: int) -> str:
    return T.entry_key(model_path, n_minis)


def entry(store: dict, key: str) -> dict:
    e = store.setdefault(key, {})
    e.setdefault("baseline", {})
    e.setdefault("used", {})
    e.setdefault("losses", [])
    e.setdefault("winners", {})
    e.setdefault("trial", None)
    e.setdefault("status", "collecting")
    e.setdefault("has_winners", False)
    return e


def clear_entry(model_path, n_minis: int, path=None) -> None:
    store = load_store(path)
    key = entry_key(model_path, n_minis)
    if key in store:
        del store[key]
        save_store(store, path)


def _specs_of(bucket) -> dict:
    return S._bucket_specs(bucket) if bucket else {}


def _label(name, value) -> str:
    return VALUE_LABELS.get((name, value), str(value))


def pick_trial(used: dict, pinned: set, losses: list) -> Optional[dict]:
    """Next one-option challenger, or None when nothing is left to try."""
    losses = list(losses or [])
    used = dict(used or {})
    knobs = dict(G.GGUF_KNOBS)
    for name in LEARN_ORDER:
        values = knobs.get(name)
        if not values:
            continue
        if name in pinned:
            continue
        if name == "flash_attn":
            inc = used.get(name, "on")
        elif name == "ubatch":
            inc = used.get(name, G.GGUF_DEFAULT_UBATCH)
        else:
            inc = used.get(name, "f16")
        alts = [v for v in values if v != inc and f"{name}={v}" not in losses]
        if name == "ubatch":
            alts.sort(key=lambda v: abs(int(v) - int(inc)))
        if not alts:
            continue
        ch = alts[0]
        extra = {"flash_attn": "on"} if name == "cache_type" else {}
        return {"name": name, "incumbent": inc, "challenger": ch, "extra": extra}
    return None


def pinned_knobs(settings) -> set:
    """Knob names the user pinned, so Self-tuning must not change them."""
    s = settings if isinstance(settings, dict) else {}
    out = set()
    if s.get("flash_attn") in ("on", "off"):
        out.add("flash_attn")
    if s.get("ubatch") in ("256", "512", "1024", 256, 512, 1024):
        out.add("ubatch")
    if s.get("kv_bits") in ("16", "8"):
        out.add("cache_type")
    return out


def used_from_tune(tune: dict) -> dict:
    tune = dict(tune or {})
    out = {}
    if tune.get("flash_attn") in ("on", "off"):
        out["flash_attn"] = tune["flash_attn"]
    else:
        out["flash_attn"] = "on"
    try:
        ub = int(tune["ubatch"]) if tune.get("ubatch") is not None else G.GGUF_DEFAULT_UBATCH
    except (TypeError, ValueError):
        ub = G.GGUF_DEFAULT_UBATCH
    out["ubatch"] = ub if ub in G.GGUF_UBATCH else G.GGUF_DEFAULT_UBATCH
    ct = tune.get("cache_type")
    out["cache_type"] = ct if ct in G.GGUF_KV_TYPES else "f16"
    return out


def observe(model_path, n_minis: int, specs, *, used=None, settings=None,
            self_tune_on=True, path=None, model_id=None,
            speed_path=None) -> dict:
    """Fold one real-chat reply into the GGUF self-tune record.

    Returns a plan: action is "idle", "reload", or "keep"; reload includes
    the tune to start (trial or revert). has_winners and before/after are
    always present so the page can fill the same lines Auto-tune uses.
    """
    empty = {
        "action": "idle", "tune": None, "trial": None, "has_winners": False,
        "before": None, "after": None, "reason": None, "label": None,
    }
    if not self_tune_on or not model_path:
        store = load_store(path)
        e = store.get(entry_key(model_path, n_minis)) if model_path else None
        if e:
            empty["has_winners"] = bool(e.get("has_winners"))
            empty["before"] = e.get("before")
            empty["after"] = e.get("after")
        return empty
    sample = S.specs_from(specs)
    if not S._has_specs(sample):
        return empty
    store = load_store(path)
    key = entry_key(model_path, n_minis)
    e = entry(store, key)
    pinned = pinned_knobs(settings)
    current = used_from_tune(used)
    plan = dict(empty)

    if e.get("status") == "done" and e.get("has_winners"):
        plan["has_winners"] = True
        plan["before"] = e.get("before")
        plan["after"] = e.get("after")
        return plan

    trial = e.get("trial")
    if not trial:
        e["used"] = current
        e["baseline"] = S._accum_specs(e.get("baseline"), sample)
        e["status"] = "collecting"
        save_store(store, path)
        if int((e["baseline"] or {}).get("write_n") or 0) < MIN_SAMPLES:
            plan["before"] = _specs_of(e["baseline"])
            return plan
        nxt = pick_trial(current, pinned, e.get("losses") or [])
        if not nxt:
            # Nothing to try; leave the baseline as a one-sided record.
            plan["before"] = _specs_of(e["baseline"])
            return plan
        # Propose the trial; the controller reloads when idle.
        e["trial"] = {
            "name": nxt["name"], "incumbent": nxt["incumbent"],
            "challenger": nxt["challenger"], "extra": nxt.get("extra") or {},
            "samples": {}, "started": time.time(),
        }
        e["status"] = "trial"
        save_store(store, path)
        trial_tune = dict(current, **(nxt.get("extra") or {}), **{nxt["name"]: nxt["challenger"]})
        plan.update({
            "action": "reload",
            "tune": trial_tune,
            "trial": dict(e["trial"]),
            "before": _specs_of(e["baseline"]),
            "reason": "trial",
            "label": LABELS.get(nxt["name"], nxt["name"]),
        })
        return plan

    # Mid-trial. The first reply after a reload is often a cold start
    # (especially after a memory-compression change), so skip it.
    trial = dict(trial)
    if not trial.get("settled"):
        trial["settled"] = True
        e["trial"] = trial
        e["status"] = "trial"
        save_store(store, path)
        plan["trial"] = dict(trial)
        plan["before"] = _specs_of(e.get("baseline"))
        plan["label"] = LABELS.get(trial.get("name"), trial.get("name"))
        plan["action"] = "idle"
        plan["reason"] = "settling"
        return plan
    trial["samples"] = S._accum_specs(trial.get("samples"), sample)
    e["trial"] = trial
    trial_n = int((trial["samples"] or {}).get("write_n") or 0)
    save_store(store, path)
    plan["trial"] = dict(trial)
    plan["before"] = _specs_of(e.get("baseline"))
    plan["label"] = LABELS.get(trial.get("name"), trial.get("name"))
    if trial_n < MIN_SAMPLES:
        plan["action"] = "idle"
        e["status"] = "trial"
        save_store(store, path)
        return plan

    base = _specs_of(e.get("baseline"))
    chal = _specs_of(trial["samples"])
    name, ch = trial["name"], trial["challenger"]
    won = T.beats(chal, base) if S._has_specs(chal) and S._has_specs(base) else False
    if won:
        e["winners"][name] = ch
        e["used"] = dict(e.get("used") or {}, **(trial.get("extra") or {}), **{name: ch})
        e["has_winners"] = True
        e["status"] = "done"
        e["before"] = base
        e["after"] = chal
        e["trial"] = None
        e["finished"] = time.time()
        save_store(store, path)
        if model_id:
            try:
                S.record_tuning(model_id, before=base, after=chal,
                                source="self_tune", path=speed_path)
            except Exception:
                pass
        plan.update({
            "action": "keep", "tune": dict(e["used"]), "has_winners": True,
            "before": base, "after": chal, "reason": "keep",
            "label": LABELS.get(name, name),
        })
        return plan

    # Revert: record the loss, reload back to the incumbent.
    loss = f"{name}={ch}"
    if loss not in (e.get("losses") or []):
        e.setdefault("losses", []).append(loss)
    e["has_winners"] = True
    e["status"] = "done"
    e["before"] = base
    e["after"] = base
    e["trial"] = None
    e["finished"] = time.time()
    e["unchanged"] = True
    save_store(store, path)
    if model_id:
        try:
            S.record_tuning(model_id, before=base, after=base,
                            source="self_tune", unchanged=True, path=speed_path)
        except Exception:
            pass
    revert = dict(e.get("used") or current)
    plan.update({
        "action": "reload", "tune": revert, "has_winners": True,
        "before": base, "after": base, "reason": "revert",
        "label": LABELS.get(name, name),
        "unchanged": True,
    })
    return plan


def record_load_failure(model_path, n_minis: int, trial: dict, path=None) -> None:
    """A trial that failed to load is a loss and is not retried."""
    if not trial or not trial.get("name"):
        return
    store = load_store(path)
    e = entry(store, entry_key(model_path, n_minis))
    loss = f"{trial['name']}={trial.get('challenger')}"
    if loss not in (e.get("losses") or []):
        e.setdefault("losses", []).append(loss)
    e["trial"] = None
    e["status"] = "collecting"
    save_store(store, path)


class Controller:
    """Background quiet reload for one GGUF self-tune trial or revert.

    Never restarts mid-reply. Yields to Auto-tune if that is running.
    """

    def __init__(self, mgr, *, inflight: Callable[[], int] = lambda: 0,
                 optimizer_running: Callable[[], bool] = lambda: False,
                 store_path=None, sleep=time.sleep):
        self.mgr = mgr
        self._inflight = inflight
        self._optimizer_running = optimizer_running
        self.store_path = store_path
        self._sleep = sleep
        self._lock = threading.Lock()
        self._pending = None
        self._thread = None
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            self._pending = None

    def handle(self, plan: dict, *, model_id=None, entry=None, settings=None,
               model_path=None, n_minis=1) -> None:
        if not plan or plan.get("action") != "reload" or not plan.get("tune"):
            return
        with self._lock:
            self._pending = {
                "tune": dict(plan["tune"]),
                "reason": plan.get("reason") or "trial",
                "label": plan.get("label") or "settings",
                "trial": plan.get("trial"),
                "model_id": model_id,
                "entry": entry,
                "settings": settings or {},
                "model_path": model_path,
                "n_minis": n_minis,
            }
            self._cancel.clear()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    def pending(self):
        with self._lock:
            return dict(self._pending) if self._pending else None

    def _note(self, msg: str) -> None:
        try:
            note = getattr(self.mgr, "_note", None)
            if callable(note):
                note(msg)
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            if self._cancel.is_set():
                return
            with self._lock:
                job = dict(self._pending) if self._pending else None
            if not job:
                return
            try:
                if self._optimizer_running():
                    self._sleep(0.5)
                    continue
                if int(self._inflight() or 0) > 0:
                    self._sleep(0.2)
                    continue
                # A short quiet window so a just-ending reply is fully done.
                self._sleep(0.4)
                if int(self._inflight() or 0) > 0 or self._optimizer_running():
                    continue
                if self._cancel.is_set():
                    return
                reason = job["reason"]
                label = job["label"]
                if reason == "revert":
                    self._note(
                        "The trial was not faster. The model is reloading "
                        "with the previous settings."
                    )
                else:
                    self._note(
                        f"Trying a different {label}. The model is reloading."
                    )
                entry = dict(job.get("entry") or {})
                entry["tune_override"] = dict(job["tune"])
                mid = job.get("model_id") or entry.get("id")
                self.mgr.switch(
                    mid, wait=True,
                    settings=job.get("settings") or {},
                    entry=entry,
                )
                snap = self.mgr.snapshot() if hasattr(self.mgr, "snapshot") else {}
                if snap.get("status") != "ready":
                    record_load_failure(
                        job.get("model_path"), job.get("n_minis") or 1,
                        job.get("trial") or {}, path=self.store_path,
                    )
                    self._note(
                        "That trial setting could not load. The model is "
                        "back on the previous settings."
                    )
                with self._lock:
                    # Clear only if nothing newer was queued.
                    if self._pending and self._pending.get("tune") == job["tune"]:
                        self._pending = None
            except Exception:
                try:
                    record_load_failure(
                        job.get("model_path"), job.get("n_minis") or 1,
                        job.get("trial") or {}, path=self.store_path,
                    )
                except Exception:
                    pass
                with self._lock:
                    if self._pending and self._pending.get("tune") == job.get("tune"):
                        self._pending = None
                return
