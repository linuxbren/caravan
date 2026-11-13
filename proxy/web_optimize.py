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
import web_tune_step

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


class _Scores(list):
    """A/B scores plus a quality flag the usual sum cannot see."""
    garbled = False


def _arm_quality_bad(scores):
    """True when this arm garbled or failed the load-time quality probe."""
    return bool(getattr(scores, "garbled", False) or getattr(scores, "quality_fail", False))


def _arm_fail_why(scores, who):
    if getattr(scores, "garbled", False):
        return f"{who} garbled"
    if getattr(scores, "quality_fail", False):
        return f"{who} failed the quality check"
    return who


def decide_ab_winner(inc, ch, inc_scores, ch_scores, pick):
    """Pick a winner. A garbled or quality-failed arm is a loss, even if fast."""
    a_bad = _arm_quality_bad(inc_scores)
    b_bad = _arm_quality_bad(ch_scores)
    if b_bad and not a_bad:
        return inc, ch, _arm_fail_why(ch_scores, "challenger")
    if a_bad and not b_bad:
        return ch, inc, _arm_fail_why(inc_scores, "incumbent")
    if a_bad and b_bad:
        a_g = bool(getattr(inc_scores, "garbled", False))
        b_g = bool(getattr(ch_scores, "garbled", False))
        if a_g or b_g:
            return inc, ch, "both garbled"
        return inc, ch, "both failed the quality check"
    if pick(inc_scores, ch_scores):
        return ch, inc, None
    return inc, ch, None



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
                          error_detail=None, source=None, paused=False, step=None)

    def snapshot(self):
        with self._lock:
            out = copy.deepcopy(self.state)
            todo = [i for i in out["schedule"] if i["state"] in ("pending", "running")]
            reloads = sum(2 for i in todo if i["reload"])
            if out["running"] and out["reply_s"] is not None and (not reloads or out["reload_s"] is not None):
                out["eta_s"] = round(len(todo) * AB_ARM * 2 * out["reply_s"] + reloads * (out["reload_s"] or 0))
            return web_tune_step.decorate(out)

    def _set_step(self, *, action="starting", knob=None, value=None,
                  kind=None, index=None, total=None):
        self._set(step=web_tune_step.format_step(
            action=action, knob=knob, value=value,
            kind=kind, index=index, total=total,
        ))

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
            active = self.mgr.lead_active_settings() or {}
            # Auto-tune is independent of Self-tuning: it runs a walk-away
            # trial now, whether learning from chats is on or off.
            if (settings.get("guess_ahead") == "mtp" or
                    settings.get("prompt_lookup") == "adaptive"):
                raise RuntimeError("turn off native MTP / adaptive lookup before Auto-tune")
            self.model_id = snap["model_id"]
            self.settings = settings
            self.fresh = bool(fresh)
            self.entry = copy.deepcopy(getattr(self.mgr, "_loaded_entry", None))
            self._cancel.clear()
            self._pause.clear()
            self.source = source or "optimize_now"
            self._tune_unchanged = False
            self._set(running=True, mode="now", phase="starting", prompts=0, reloads=0,
                      started=time.time(), eta_s=None, reply_s=None, reload_s=None,
                      schedule=[], results=[], log=[], summary=None, error=None,
                      error_detail=None, source=self.source, paused=False,
                      step=web_tune_step.format_step(action="starting"))
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
            self._set(phase="paused" if self._pause.is_set() else "waiting for your chat",
                      step=web_tune_step.format_step(
                          action="paused" if self._pause.is_set() else "waiting"))
            self._sleep(0.1)
        if self._cancel.is_set():
            raise Canceled()
        snap = self.mgr.snapshot()
        if snap.get("model_id") != self.model_id or snap.get("status") != "ready":
            raise RuntimeError("model changed during Auto-tune")

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
        if restoring:
            self._set(phase="restoring winners",
                      step=web_tune_step.format_step(action="reloading_winner"))
        else:
            cur = None
            for i in (self.state.get("schedule") or []):
                if i.get("state") == "running":
                    cur = i
                    break
            knob = (cur or {}).get("name")
            # Reloading to try the challenger of the option now running.
            value = (cur or {}).get("challenger")
            self._set(phase="reloading one option",
                      step=web_tune_step.format_step(
                          action="reloading", knob=knob, value=value))
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
                body = json.loads(response.read())
                usage = (body.get("usage") or {}) if isinstance(body, dict) else {}
        except (HTTPError, URLError) as exc:
            # Re-raise so the run stops and restores; body is kept for the log.
            if isinstance(exc, HTTPError):
                web_tune_errors.http_body(exc)
            raise
        elapsed = time.monotonic() - t0
        detail = usage.get("caravan") or {}
        content = ""
        try:
            for ch in (body.get("choices") or []):
                msg = ch.get("message") or {}
                if isinstance(msg.get("content"), str):
                    content += msg["content"]
        except Exception:
            content = ""
        garbled = False
        try:
            from garble import is_garbled
            garbled = is_garbled(content)
        except Exception:
            garbled = False
        return dict(elapsed=elapsed, ttft=detail.get("ttft_s"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_s=detail.get("total_s", elapsed), prefill_s=detail.get("prefill_s", 0),
                    content=content, garbled=garbled)

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

    def _arm_quality_failed(self):
        """True when the just-loaded arm failed the load-time quality probe."""
        try:
            snap = self.mgr.snapshot() or {}
        except Exception:
            return False
        q = snap.get("quality") or {}
        if q.get("definite") and q.get("ok") is False:
            return True
        return False

    def _measure_or_quality_fail(self, name, arm):
        """Measure this arm, or record a quality-check loss without measuring 16 as 4."""
        if self._arm_quality_failed():
            scores = _Scores()
            scores.quality_fail = True
            self._log(f"{name}: {arm} failed the quality check")
            return scores
        return self._measure(name, arm)

    def _chat_window(self):
        try:
            import caravan_prompts as P
            return P.chat_window_from(self.mgr.snapshot() or {})
        except Exception:
            return None

    def _median_specs(self, samples, kinds=None):
        import gguf_tune as GT
        out = {}
        for key in ("write_tok_s", "read_tok_s", "ttft_s", "total_s",
                    "prompt_tokens", "completion_tokens"):
            vals = [s[key] for s in samples if isinstance(s, dict) and s.get(key) is not None]
            med = GT._median(vals) if vals else None
            if med is not None:
                out[key] = med
        if kinds:
            long_reads = [
                s["read_tok_s"] for s, k in zip(samples, kinds)
                if k == "long" and isinstance(s, dict) and s.get("read_tok_s") is not None
            ]
            if long_reads:
                med = GT._median(long_reads)
                if med is not None:
                    out["long_read_tok_s"] = med
        return out

    def _arm_value(self, name, arm):
        for i in self.state.get("schedule") or []:
            if i.get("name") == name:
                if arm == "challenger":
                    return i.get("challenger")
                return i.get("incumbent")
        return arm

    def _measure(self, name, arm):
        scores = _Scores()
        scores_garbled = False
        if name == "shared_prefix":
            self._boundary()
            self._one(prompt_plan(0))  # seed shared prefix; cold store is not a hit
            for i in range(AB_ARM):
                self._boundary()
                self._set(phase=f"A/B {name}: {arm} {i + 1}/{AB_ARM}")
                self._set_step(
                    action="trying" if arm == "challenger" else "measuring",
                    knob=name, value=self._arm_value(name, arm),
                    kind="short", index=i + 1, total=AB_ARM,
                )
                result = self._one(prompt_plan(0))
                if isinstance(result, dict) and result.get("garbled"):
                    scores_garbled = True
                if not result.get("ttft") or result["ttft"] <= 0:
                    raise ValueError("reply missing TTFT")
                scores.append(1.0 / result["ttft"])
            if scores_garbled:
                scores.garbled = True
            return scores
        if name == "pipeline_chats":
            for i in range(AB_ARM):
                self._boundary()
                self._set(phase=f"A/B {name}: {arm} {i + 1}/{AB_ARM}")
                self._set_step(
                    action="trying" if arm == "challenger" else "measuring",
                    knob=name, value=self._arm_value(name, arm),
                    kind="short", index=i + 1, total=AB_ARM,
                )
                t0 = time.monotonic()
                # Only this knob needs simultaneous requests, not simultaneous
                # option trials. Same pair is sent to both arm widths.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(self._send, prompt_plan(j + 1)) for j in range(2)]
                    results = [f.result() for f in futures]
                elapsed = time.monotonic() - t0
                for result in results:
                    n = self.state["prompts"]
                    self._set(prompts=n + 1)
                    self._note_tune_sample(result)
                    if isinstance(result, dict) and result.get("garbled"):
                        scores_garbled = True
                ct = sum(r.get("completion_tokens") or 0 for r in results)
                if ct <= 0:
                    raise ValueError("pipeline reply missing token counts")
                scores.append(ct / max(elapsed, 0.001))
            if scores_garbled:
                scores.garbled = True
            return scores
        # Regular knobs: the same five short prompts as bench, plus one
        # ~2k-token long prompt if it fits, each with a unique opening.
        import caravan_prompts as P
        import gguf_tune as GT
        prompts, kinds, _note = P.autotune_prompt_list(self._chat_window())
        samples = []
        for i, prompt in enumerate(prompts):
            self._boundary()
            self._set(phase=f"A/B {name}: {arm} {i + 1}/{len(prompts)}")
            kind = kinds[i] if i < len(kinds) else "short"
            if kind == "long":
                self._set_step(
                    action="trying" if arm == "challenger" else "measuring",
                    knob=name, value=self._arm_value(name, arm),
                    kind="long",
                )
            else:
                n_short = sum(1 for k in kinds if k != "long")
                short_i = sum(1 for k in kinds[:i + 1] if k != "long")
                self._set_step(
                    action="trying" if arm == "challenger" else "measuring",
                    knob=name, value=self._arm_value(name, arm),
                    kind="short", index=short_i, total=n_short or len(prompts),
                )
            result = self._one([{"role": "user", "content": prompt}])
            if isinstance(result, dict) and result.get("garbled"):
                scores_garbled = True
            samples.append(self._specs_from_reply(result) if isinstance(result, dict) else {})
        specs = self._median_specs(samples, kinds)
        if not (specs.get("write_tok_s") or specs.get("completion_tokens")):
            raise ValueError("reply missing token counts")
        score = GT.combined_score(specs)
        if score <= 0:
            raise ValueError("reply missing token counts")
        scores.append(score)
        if scores_garbled:
            try:
                scores.garbled = True
            except Exception:
                pass
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
            try:
                import kv_quality as K
                active["kv_4_supported"] = K.allows_memory_compression_4(
                    model_dir=self.mgr._lead_path)
            except Exception:
                active["kv_4_supported"] = True
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
                a = self._measure_or_quality_fail(name, "incumbent")
                self._apply(name, ch)
                b = self._measure_or_quality_fail(name, "challenger")
                self._boundary()  # Cancel during the last reply must not commit.
                winner, lost, why = decide_ab_winner(inc, ch, a, b, AB.pick)
                if why:
                    self._log(f"{name}: {why}; kept {winner}")
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
                    self._tune_unchanged = same
                except Exception:
                    pass
            finished = complete and not failure and not canceled
            if failure:
                end_action = "error"
                end_phase = "stopped (error)"
            elif canceled:
                end_action = "canceled"
                end_phase = "canceled"
            else:
                end_action = "done"
                end_phase = "done"
            self._set(running=False, paused=False, error=failure,
                      phase=end_phase,
                      step=web_tune_step.format_step(action=end_action),
                      eta_s=0 if complete else None,
                      summary=dict(winner=self.best, complete=finished,
                                   unchanged=bool(getattr(self, "_tune_unchanged", False)),
                                   prompts=self.state["prompts"], reloads=self.state["reloads"],
                                   minutes=round((time.time() - self.state["started"]) / 60, 2)))
