"""Optimize now for GGUF models (Day 18): wraps gguf_tune.GgufTuner in the
same snapshot shape the MLX Optimizer reports (phase, prompts, reloads,
schedule, eta_s, summary) so the existing Optimize now panel renders it.

Each option costs 2 reloads + 2 measurements (five short prompts
and one ~2k-token long prompt, skipped if it will not fit the chat window). The reload is a
full GGUF relaunch with an explicit tune (entry["tune_override"]). The tuner
and its hooks are injectable so this is unit-tested with fakes."""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path

import gguf_split as G
import gguf_tune as GT
import web_tune_errors
import web_tune_step


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
                    schedule=[], results=[], log=[], summary=None, error=None,
                    error_detail=None, source=None, paused=False, step=None)

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
        return web_tune_step.decorate(out)

    def _set_step(self, *, action="starting", knob=None, value=None,
                  kind=None, index=None, total=None):
        self._set(step=web_tune_step.format_step(
            action=action, knob=knob, value=value,
            kind=kind, index=index, total=total,
        ))

    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    def _log(self, msg):
        with self._lock:
            self.state["log"] = (self.state["log"] + [{"t": time.time(), "msg": msg}])[-60:]
        self._on_log(msg)

    def _schedule_kw(self) -> dict:
        """Safety gates Auto-tune uses for Prompt lookup: one chat, not pinned."""
        s = dict(getattr(self, "settings", None) or {})
        pinned = set()
        if s.get("prompt_lookup") in ("on", "off"):
            pinned.add("prompt_lookup")
        if s.get("guess_ahead") in ("on", "off"):
            pinned.add("guess_ahead")
        n_slots = 1
        try:
            n_slots = int(s.get("pipeline_chats") or 1)
        except (TypeError, ValueError):
            n_slots = 1
        if n_slots < 1:
            n_slots = 1
        # Two chats pin is "2"; Auto/1 is one chat. A loaded tune may
        # also have n_slots.
        entry = getattr(self, "entry", None) or {}
        tun = entry.get("tune") or entry.get("tune_override") or {}
        if s.get("pipeline_chats") in (None, "", "auto") and tun.get("n_slots"):
            try:
                n_slots = int(tun["n_slots"])
            except (TypeError, ValueError):
                pass
        # Day 27: Guess-ahead is tried only with a helper already on this Mac.
        draft = None
        path = getattr(self, "path", None)
        if path and "guess_ahead" not in pinned:
            try:
                found = G.find_gguf_draft(path)
                draft = (found or {}).get("path")
            except Exception:
                draft = None
        return {"n_slots": n_slots, "pinned": pinned, "draft_path": draft}

    def start(self, source="optimize_now", fresh=True):
        with self._lock:
            if self.state["running"]:
                raise RuntimeError("optimize already running")
            self.source = source or "optimize_now"
            self.fresh = bool(fresh)
            snap = self.mgr.snapshot()
            entry = copy.deepcopy(getattr(self.mgr, "_loaded_entry", None) or {})
            if snap.get("status") != "ready" or not snap.get("model_id"):
                raise RuntimeError("load a model first")
            if snap.get("backend") != "llama" or entry.get("source") != "gguf":
                raise RuntimeError("GGUF Auto-tune needs a GGUF model loaded")
            self.entry, self.model_id = entry, snap["model_id"]
            self.settings = snap.get("settings") or {}
            nodes = (snap.get("gguf") or {}).get("nodes") or [None]
            self.n_minis = max(1, len(nodes))
            self.path = Path(entry["lead_path"]).expanduser()
            store = GT.load_store(self.store_path)
            e = GT.entry(store, GT.entry_key(self.path, self.n_minis))
            # A fresh Tune again retries earlier losses; the on-disk record
            # is only updated when this run itself commits a result.
            losses = [] if self.fresh else list(e.get("losses") or [])
            skw = self._schedule_kw()
            sched = [{"name": i["name"], "state": "skipped" if i["skip"] else "pending",
                      "skip": i["skip"], "reload": True, "incumbent": i["incumbent"],
                      "challenger": i["challenger"], "winner": None, "done_arms": 0}
                     for i in G.gguf_schedule(e["best"], losses, **skw)]
            self._cancel.clear(); self._pause.clear()
            self.state = self._blank()
            self._tune_unchanged = False
            self._set(running=True, mode="now", phase="starting", started=time.time(),
                      schedule=sched, source=self.source,
                      step=web_tune_step.format_step(action="starting"))
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
            self._set(phase="paused" if self._pause.is_set() else "waiting for your chat",
                      step=web_tune_step.format_step(
                          action="paused" if self._pause.is_set() else "waiting"))
            self._sleep(0.1)

    def _restart(self, tune):
        self._boundary()
        with self._lock:
            cur = self._current()
            if cur and not self._cancel.is_set():
                cur["state"] = "running"
                label = f"reloading with {cur['name']}={tune.get(cur['name'])}"
                step = web_tune_step.format_step(
                    action="reloading", knob=cur["name"],
                    value=tune.get(cur["name"]),
                )
            else:
                label = "reloading with the best settings"
                step = web_tune_step.format_step(action="reloading_winner")
            self.state["phase"] = label
            self.state["step"] = step
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
        cur = self._current()
        is_try = int((cur or {}).get("done_arms") or 0) >= 1
        knob = (cur or {}).get("name")
        value = (cur or {}).get("challenger" if is_try else "incumbent")
        action = "trying" if is_try else "measuring"
        self._set_step(action=action, knob=knob, value=value if is_try else None)

        def on_prompt(index, total, kind="short"):
            self._set_step(
                action=action, knob=knob,
                value=value if is_try else None,
                kind=kind, index=index, total=total,
            )

        t0 = time.time()
        window = None
        try:
            import caravan_prompts as P
            window = P.chat_window_from(self.mgr.snapshot() or {})
        except Exception:
            window = None
        if self._measure_fn:
            raw = self._measure_fn()
        else:
            raw = GT.measure_http_specs(
                self.mgr.lead_port, chat_window=window, on_prompt=on_prompt,
            )
        dt = time.time() - t0
        try:
            import caravan_prompts as P
            n_prompts = len(P.autotune_prompt_list(window)[0])
        except Exception:
            n_prompts = len(GT.BENCH_PROMPTS)
        with self._lock:
            self.state["prompts"] += n_prompts
            per = dt / max(n_prompts, 1)
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
            # Real GgufTuner accepts this; test fakes may not.
            if hasattr(tuner, "schedule_kw"):
                tuner.schedule_kw = self._schedule_kw()
            res = tuner.run()
            status = res.get("status") or "done"
            source = getattr(self, "source", "optimize_now") or "optimize_now"
            if res.get("before") and res.get("after") and getattr(self, "model_id", None):
                try:
                    import web_speed
                    same = web_speed.tuning_bodies_match(res["before"], res["after"])
                    self._tune_unchanged = same
                    web_speed.record_tuning(
                        self.model_id,
                        before=res["before"], after=res["after"],
                        source=source, unchanged=same,
                    )
                except Exception as ex:  # noqa: BLE001
                    self._log(f"could not save before/after: {ex}")
            if status in ("done", "cancelled"):
                self._set(results=res.get("tried") or [], error=None, error_detail=None,
                          summary={"complete": status == "done", "winner": res.get("best") or {},
                                   "unchanged": bool(getattr(self, "_tune_unchanged", False)),
                                   "minutes": round((time.time() - self.state["started"]) / 60, 1),
                                   "before": res.get("before"), "after": res.get("after")})
                phase = "done" if status == "done" else "canceled"
            else:
                raw = status
                source = getattr(self, "source", None) or "optimize_now"
                plain = web_tune_errors.plain_tune_error(
                    raw, schedule=self.state.get("schedule"), source=source, detail=raw)
                self._log(raw)
                web_tune_errors.log_tune_error(raw, source=source)
                self._set(results=res.get("tried") or [], error=plain, error_detail=raw,
                          summary={"complete": False, "winner": res.get("best") or {},
                                   "unchanged": False,
                                   "minutes": round((time.time() - self.state["started"]) / 60, 1),
                                   "before": res.get("before"), "after": res.get("after")})
                phase = "stopped (error)"
            self._pending_phase = phase
        except Exception as e:  # noqa: BLE001
            raw = web_tune_errors.detail_of(e)
            source = getattr(self, "source", None) or "optimize_now"
            plain = web_tune_errors.plain_tune_error(
                e, schedule=self.state.get("schedule"), source=source, detail=raw)
            self._log(raw)
            web_tune_errors.log_tune_error(raw, source=source)
            self._set(error=plain, error_detail=raw)
            self._pending_phase = "stopped (error)"
        finally:
            with self._lock:
                for i in self.state["schedule"]:
                    if i["state"] in ("running", "pending"):
                        i["state"] = "skipped"; i["skip"] = i["skip"] or "not run"
            phase = getattr(self, "_pending_phase", "done")
            if self.state.get("error") and phase == "done":
                phase = "stopped (error)"
            end_action = "error" if "error" in str(phase) else (
                "canceled" if "cancel" in str(phase) else "done")
            self._set(running=False, phase=phase, paused=False, eta_s=None,
                      step=web_tune_step.format_step(action=end_action))
