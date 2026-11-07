"""Walk-away tuning: paired arms, one knob at a time; ordinary Auto is separate."""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

import optimize_schedule as AB
import tuned_settings as TS
import web_settings

AB_ARM = 3

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

def prompt_plan(i):
    if i % 3 == 0:
        return [{"role": "system", "content": _PREAMBLE},
                {"role": "user", "content": SHARED_Q[0]}]
    return [{"role": "user", "content": (PREDICTABLE if i % 3 == 1 else LONG)[0]}]


class Canceled(Exception):
    pass


class Optimizer:
    def __init__(self, mgr, *, inflight=lambda: 0, send=None, sleep=time.sleep):
        self.mgr, self.inflight, self._sleep = mgr, inflight, sleep
        self._send = send or self._http_send
        self._cancel, self._pause = threading.Event(), threading.Event()
        self._lock = threading.RLock()
        self._thread = None
        self.state = dict(running=False, mode=None, phase="idle", prompts=0, reloads=0,
                          started=None, eta_s=None, reply_s=None, reload_s=None,
                          schedule=[], results=[], log=[], summary=None, error=None, paused=False)

    def snapshot(self):
        with self._lock:
            out = copy.deepcopy(self.state)
            todo = [i for i in out["schedule"] if i["state"] in ("pending", "running")]
            reloads = sum(2 for i in todo if i["reload"])
            if out["running"] and out["reply_s"] is not None and (not reloads or out["reload_s"] is not None):
                out["eta_s"] = round(len(todo) * AB_ARM * 2 * out["reply_s"] + reloads * (out["reload_s"] or 0))
            return out

    def _set(self, **values):
        with self._lock:
            self.state.update(values)

    def _log(self, msg):
        with self._lock:
            self.state["log"] = (self.state["log"] + [{"t": time.time(), "msg": msg}])[-60:]

    def start(self, mode="now"):
        # Accept legacy clients, but never resurrect Deep/Quick coverage.
        with self._lock:
            if self.state["running"]:
                raise RuntimeError("optimize already running")
            snap = self.mgr.snapshot()
            if snap.get("status") != "ready" or not snap.get("model_id"):
                raise RuntimeError("load a model first")
            active = self.mgr.lead_active_settings()
            if not active or not active.get("self_tune", True):
                raise RuntimeError("Optimize now needs an MLX model with Auto learning on")
            settings = web_settings.normalize(snap.get("settings") or {})
            if (settings.get("guess_ahead") == "mtp" or
                    settings.get("prompt_lookup") == "adaptive"):
                raise RuntimeError("turn off native MTP / adaptive lookup before Optimize now")
            self.model_id = snap["model_id"]
            self.settings = settings
            self.entry = copy.deepcopy(getattr(self.mgr, "_loaded_entry", None))
            self._cancel.clear()
            self._pause.clear()
            self._set(running=True, mode="now", phase="starting", prompts=0, reloads=0,
                      started=time.time(), eta_s=None, reply_s=None, reload_s=None,
                      schedule=[], results=[], log=[], summary=None, error=None, paused=False)
            self._thread = threading.Thread(target=self._run_safe, daemon=True)
            self._thread.start()
            return self.snapshot()

    def cancel(self):
        self._cancel.set()
        self._pause.clear()
        self._log("cancel requested; any current reply/reload finishes, then restore winners")
        return self.snapshot()

    def pause(self, paused=True):
        if paused:
            self._pause.set()
        else:
            self._pause.clear()
        self._set(paused=bool(paused))
        return self.snapshot()

    def _boundary(self):
        while self._pause.is_set() or self.inflight() > 0:
            if self._cancel.is_set():
                raise Canceled()
            self._set(phase="paused" if self._pause.is_set() else "waiting for your chat")
            self._sleep(0.1)
        if self._cancel.is_set():
            raise Canceled()
        snap = self.mgr.snapshot()
        if snap.get("model_id") != self.model_id or snap.get("status") != "ready":
            raise RuntimeError("model changed during Optimize now")

    def _hold(self, values):
        self.mgr.sweep({"pause": True, "hold": {n: v for n, v in values.items()
                                             if n in AB.LIVE and n not in self.pinned}})

    def _reload(self, values, *, restoring=False):
        if not restoring:
            self._boundary()
        else:
            # Restoration is mandatory after cancellation/failure. It must not
            # kill a user chat that arrived during the preceding reload.
            while self.inflight() > 0:
                self._sleep(0.1)
        self._set(phase="restoring winners" if restoring else "reloading one option")
        force = {n: values[n] for n in TS.RELOAD_TRIO if n in values}
        sweep = {"force": force, "packer_layers": values.get("packer_layers")}
        t0 = time.monotonic()
        self.mgr.switch(self.model_id, wait=True, settings=self.settings,
                        entry=self.entry, sweep=sweep)
        elapsed = time.monotonic() - t0
        n = self.state["reloads"]
        self._set(reloads=n + 1, reload_s=round(elapsed, 3))
        if self.mgr.snapshot().get("status") != "ready":
            raise RuntimeError("reload failed: " + str(self.mgr.snapshot().get("error")))
        # Mark only after a successful load, so a failed challenger forces a
        # recovery reload rather than falsely believing baseline is still up.
        self.current = dict(values)
        self._hold(values)

    def _apply(self, name, value):
        self._boundary()
        values = dict(self.best, **{name: value})
        if name in AB.LIVE:
            self._hold(values)
            self.current = values
        elif any(self.current.get(n) != v for n, v in values.items() if n not in AB.LIVE):
            self.dirty_reload = True
            self._reload(values)

    def _http_send(self, messages):
        data = json.dumps(dict(messages=messages, max_tokens=96, temperature=0,
                               stream=False, thinking=False)).encode()
        req = Request(f"http://127.0.0.1:{self.mgr.lead_port}/v1/chat/completions",
                      data=data, headers={"Content-Type": "application/json",
                      "X-Caravan-Session": "opt-" + uuid.uuid4().hex[:12]})
        t0 = time.monotonic()
        with urlopen(req, timeout=600) as response:
            usage = json.loads(response.read()).get("usage") or {}
        elapsed = time.monotonic() - t0
        detail = usage.get("caravan") or {}
        return dict(elapsed=elapsed, ttft=detail.get("ttft_s"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_s=detail.get("total_s", elapsed), prefill_s=detail.get("prefill_s", 0))

    def _one(self, messages):
        result = self._send(messages)
        if not isinstance(result, dict):
            result = {"elapsed": float(result)}
        n = self.state["prompts"]
        elapsed = float(result["elapsed"])
        avg = (float(self.state["reply_s"] or 0) * n + elapsed) / (n + 1)
        self._set(prompts=n + 1, reply_s=round(avg, 3))
        return result

    def _measure(self, name, arm):
        scores = []
        if name == "shared_prefix":
            self._boundary()
            self._one(prompt_plan(0))  # seed shared prefix; cold store is not a hit
        for i in range(AB_ARM):
            self._boundary()
            self._set(phase=f"A/B {name}: {arm} {i + 1}/{AB_ARM}")
            if name == "pipeline_chats":
                t0 = time.monotonic()
                # Only this knob needs simultaneous requests, not simultaneous
                # option trials. Same pair is sent to both arm widths.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(self._send, prompt_plan(j + 1)) for j in range(2)]
                    results = [f.result() for f in futures]
                elapsed = time.monotonic() - t0
                for result in results:
                    # Account outside threads (avoid lost counter updates).
                    n = self.state["prompts"]
                    self._set(prompts=n + 1)
                ct = sum(r.get("completion_tokens") or 0 for r in results)
                if ct <= 0:
                    raise ValueError("pipeline reply missing token counts")
                score = ct / max(elapsed, 0.001)
            else:
                result = self._one(prompt_plan(0 if name == "shared_prefix" else i))
                if name == "shared_prefix":
                    if not result.get("ttft") or result["ttft"] <= 0:
                        raise ValueError("reply missing TTFT")
                    score = 1.0 / result["ttft"]
                else:
                    if not result.get("completion_tokens"):
                        raise ValueError("reply missing token counts")
                    score = TS.normalized_tps(completion_tokens=result["completion_tokens"],
                        total_s=result.get("total_s", result["elapsed"]),
                        prefill_s=result.get("prefill_s") or 0)
            scores.append(score)
        return scores

    def _run_safe(self):
        self.best, self.current, self.pinned = {}, {}, set()
        self.dirty_reload, self.owns_pause = False, False
        complete = False
        failure = None
        try:
            self._boundary()
            active = self.mgr.lead_active_settings() or {}
            active["kv_quant_supported"] = TS.kv_quant_supported(self.mgr._lead_path)
            self.fp = AB.fingerprint(self.mgr.optimize_hardware(), split=self.mgr.snapshot().get("split"))
            self.pinned = set(active.get("pinned") or [])
            self.mgr.sweep({"pause": True})
            self.owns_pause = True
            _, entry = self.mgr._tuned_entry(self.mgr._lead_path, create=True)
            self.best = AB.baseline(entry, active, self.settings)
            self.current = AB.baseline({}, active)
            items = AB.schedule(entry, self.settings, active, self.fp, n_layers=active.get("n_layers"))
            self._set(schedule=items)
            self._hold(self.best)
            if any(self.current.get(n) != v for n, v in self.best.items() if n not in AB.LIVE):
                self.dirty_reload = True
                self._reload(self.best)
                self.dirty_reload = False
            for item in items:
                if item["skip"]:
                    self._log("skip " + item["name"] + ": " + item["skip"])
                    continue
                self._boundary()
                item["state"] = "running"
                self._set(schedule=copy.deepcopy(items))
                name, inc, ch = item["name"], item["incumbent"], item["challenger"]
                self._log(f"A/B {name}: {inc} vs {ch}; all other values held")
                self._apply(name, inc)
                a = self._measure(name, "incumbent")
                self._apply(name, ch)
                b = self._measure(name, "challenger")
                self._boundary()  # Cancel during the last reply must not commit.
                winner, lost = (ch, inc) if AB.pick(a, b) else (inc, ch)
                result = dict(name=name, incumbent=inc, challenger=ch,
                              incumbent_scores=a, challenger_scores=b, winner=winner, lost=lost)
                self.mgr.sweep({"commit": dict(name=name, winner=winner, lost=lost,
                    fingerprint=self.fp, measurements=result)})
                self.best[name] = winner
                if self.current.get(name) != winner:
                    self._apply(name, winner)
                self.dirty_reload = False
                item["state"] = "kept"
                item["winner"] = winner
                self._set(schedule=copy.deepcopy(items), results=self.state["results"] + [result])
                self._log(f"kept {name}={winner}; lost {lost}")
            complete = True
        except Canceled:
            pass
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
            self._log(failure)
        finally:
            if self.owns_pause:
                try:
                    reload_drift = any(self.current.get(n) != v for n, v in self.best.items() if n not in AB.LIVE)
                    if self.dirty_reload or reload_drift:
                        self._reload(self.best, restoring=True)
                    self._hold(self.best)
                    self.mgr.sweep({"release": True})
                except Exception as error:
                    failure = (failure + "; " if failure else "") + "restore failed: " + str(error)
                    self._log(failure)
            canceled = self._cancel.is_set()
            self._set(running=False, paused=False, error=failure,
                      phase="stopped (error)" if failure else "canceled" if canceled else "done",
                      eta_s=0 if complete else None,
                      summary=dict(winner=self.best, complete=complete and not failure and not canceled,
                                   prompts=self.state["prompts"], reloads=self.state["reloads"],
                                   minutes=round((time.time() - self.state["started"]) / 60, 2)))
