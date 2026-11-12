"""Walk-away tuning: paired arms, one knob at a time; ordinary Auto is separate."""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import optimize_schedule as AB
import tuned_settings as TS
import web_settings
import web_tune_errors

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


def experimental_settings(settings, values):
    """Page settings for a reload with native MTP / adaptive lookup on or off."""
    s = dict(settings or {})
    if "native_mtp" in values:
        if values["native_mtp"]:
            s["guess_ahead"] = "mtp"
        elif s.get("guess_ahead") == "mtp":
            s["guess_ahead"] = "auto"
    if "adaptive_lookup" in values:
        if values["adaptive_lookup"]:
            s["prompt_lookup"] = "adaptive"
            s["pipeline_chats"] = "1"
        elif s.get("prompt_lookup") == "adaptive":
            s["prompt_lookup"] = "auto"
    return s


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
                          schedule=[], results=[], log=[], summary=None, error=None,
                          error_detail=None, source=None, paused=False)

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

    def start(self, mode="now", source="optimize_now", fresh=True):
        # Accept legacy clients, but never resurrect Deep/Quick coverage.
        # fresh=True (the Tune again button, and the default): retry even if a
        # previous pass already recorded losses or the page has pins, so a
        # second press is not a silent no-op. No unload or redownload.
        with self._lock:
            if self.state["running"]:
                raise RuntimeError("optimize already running")
            snap = self.mgr.snapshot()
            if snap.get("status") != "ready" or not snap.get("model_id"):
                raise RuntimeError("load a model first")
            settings = web_settings.normalize(snap.get("settings") or {})
            active = self.mgr.lead_active_settings()
            # A split start can leave the worker with learning off even when
            # Self-tuning is On. Turn learning on live, then continue.
            if ((not active or not active.get("self_tune", True))
                    and settings.get("self_tune") != "off"
                    and hasattr(self.mgr, "set_self_tune")):
                try:
                    self.mgr.set_self_tune("auto")
                    active = self.mgr.lead_active_settings() or active
                except Exception:
                    pass
            if not active or not active.get("self_tune", True):
                raise RuntimeError("Optimize now needs an MLX model with Auto learning on")
            if (settings.get("guess_ahead") == "mtp" or
                    settings.get("prompt_lookup") == "adaptive"):
                raise RuntimeError("turn off native MTP / adaptive lookup before Optimize now")
            self.model_id = snap["model_id"]
            self.settings = settings
            self.fresh = bool(fresh)
            self.entry = copy.deepcopy(getattr(self.mgr, "_loaded_entry", None))
            self._cancel.clear()
            self._pause.clear()
            self.source = source or "optimize_now"
            self._set(running=True, mode="now", phase="starting", prompts=0, reloads=0,
                      started=time.time(), eta_s=None, reply_s=None, reload_s=None,
                      schedule=[], results=[], log=[], summary=None, error=None,
                      error_detail=None, source=self.source, paused=False)
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
        settings = experimental_settings(self.settings, values)
        t0 = time.monotonic()
        self.mgr.switch(self.model_id, wait=True, settings=settings,
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
        try:
            with urlopen(req, timeout=600) as response:
                usage = json.loads(response.read()).get("usage") or {}
        except (HTTPError, URLError) as exc:
            # Re-raise so the run stops and restores; body is kept for the log.
            if isinstance(exc, HTTPError):
                web_tune_errors.http_body(exc)
            raise
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
        self._note_tune_sample(result)
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
                    self._note_tune_sample(result)
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

    def _specs_from_reply(self, result):
        """Token rate and first-token time, plus any other fields the reply has."""
        if not isinstance(result, dict):
            return {}
        ttft = result.get("ttft") if result.get("ttft") else result.get("ttft_s")
        tokens = result.get("completion_tokens")
        prompt = result.get("prompt_tokens")
        total = result.get("total_s", result.get("elapsed"))
        prefill = result.get("prefill_s") or 0
        write = None
        read = result.get("read_tok_s")
        try:
            if tokens and total is not None:
                decode = max(float(total) - float(prefill or 0), 0.001)
                write = float(tokens) / decode
        except (TypeError, ValueError):
            write = None
        try:
            if read is None and prompt and prefill:
                read = float(prompt) / max(float(prefill), 0.001)
        except (TypeError, ValueError):
            read = None
        return {
            "write_tok_s": write,
            "ttft_s": ttft,
            "completion_tokens": tokens,
            "prompt_tokens": prompt,
            "read_tok_s": read,
            "total_s": total,
        }

    def _mean_specs(self, samples):
        def avg(key):
            vals = [s[key] for s in samples if s.get(key) is not None]
            return (sum(vals) / len(vals)) if vals else None
        return {
            "write_tok_s": avg("write_tok_s"),
            "ttft_s": avg("ttft_s"),
            "completion_tokens": avg("completion_tokens"),
            "prompt_tokens": avg("prompt_tokens"),
            "read_tok_s": avg("read_tok_s"),
            "total_s": avg("total_s"),
        }

    def _note_tune_sample(self, result):
        """Stash a trial reply so before/after can be taken without extra sends."""
        samples = getattr(self, "_tune_samples", None)
        if samples is None:
            return
        if not isinstance(result, dict):
            result = {"elapsed": float(result)}
        samples.append((dict(self.current), self._specs_from_reply(result)))

    def _specs_for_settings(self, settings):
        settings = settings or {}
        picked = [
            specs for cur, specs in (getattr(self, "_tune_samples", None) or [])
            if all(cur.get(k) == v for k, v in settings.items())
        ]
        return self._mean_specs(picked)

    def _sample_speed(self, n=2):
        """Measure current settings without bumping the public prompt counter."""
        samples = []
        for i in range(n):
            self._boundary()
            result = self._send(prompt_plan(i))
            if not isinstance(result, dict):
                result = {"elapsed": float(result)}
            samples.append(self._specs_from_reply(result))
        return self._mean_specs(samples)

    def _chat_average_specs(self):
        try:
            import web_speed
            avg = web_speed.get(self.model_id, self.settings)
        except Exception:
            return {}
        if not avg or not avg.get("count"):
            return {}
        return {
            "write_tok_s": avg.get("write_tok_s"),
            "ttft_s": avg.get("ttft_s"),
            "prompt_tokens": avg.get("prompt_tokens"),
            "completion_tokens": avg.get("completion_tokens"),
            "read_tok_s": avg.get("read_tok_s"),
            "total_s": avg.get("total_s"),
        }

    def _schedule(self, entry, settings, active, fp, *, n_layers=None, fresh=True):
        """Plan one-option trials. A fresh run retries earlier losses and pins."""
        entry = copy.deepcopy(entry or {})
        settings = dict(settings or {})
        active = dict(active or {})
        if fresh:
            for rec in (entry.get("optimize_hardware") or {}).values():
                if isinstance(rec, dict):
                    rec["losses"] = []
            # Trial every available option, including ones the page currently
            # pins. Capability skips (unavailable, blocked) still apply.
            settings = web_settings.normalize({})
            active["pinned"] = []
        return AB.schedule(entry, settings, active, fp, n_layers=n_layers)

    def _record_tune_result(self, before, after, source="optimize_now", unchanged=False):
        try:
            import web_speed
            return web_speed.record_tuning(
                self.model_id, before=before, after=after, source=source,
                unchanged=unchanged)
        except Exception:
            return None

    def _run_safe(self):
        self.best, self.current, self.pinned = {}, {}, set()
        self.dirty_reload, self.owns_pause = False, False
        complete = False
        failure = None
        try:
            self._boundary()
            active = self.mgr.lead_active_settings() or {}
            active["kv_quant_supported"] = TS.kv_quant_supported(self.mgr._lead_path)
            # Day 18: native MTP and adaptive lookup sweeps (both start off).
            active["split"] = bool(self.mgr.snapshot().get("split"))
            active["native_mtp_on_disk"] = bool((self.entry or {}).get("native_mtp_available"))
            active["native_mtp"] = active.get("guess_ahead_mode") == "native_mtp" and bool(active.get("native_mtp_available"))
            pl = active.get("prompt_lookup")
            active["adaptive_lookup"] = bool(pl.get("adaptive")) if isinstance(pl, dict) else None
            self.fp = AB.fingerprint(self.mgr.optimize_hardware(), split=self.mgr.snapshot().get("split"))
            self.pinned = set(active.get("pinned") or [])
            self.mgr.sweep({"pause": True})
            self.owns_pause = True
            _, entry = self.mgr._tuned_entry(self.mgr._lead_path, create=True)
            self.best = AB.baseline(entry, active, self.settings)
            self.current = AB.baseline({}, active)
            items = self._schedule(entry, self.settings, active, self.fp,
                                   n_layers=active.get("n_layers"),
                                   fresh=getattr(self, "fresh", True))
            self._set(schedule=items)
            self._hold(self.best)
            if any(self.current.get(n) != v for n, v in self.best.items() if n not in AB.LIVE):
                self.dirty_reload = True
                self._reload(self.best)
                self.dirty_reload = False
            # Baseline: prefer the chat average from before this run; otherwise
            # use incumbent trial replies already sent during A/B (no extra send,
            # so "exactly one option running" snapshots stay valid).
            self._tune_samples = []
            self._tune_initial = dict(self.best)
            self._tune_before = self._chat_average_specs()
            try:
                import web_speed
                web_speed.snapshot_pending_before(self.model_id, self._tune_before)
            except Exception:
                pass
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
                if name in AB.EXPERIMENTAL and self.current.get(name):
                    # The experimental worker runs with --no-learn and can't record;
                    # go back to the normal worker to commit, then apply the winner.
                    self._apply(name, False)
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
            failure_detail = web_tune_errors.detail_of(error)
            source = getattr(self, "source", None) or self.state.get("source") or "optimize_now"
            failure = web_tune_errors.plain_tune_error(
                error, schedule=self.state.get("schedule"),
                source=source, detail=failure_detail)
            self._log(failure_detail)
            web_tune_errors.log_tune_error(failure_detail, source=source)
            self._set(error_detail=failure_detail)
        finally:
            if self.owns_pause:
                try:
                    reload_drift = any(self.current.get(n) != v for n, v in self.best.items() if n not in AB.LIVE)
                    if self.dirty_reload or reload_drift:
                        self._reload(self.best, restoring=True)
                    self._hold(self.best)
                except Exception as error:
                    extra = "restore failed: " + str(error)
                    raw = ((self.state.get("error_detail") or "") + "; " + extra).strip("; ")
                    self._set(error_detail=raw)
                    self._log(extra)
                    web_tune_errors.log_tune_error(raw, source=getattr(self, "source", None) or "optimize_now")
                    failure = web_tune_errors.plain_tune_error(
                        extra, schedule=self.state.get("schedule"),
                        source=getattr(self, "source", None) or "optimize_now",
                        detail=raw)
                finally:
                    # Even a preflight/recovery failure can leave the original
                    # healthy worker alive. Never strand it in sweep pause.
                    try:
                        self.mgr.sweep({"release": True})
                    except Exception as error:
                        extra = "release failed: " + str(error)
                        raw = ((self.state.get("error_detail") or "") + "; " + extra).strip("; ")
                        self._set(error_detail=raw)
                        self._log(extra)
                        web_tune_errors.log_tune_error(raw, source=getattr(self, "source", None) or "optimize_now")
                        failure = web_tune_errors.plain_tune_error(
                            extra, schedule=self.state.get("schedule"),
                            source=getattr(self, "source", None) or "optimize_now",
                            detail=raw)
            canceled = self._cancel.is_set()
            if complete and not failure and not canceled:
                try:
                    import web_speed
                    schedule = self.state.get("schedule") or []
                    kept = any(i.get("state") == "kept" for i in schedule)
                    before = getattr(self, "_tune_before", None) or {}
                    if not (before.get("write_tok_s") or before.get("ttft_s")):
                        before = self._specs_for_settings(
                            getattr(self, "_tune_initial", self.best))
                    after = self._specs_for_settings(self.best) if kept else dict(before or {})
                    same = (not kept) or web_speed.tuning_bodies_match(before, after)
                    self._record_tune_result(before, after, unchanged=same)
                    if same:
                        self._log(web_speed.NOTHING_FASTER)
                except Exception:
                    pass
            self._set(running=False, paused=False, error=failure,
                      phase="stopped (error)" if failure else "canceled" if canceled else "done",
                      eta_s=0 if complete else None,
                      summary=dict(winner=self.best, complete=complete and not failure and not canceled,
                                   prompts=self.state["prompts"], reloads=self.state["reloads"],
                                   minutes=round((time.time() - self.state["started"]) / 60, 2)))
