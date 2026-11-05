"""Optimize now: one A/B per option against the current best, then stop.

Walk-away pass the user starts. Each Optimizations option (and the packer
layer cut) is tried once versus the Day 9 guess or the saved winner. Live
options flip in place. A reload happens only when a reload-only knob still
on Auto needs that trial. Values that already lost for this model and
hardware are skipped until the hardware fingerprint changes.

Optimize as used — everyday Auto learning on real chats — is the worker's
existing light probes. This runner does not replace that path and does not
search combinations of options.

Cancel any time. Progress and the time left come from measured reply and
reload times. Winners are saved per model + hardware.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Optional
from urllib.request import Request, urlopen

import tuned_settings as TS
import web_settings

# Fixed prompt set: short, predictable, long, and a long shared opening
# (> 512 tokens) so shared start has something to reuse.
_PREAMBLE = " ".join(
    f"Section {i}: Caravan runs one language model across two Mac minis. The lead "
    f"holds the last layers and the packer holds the first layers. Each reply "
    f"crosses Thunderbolt between them, so every millisecond of hand-off matters. "
    f"Self-tuning tries settings, times replies, and keeps whatever is fastest."
    for i in range(1, 13))
SHORT = [
    "Name three colors.",
    "What is 17 times 3? Answer with the number only.",
    "Give one synonym for quick.",
    "Say hello in French.",
]
PREDICTABLE = [
    "Count from 1 to 40, separated by commas.",
    "List the months of the year, one per line.",
    "Write the alphabet in capital letters separated by spaces.",
]
LONG = [
    "Explain in about 150 words why caching speeds up repeated work.",
    "Write a short story (about 150 words) about a lighthouse keeper.",
]
SHARED_Q = [
    "In one sentence: which Mac holds the first layers?",
    "In one sentence: what does self-tuning keep?",
    "In one sentence: what does each reply cross?",
]
# One arm is a few replies, not a sweep of every value.
AB_ARM = 3
VERIFY_ARM = 2


def prompt_plan(i: int) -> list:
    """Messages for prompt i (deterministic cycle)."""
    kind = i % 4
    if kind == 0:
        return [{"role": "system", "content": _PREAMBLE},
                {"role": "user", "content": SHARED_Q[(i // 4) % len(SHARED_Q)]}]
    if kind == 1:
        return [{"role": "user", "content": PREDICTABLE[(i // 4) % len(PREDICTABLE)]}]
    if kind == 2:
        return [{"role": "user", "content": SHORT[(i // 4) % len(SHORT)]}]
    return [{"role": "user", "content": LONG[(i // 4) % len(LONG)]}]


def unavailable(active: Optional[dict]) -> set:
    """Options this model/setup can't vary."""
    a = active or {}
    out = set()
    if not a.get("guess_ahead_loaded"):
        out.add("guess_ahead")
    if a.get("keepalive") is None:  # single Mini: no pipe, keep-warm, or packer cut
        out |= {"keepalive", "pipeline_chats", "shared_prefix", "packer_layers"}
    return out


def eta_s(*, prompts_left: int, reloads_left: int,
          reply_s: Optional[float], reload_s: Optional[float]) -> Optional[float]:
    """Time left from measured reply and reload times. None until those exist."""
    prompts_left = max(0, int(prompts_left or 0))
    reloads_left = max(0, int(reloads_left or 0))
    if prompts_left and reply_s is None:
        return None
    if reloads_left and reload_s is None:
        return None
    return prompts_left * float(reply_s or 0) + reloads_left * float(reload_s or 0)


def _arm_kind(name: str) -> str:
    if name == "shared_prefix":
        return "ttft"
    if name == "pipeline_chats":
        return "pipeline"
    return "tps"


def _as_result(raw) -> dict:
    if isinstance(raw, dict):
        out = dict(raw)
        out.setdefault("elapsed", float(raw.get("elapsed") or 0))
        return out
    return {"elapsed": float(raw)}


