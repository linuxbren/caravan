"""Optimize now for GGUF models (Day 18): wraps gguf_tune.GgufTuner in the
same snapshot shape the MLX Optimizer reports (phase, prompts, reloads,
schedule, eta_s, summary) so the existing Optimize now panel renders it.

Each option costs 2 reloads + 2 measurements (2 prompts each). The reload is a
full GGUF relaunch with an explicit tune (entry["tune_override"]). The tuner
and its hooks are injectable so this is unit-tested with fakes."""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path

import gguf_split as G
import gguf_tune as GT


class GgufOptimizer:
    def __init__(self, mgr, *, inflight=lambda: 0, tuner_cls=None, measure=None,
                 sleep=time.sleep, store_path=None):
        self.mgr, self.inflight, self._sleep = mgr, inflight, sleep
        self.tuner_cls = tuner_cls or GT.GgufTuner
        self._measure_fn = measure
        self.store_path = store_path
        self._cancel, self._pause = threading.Event(), threading.Event()
        self._lock = threading.RLock()
        self._thread = None
        self.state = self._blank()

    @staticmethod
    def _blank():
        return dict(running=False, mode=None, backend="llama", phase="idle", prompts=0,
                    reloads=0, started=None, eta_s=None, reply_s=None, reload_s=None,
                    schedule=[], results=[], log=[], summary=None, error=None, paused=False)

    def snapshot(self):
        with self._lock:
            out = copy.deepcopy(self.state)
        todo = [i for i in out["schedule"] if i["state"] in ("pending", "running")]
        if out["running"] and out["reload_s"] is not None and out["reply_s"] is not None:
            left = 0.0
            for i in todo:
                n = 2 - int(i.get("done_arms") or 0)
                left += n * (out["reload_s"] + 2 * out["reply_s"])
            out["eta_s"] = round(left + out["reload_s"])  # + final restore of the winner
        return out

    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    def _log(self, msg):
        with self._lock:
            self.state["log"] = (self.state["log"] + [{"t": time.time(), "msg": msg}])[-60:]
        self._on_log(msg)

    def start(self, source="optimize_now"):
        with self._lock:
            if self.state["running"]:
                raise RuntimeError("optimize already running")
            self.source = source or "optimize_now"
            snap = self.mgr.snapshot()
            entry = copy.deepcopy(getattr(self.mgr, "_loaded_entry", None) or {})
            if snap.get("status") != "ready" or not snap.get("model_id"):
                raise RuntimeError("load a model first")
            if snap.get("backend") != "llama" or entry.get("source") != "gguf":
                raise RuntimeError("GGUF Optimize now needs a GGUF model loaded")
            self.entry, self.model_id = entry, snap["model_id"]
            self.settings = snap.get("settings") or {}
            nodes = (snap.get("gguf") or {}).get("nodes") or [None]
            self.n_minis = max(1, len(nodes))
            self.path = Path(entry["lead_path"]).expanduser()
            store = GT.load_store(self.store_path)
            e = GT.entry(store, GT.entry_key(self.path, self.n_minis))
            sched = [{"name": i["name"], "state": "skipped" if i["skip"] else "pending",
                      "skip": i["skip"], "reload": True, "incumbent": i["incumbent"],
                      "challenger": i["challenger"], "winner": None, "done_arms": 0}
                     for i in G.gguf_schedule(e["best"], e["losses"])]
            self._cancel.clear(); self._pause.clear()
            self.state = self._blank()
            self._set(running=True, mode="now", phase="starting", started=time.time(), schedule=sched)
            self._thread = threading.Thread(target=self._run_safe, daemon=True)
            self._thread.start()
            return self.snapshot()

    def cancel(self):
        self._cancel.set(); self._pause.clear()
        self._log("cancel requested; the current step finishes, then the best settings reload")
        return self.snapshot()

    def pause(self, paused=True):
        (self._pause.set if paused else self._pause.clear)()
        self._set(paused=bool(paused))
        return self.snapshot()

    # --- hooks given to the tuner ---
    def _current(self):
        for i in self.state["schedule"]:
            if i["state"] in ("running", "pending"):
                return i
        return None

    def _boundary(self):
        while (self._pause.is_set() or self.inflight() > 0) and not self._cancel.is_set():
            self._set(phase="paused" if self._pause.is_set() else "waiting for your chat")
            self._sleep(0.1)

    def _restart(self, tune):
        self._boundary()
        with self._lock:
            cur = self._current()
            if cur and not self._cancel.is_set():
                cur["state"] = "running"
                label = f"reloading with {cur['name']}={tune.get(cur['name'])}"
            else:
                label = "reloading with the best settings"
            self.state["phase"] = label
        t0 = time.time()
        self.mgr.switch(self.model_id, wait=True, settings=self.settings,
                        entry=dict(self.entry, tune_override=dict(tune)))
        snap = self.mgr.snapshot()
        if snap.get("status") != "ready":
            raise RuntimeError(snap.get("error") or "reload failed")
        dt = time.time() - t0
        with self._lock:
            self.state["reloads"] += 1
            r = self.state["reload_s"]
            self.state["reload_s"] = round(dt if r is None else (r + dt) / 2, 1)

    def _measure(self):
        self._set(phase="measuring")
        t0 = time.time()
        raw = (self._measure_fn or (lambda: GT.measure_http_specs(self.mgr.lead_port)))()
        dt = time.time() - t0
        with self._lock:
            self.state["prompts"] += len(GT.BENCH_PROMPTS)
            per = dt / len(GT.BENCH_PROMPTS)
            r = self.state["reply_s"]
            self.state["reply_s"] = round(per if r is None else (r + per) / 2, 1)
            cur = self._current()
            if cur:
                cur["done_arms"] = int(cur.get("done_arms") or 0) + 1
        return raw

    def _on_log(self, msg):
        # gguf_tune logs "gguf tune: <name> ... -> keep X|stay Y" after each option.
        if not msg.startswith("gguf tune: ") or "->" not in msg:
            return
        name = msg[len("gguf tune: "):].split(" ", 1)[0]
        with self._lock:
            for i in self.state["schedule"]:
                if i["name"] == name and i["state"] in ("running", "pending"):
                    i["state"] = "kept"
                    i["winner"] = msg.rsplit("-> ", 1)[-1].split(" ", 1)[-1]
                    break

    def _run_safe(self):
        try:
            tuner = self.tuner_cls(self.path, self.n_minis, restart=self._restart,
                                   measure=self._measure, store_path=self.store_path,
                                   log=self._log, cancelled=self._cancel.is_set)
            res = tuner.run()
            status = res.get("status") or "done"
            source = getattr(self, "source", "optimize_now") or "optimize_now"
            if res.get("before") and res.get("after") and getattr(self, "model_id", None):
                try:
                    import web_speed
                    web_speed.record_tuning(
                        self.model_id,
                        before=res["before"], after=res["after"],
                        source=source,
                    )
                except Exception as ex:  # noqa: BLE001
                    self._log(f"could not save before/after: {ex}")
            self._set(results=res.get("tried") or [],
                      error=None if status in ("done", "cancelled") else status,
                      summary={"complete": status == "done", "winner": res.get("best") or {},
                               "minutes": round((time.time() - self.state["started"]) / 60, 1),
                               "before": res.get("before"), "after": res.get("after")})
        except Exception as e:  # noqa: BLE001
            self._set(error=f"{type(e).__name__}: {e}")
        finally:
            with self._lock:
                for i in self.state["schedule"]:
                    if i["state"] in ("running", "pending"):
                        i["state"] = "skipped"; i["skip"] = i["skip"] or "not run"
            self._set(running=False, phase="done", paused=False, eta_s=None)