def score_result(kind: str, result: dict) -> float:
    """Higher is better. Shared start uses time-to-first-token; pipeline uses wall time."""
    elapsed = max(float(result.get("elapsed") or 0), 0.001)
    if kind == "ttft":
        ttft = result.get("ttft")
        return TS.shared_prefix_score(elapsed if ttft is None else ttft)
    if kind == "pipeline":
        return 1.0 / elapsed
    ct = result.get("completion_tokens")
    total = result.get("total_s")
    if ct is not None and total is not None:
        return TS.normalized_tps(
            completion_tokens=int(ct), total_s=float(total),
            prefill_s=float(result.get("prefill_s") or 0),
            prompt_tokens=int(result.get("prompt_tokens") or 0))
    return 1.0 / elapsed


class Optimizer:
    def __init__(self, mgr, *, inflight=None, send=None, sleep=time.sleep):
        self.mgr = mgr
        self.inflight = inflight or (lambda: 0)
        self._send_fn = send or self._http_send
        self._sleep = sleep
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._items = []
        self._states = {}
        self._phase = "idle"
        self._prompts_left = 0
        self._reloads_left = 0
        self.best = {}
        self.running = {}
        self.packer_k = None
        self.fp = ""
        self.state = {"running": False, "mode": None, "phase": "idle", "prompts": 0,
                      "reloads": 0, "started": None, "eta_s": None, "reply_s": None,
                      "reload_s": None, "schedule": None, "log": [], "summary": None,
                      "error": None}

    def snapshot(self) -> dict:
        with self._lock:
            s = dict(self.state)
            s["log"] = list(self.state["log"][-30:])
            if s.get("schedule"):
                s["schedule"] = [dict(x) for x in s["schedule"]]
        return s

    def start(self, mode: str = "now") -> dict:
        """Start Optimize now. `mode` is ignored — there is no Quick-only path."""
        del mode
        if self._thread and self._thread.is_alive():
            raise RuntimeError("optimize already running")
        snap = self.mgr.snapshot()
        if snap.get("status") != "ready" or not snap.get("model_id"):
            raise RuntimeError("load a model first")
        self._cancel.clear()
        self._items, self._states = [], {}
        self._phase = "starting"
        self._set(running=True, mode="now", phase="starting", prompts=0, reloads=0,
                  started=time.time(), eta_s=None, reply_s=None, reload_s=None,
                  schedule=None, summary=None, error=None, log=[])
        self._thread = threading.Thread(target=self._run_safe, daemon=True)
        self._thread.start()
        return self.snapshot()

    def cancel(self) -> dict:
        self._cancel.set()
        self._log("cancel requested")
        return self.snapshot()

    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    def _log(self, msg: str):
        with self._lock:
            self.state["log"].append({"t": round(time.time(), 1), "msg": msg})
            self.state["log"] = self.state["log"][-60:]

    def _publish(self):
        self._set(phase=self._phase, schedule=self._view(),
                  eta_s=eta_s(prompts_left=self._prompts_left, reloads_left=self._reloads_left,
                              reply_s=self.state["reply_s"], reload_s=self.state["reload_s"]))

    def _view(self) -> list:
        out = []
        for it in self._items:
            state = self._states.get(it["name"], "skipped" if it["skip"] else "pending")
            if state == "kept" and it["name"] in self.best:
                detail = TS.knob_value_label(it["name"], self.best[it["name"]])
            else:
                detail = it["skip"] or ""
            out.append({"name": it["name"], "label": it["label"], "state": state,
                        "detail": detail, "reload": it["reload"]})
        return out

    def _user_settings(self) -> dict:
        return web_settings.normalize(self.mgr.snapshot().get("settings") or {})

    def _n_layers(self):
        n = getattr(self.mgr, "n_layers", None)
        if callable(n):
            try:
                return n()
            except Exception:
                return None
        return n

    def _sweep(self, body: dict) -> dict:
        fn = getattr(self.mgr, "sweep", None)
        if fn is None:
            raise RuntimeError("lead has no optimize-now control")
        return fn(body)

    def _release(self):
        fn = getattr(self.mgr, "sweep", None)
        if fn is None:
            return
        try:
            fn({"release": True})
        except Exception as e:  # noqa: BLE001 — surface on the log, still finish
            self._log(f"could not resume everyday learning ({e})")

    def _wait(self, phase: str):
        while self.inflight() > 0 and not self._cancel.is_set():
            self._phase = phase
            self._publish()
            self._sleep(1)

    def _note_reply(self, result: dict):
        dt = float(result.get("elapsed") or 0)
        n = self.state["prompts"]
        prev = self.state["reply_s"]
        avg = dt if prev is None else (prev * n + dt) / (n + 1)
        self._prompts_left = max(0, self._prompts_left - 1)
        self._set(prompts=n + 1, reply_s=round(avg, 2))
        self._publish()

    def _note_reload(self, dt: float):
        n = self.state["reloads"]
        prev = self.state["reload_s"]
        avg = dt if prev is None else (prev * n + dt) / (n + 1)
        self._reloads_left = max(0, self._reloads_left - 1)
        self._set(reloads=n + 1, reload_s=round(avg, 1))
        self._publish()

    def _pull_running(self):
        active = self.mgr.lead_active_settings() or {}
        for n in TS.RELOAD_TRIO:
            if active.get(n) is not None:
                self.running[n] = TS.norm_knob(n, active[n])

    def _running_is(self, name: str, value) -> bool:
        if name == "packer_layers":
            return self.packer_k is not None and int(self.packer_k) == int(value)
        if name not in self.running or value is None:
            return False
        return TS.norm_knob(name, self.running[name]) == TS.norm_knob(name, value)

    def _force_map(self, overrides=None) -> dict:
        force = {}
        for n in TS.RELOAD_TRIO:
            if n in self.best:
                force[n] = self.best[n]
        if overrides:
            force.update(overrides)
        return force

    def _reload(self, why: str, *, packer_layers, reload_force, freeze: bool = True):
        self._wait("waiting for your chat to finish before reloading")
        if self._cancel.is_set():
            return
        self._phase = f"reloading to {why}"
        self._publish()
        self._log(f"reloading to {why}")
        t0 = time.time()
        self.mgr.switch(
            self.mgr.snapshot().get("model_id"), wait=True, settings=self._user_settings(),
            packer_layers=packer_layers, hold_trials=True, reload_force=reload_force,
            freeze_forced=freeze)
        self._note_reload(time.time() - t0)
        self._pull_running()
        if packer_layers is not None:
            self.packer_k = int(packer_layers)
        snap = self.mgr.snapshot()
        if snap.get("status") != "ready":
            raise RuntimeError(f"reload failed: {snap.get('error')}")
        self._log(f"reloaded in {time.time() - t0:.0f}s")
        if freeze:
            self._sweep({"pause": True})

    def _extra_reload(self, why: str, *, packer_layers, reload_force):
        self._reloads_left += 1
        self._publish()
        self._reload(why, packer_layers=packer_layers, reload_force=reload_force, freeze=True)

    def _apply_value(self, name: str, value, why: str):
        if name == "packer_layers":
            self._reload(why, packer_layers=int(value), reload_force=self._force_map(), freeze=True)
            return
        self._reload(why, packer_layers=self.packer_k,
                     reload_force=self._force_map({name: value}), freeze=True)

    def _hold_live(self, extra=None):
        hold = {}
        settings = self._user_settings()
        ui_for = {"guess_ahead": "guess_ahead", "shared_prefix": "shared_start",
                  "pipeline_chats": "pipeline_chats"}
        for name, ui in ui_for.items():
            if settings.get(ui) != "auto":
                continue
            if name in self.best:
                hold[name] = self.best[name]
        if extra:
            for name, value in extra.items():
                ui = ui_for.get(name)
                if ui and settings.get(ui) != "auto":
                    continue
                hold[name] = value
        if hold:
            self._sweep({"pause": True, "hold": hold})

    def _one(self, messages) -> dict:
        return _as_result(self._send_fn(messages))

    def _http_send(self, messages: list, max_tokens: int = 160) -> dict:
        body = json.dumps(
            {"messages": messages, "max_tokens": max_tokens, "stream": False}).encode()
        req = Request(f"http://127.0.0.1:{self.mgr.lead_port}/v1/chat/completions",
                      data=body, method="POST",
                      headers={"Content-Type": "application/json",
                               "X-Caravan-Session": "opt-" + uuid.uuid4().hex[:12]})
        t0 = time.time()
        with urlopen(req, timeout=600) as r:
            raw = r.read()
        elapsed = time.time() - t0
        out = {"elapsed": elapsed}
        try:
            full = json.loads(raw).get("usage") or {}
            caravan = full.get("caravan") or {}
            out["ttft"] = caravan.get("ttft_s")
            out["total_s"] = caravan.get("total_s") or elapsed
            out["prefill_s"] = caravan.get("prefill_s")
            out["completion_tokens"] = full.get("completion_tokens")
            out["prompt_tokens"] = full.get("prompt_tokens")
        except (ValueError, TypeError):
            pass
        return out

    def _round(self, kind: str, i: int, n_chats: Optional[int]) -> dict:
        if kind == "pipeline":
            # Real replies overlap only when the worker can run two chats.
            # Measured wall time is the score. A simulated reply (tests) reports
            # its own elapsed; width 2 keeps the max and width 1 adds them.
            results, errors = [], []

            def run(m):
                try:
                    results.append(self._one(m))
                except Exception as e:  # noqa: BLE001 — raised after join
                    errors.append(e)

            t0 = time.time()
            threads = [threading.Thread(target=run, args=(m,))
                       for m in (prompt_plan(1), prompt_plan(2))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            if errors:
                raise errors[0]
            wall = max(time.time() - t0, 0.001)
            if results and all(r.get("simulated") for r in results):
                sim = [r["elapsed"] for r in results]
                elapsed = max(sim) if int(n_chats or 1) >= 2 else sum(sim)
            else:
                elapsed = wall
            return {"elapsed": elapsed, "ttft": elapsed, "total_s": elapsed,
                    "prefill_s": 0, "completion_tokens": None}
        if kind == "ttft":
            return self._one(prompt_plan(0))
        return self._one(prompt_plan(i))

    def _measure(self, kind: str, n_chats: Optional[int] = None) -> list:
        scores = []
        for i in range(AB_ARM):
            if self._cancel.is_set():
                break
            self._wait("paused while your chat runs")
            if self._cancel.is_set():
                break
            result = self._round(kind, i, n_chats)
            self._note_reply(result)
            scores.append(score_result(kind, result))
            self._phase = self._phase_base + f" · prompt {i + 1}/{AB_ARM}"
            self._publish()
        return scores

    def _commit(self, name: str, winner_value, lost_value):
        self._sweep({"pause": True, "commit": {
            "fingerprint": self.fp, "name": name,
            "winner": winner_value, "lost": lost_value,
        }})
        self.best[name] = TS.norm_knob(name, winner_value)

    def _drift(self) -> bool:
        settings = self._user_settings()
        for n in TS.RELOAD_TRIO:
            if settings.get(n) != "auto" or n not in self.best or n not in self.running:
                continue
            if TS.norm_knob(n, self.running[n]) != TS.norm_knob(n, self.best[n]):
                return True
        if "packer_layers" in self.best and self.packer_k is not None:
            if int(self.packer_k) != int(self.best["packer_layers"]):
                return True
        return False

    def _run_safe(self):
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — surface to UI
            self._set(error=f"{type(e).__name__}: {e}", phase="stopped (error)")
            self._log(f"error: {e}")
        finally:
            self._release()
            self._set(running=False)

    def _run(self):
        settings = self._user_settings()
        path = getattr(self.mgr, "_lead_path", None)
        try:
            _st, entry = self.mgr._tuned_entry(path, create=True)
        except (OSError, ValueError, TypeError):
            entry = None
        active = self.mgr.lead_active_settings() or {}
        packer = None
        cat = getattr(self.mgr, "catalog_packer_layers", None)
        if callable(cat):
            packer = cat()
        self.fp = self.mgr.hardware_fingerprint() if hasattr(self.mgr, "hardware_fingerprint") else (
            TS.hardware_fingerprint(spanned=True))
        baseline = TS.baseline_values(entry, active, packer_layers=packer)
        self._items = TS.build_schedule(
            entry, fingerprint=self.fp, settings=settings, baseline=baseline,
            unavailable=unavailable(active), n_layers=self._n_layers())
        self.best = dict(baseline)
        for it in self._items:
            if it["incumbent"] is not None:
                self.best[it["name"]] = it["incumbent"]
            self._states[it["name"]] = "skipped" if it["skip"] else "pending"
        self._pull_running()
        self.packer_k = self.best.get("packer_layers", packer)
        trials = [it for it in self._items if not it["skip"]]
        self._prompts_left = len(trials) * AB_ARM * 2 + (VERIFY_ARM if trials else 0)
        self._reloads_left = sum(1 for it in trials if it["reload"])
        self._log(f"optimize now: {len(trials)} option(s) to try, "
                  f"{sum(1 for it in self._items if it['skip'])} skipped")
        for it in self._items:
            if it["skip"]:
                self._log(f"skip {it['label']}: {it['skip']}")
        self._phase = "starting"
        self._publish()
        if trials:
            self._sweep({"pause": True, "clear_pending": True})

        for it in trials:
            if self._cancel.is_set():
                break
            name = it["name"]
            self._states[name] = "running"
            inc, ch = it["incumbent"], it["challenger"]
            kind = _arm_kind(name)
            self._phase_base = (
                f"A/B {it['label']} {TS.knob_value_label(name, ch)} vs "
                f"{TS.knob_value_label(name, inc)}")
            self._phase = self._phase_base
            self._publish()
            self._log(self._phase_base)
            if it["reload"]:
                if not self._running_is(name, inc):
                    self._extra_reload(
                        f"{it['label']} {TS.knob_value_label(name, inc)}",
                        packer_layers=inc if name == "packer_layers" else self.packer_k,
                        reload_force=self._force_map(
                            {} if name == "packer_layers" else {name: inc}))
                    if self._cancel.is_set():
                        break
                inc_scores = self._measure(kind, inc if name == "pipeline_chats" else None)
                if self._cancel.is_set():
                    break
                self._apply_value(name, ch, f"try {it['label']} {TS.knob_value_label(name, ch)}")
                if self._cancel.is_set():
                    break
                ch_scores = self._measure(kind, ch if name == "pipeline_chats" else None)
            else:
                self._hold_live({name: inc})
                inc_scores = self._measure(kind, inc if name == "pipeline_chats" else None)
                if self._cancel.is_set():
                    break
                self._hold_live({name: ch})
                ch_scores = self._measure(kind, ch if name == "pipeline_chats" else None)
            if self._cancel.is_set():
                break
            kept, lost = (ch, inc) if TS.ab_pick(inc_scores, ch_scores) == "challenger" else (inc, ch)
            self._commit(name, kept, lost)
            if it["reload"] and not self._running_is(name, kept):
                self._extra_reload(
                    f"{it['label']} {TS.knob_value_label(name, kept)}",
                    packer_layers=kept if name == "packer_layers" else self.packer_k,
                    reload_force=self._force_map(
                        {} if name == "packer_layers" else {name: kept}))
            elif not it["reload"]:
                self._hold_live({name: kept})
            self._states[name] = "kept"
            self._log(f"kept {it['label']} {TS.knob_value_label(name, kept)}")
            self._publish()

        if trials and not self._cancel.is_set():
            self._phase = "verify winner"
            self._publish()
            if self._drift():
                self._extra_reload(
                    "finish on the winners", packer_layers=self.best.get("packer_layers", self.packer_k),
                    reload_force=self._force_map())
            self._hold_live()
            for i in range(VERIFY_ARM):
                if self._cancel.is_set():
                    break
                self._wait("paused while your chat runs")
                if self._cancel.is_set():
                    break
                self._note_reply(self._one(prompt_plan(i)))
            self._log("verify pass on the winner")

        try:
            _st, entry = self.mgr._tuned_entry(path, create=False)
        except (OSError, ValueError, TypeError):
            entry = None
        canceled = self._cancel.is_set()
        complete = (not canceled) and all(
            self._states.get(it["name"]) in ("kept", "skipped") for it in self._items)
        self._prompts_left = 0
        self._reloads_left = 0
        self._phase = "canceled" if canceled else ("done" if complete else "stopped")
        winner = dict((entry or {}).get("winner") or {})
        self._set(summary={
            "winner": winner,
            "prompts": self.state["prompts"],
            "reloads": self.state["reloads"],
            "minutes": round((time.time() - (self.state["started"] or time.time())) / 60, 1),
            "complete": complete,
        })
        self._publish()
        self._set(eta_s=0 if complete else None)
        self._log("done" if complete else "stopped before every option was tried")
