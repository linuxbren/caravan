"""Day 15: Quick / Deep optimize — Caravan feeds itself prompts until tuned.

Quick: live options only (guess-ahead, shared start, two chats). No reloads
except one at the start if those options are pinned.
Deep: Quick plus reload options (memory compression, fused kernels, GPU
keep-warm). Between trials it reloads the model itself, but only when no chat
is in flight. Cancel any time; a reload already started finishes first.

Everything is scored by the worker's normal self-tuning (tuned_settings.py);
this runner only supplies prompts, reloads when a trial is queued, and reports
progress. Winners stay saved as the learned settings for that model.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Callable, Optional
from urllib.request import Request, urlopen

import tuned_settings as TS
import web_settings

# Fixed prompt set: short, long, predictable (guess-ahead friendly), and a long
# shared opening (> 512 tokens) so shared start has something to reuse.
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
MAX_PROMPTS = {"quick": 60, "deep": 180}
STALL_AFTER = 30  # prompts with no new coverage => stop and say so


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
    """Options this model/setup can't vary (skip in coverage)."""
    a = active or {}
    out = set()
    if not a.get("guess_ahead_loaded"):
        out.add("guess_ahead")
    if a.get("keepalive") is None:  # single Mini: no keep-warm, no two-chat pipe
        out |= {"keepalive", "pipeline_chats"}
    return out


def eta_s(cov: dict, *, mode: str, reply_s: Optional[float], reload_s: Optional[float]) -> Optional[float]:
    """Rough time left from measured reply and reload times. None until measured."""
    if reply_s is None:
        return None
    per = {}
    for it in cov.get("items") or []:
        per.setdefault(it["name"], 0)
        per[it["name"]] += max(0, it["need"] - it["have"])
    replies_left = max(per.values() or [0])
    t = replies_left * reply_s
    if mode == "deep":
        reloads_left = sum(1 for n in TS.RELOAD_TRIO for it in cov["items"]
                           if it["name"] == n and it["have"] < it["need"])
        if reloads_left:
            t += (reloads_left + 1) * (reload_s if reload_s is not None else 0)
            if reload_s is None:
                return None
    return t


class Optimizer:
    def __init__(self, mgr, *, inflight: Callable[[], int],
                 send: Optional[Callable] = None, sleep=time.sleep):
        self.mgr = mgr
        self.inflight = inflight      # user chats in flight right now
        self._send = send or self._http_send
        self._sleep = sleep
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.state = {"running": False, "mode": None, "phase": "idle", "prompts": 0,
                      "reloads": 0, "started": None, "eta_s": None, "reply_s": None,
                      "reload_s": None, "coverage": None, "log": [], "summary": None,
                      "error": None}

    # ---- public ----
    def snapshot(self) -> dict:
        with self._lock:
            s = dict(self.state)
            s["log"] = list(self.state["log"][-30:])
        return s

    def start(self, mode: str = "deep") -> dict:
        mode = "quick" if mode == "quick" else "deep"
        if self._thread and self._thread.is_alive():
            raise RuntimeError("optimize already running")
        snap = self.mgr.snapshot()
        if snap.get("status") != "ready" or not snap.get("model_id"):
            raise RuntimeError("load a model first")
        self._cancel.clear()
        self._set(running=True, mode=mode, phase="starting", prompts=0, reloads=0,
                  started=time.time(), eta_s=None, reply_s=None, reload_s=None,
                  summary=None, error=None, log=[])
        self._thread = threading.Thread(target=self._run_safe, args=(mode,), daemon=True)
        self._thread.start()
        return self.snapshot()

    def cancel(self) -> dict:
        self._cancel.set()
        self._log("cancel requested")
        return self.snapshot()

    # ---- internals ----
    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    def _log(self, msg: str):
        with self._lock:
            self.state["log"].append({"t": round(time.time(), 1), "msg": msg})
            self.state["log"] = self.state["log"][-60:]

    def _settings_for(self, mode: str) -> dict:
        cur = web_settings.normalize(self.mgr.snapshot().get("settings") or {})
        want = dict(cur)
        want["self_tune"] = "auto"
        for k in ("guess_ahead", "shared_start", "pipeline_chats"):
            want[k] = "auto"
        if mode == "deep":
            for k in ("fuse_kernels", "kv_bits", "keepalive"):
                want[k] = "auto"
        return want

    def _reload(self, settings: dict, why: str):
        model_id = self.mgr.snapshot().get("model_id")
        while self.inflight() > 0 and not self._cancel.is_set():
            self._set(phase="waiting for your chat to finish before reloading")
            self._sleep(2)
        self._set(phase=f"reloading to {why}")
        self._log(f"reloading to {why}")
        t0 = time.time()
        self.mgr.switch(model_id, wait=True, settings=settings)
        dt = time.time() - t0
        snap = self.mgr.snapshot()
        if snap.get("status") != "ready":
            raise RuntimeError(f"reload failed: {snap.get('error')}")
        st = self.state
        n = st["reloads"]
        avg = dt if st["reload_s"] is None else (st["reload_s"] * n + dt) / (n + 1)
        self._set(reloads=n + 1, reload_s=round(avg, 1))
        self._log(f"reloaded in {dt:.0f}s")

    def _entry_and_active(self):
        active = self.mgr.lead_active_settings()
        try:
            _, e = self.mgr._tuned_entry(self.mgr._lead_path)
        except (OSError, ValueError, TypeError):
            e = None
        return e, active

    def _http_send(self, messages: list, max_tokens: int = 160) -> float:
        body = json.dumps({"messages": messages, "max_tokens": max_tokens,
                           "stream": False}).encode()
        req = Request(f"http://127.0.0.1:{self.mgr.lead_port}/v1/chat/completions",
                      data=body, method="POST",
                      headers={"Content-Type": "application/json",
                               "X-Caravan-Session": "opt-" + uuid.uuid4().hex[:12]})
        t0 = time.time()
        with urlopen(req, timeout=600) as r:
            r.read()
        return time.time() - t0

    def _run_safe(self, mode):
        try:
            self._run(mode)
        except Exception as e:  # noqa: BLE001 — surface to UI
            self._set(error=f"{type(e).__name__}: {e}", phase="stopped (error)")
            self._log(f"error: {e}")
        finally:
            self._set(running=False)

    def _run(self, mode: str):
        settings = self._settings_for(mode)
        cur = web_settings.normalize(self.mgr.snapshot().get("settings") or {})
        if settings != cur:
            pinned = [k for k in settings if settings[k] != cur[k]]
            self._reload(settings, "set " + ", ".join(pinned) + " to Auto")
        best_missing, since_gain, i = None, 0, 0
        while not self._cancel.is_set():
            e, active = self._entry_and_active()
            cov = TS.coverage(e, mode=mode, pinned=unavailable(active))
            self._set(coverage=cov, eta_s=eta_s(cov, mode=mode, reply_s=self.state["reply_s"],
                                                 reload_s=self.state["reload_s"]))
            if cov["done"]:
                break
            if best_missing is None or cov["missing"] < best_missing:
                best_missing, since_gain = cov["missing"], 0
            elif since_gain >= STALL_AFTER:
                self._log(f"no new coverage in {STALL_AFTER} prompts; stopping")
                break
            if i >= MAX_PROMPTS[mode]:
                self._log(f"hit the {MAX_PROMPTS[mode]}-prompt cap; stopping")
                break
            if mode == "deep":
                rs = TS.reload_status(e, active, (active or {}).get("reload_auto") or [])
                tries = [c for c in rs["reload_wanted"] if c["why"] == "try"]
                if tries or (rs["reload_wanted"] and not rs["trial"]):
                    c = (tries or rs["reload_wanted"])[0]
                    verb = "try" if c["why"] == "try" else "go back to"
                    self._reload(settings, f"{verb} {c['label']} {c['to']}")
                    continue
            while self.inflight() > 0 and not self._cancel.is_set():
                self._set(phase="paused while your chat runs")
                self._sleep(1)
            msgs = prompt_plan(i)
            self._set(phase=f"prompt {i + 1}")
            if i % 5 == 4:
                # Two chats at once so "two chats" gets concurrent samples.
                res = []
                th = [threading.Thread(target=lambda m=m: res.append(self._send(m)))
                      for m in (msgs, prompt_plan(i + 2))]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                dt = max(res) if res else 0.0
            else:
                dt = self._send(msgs)
            n = self.state["prompts"]
            avg = dt if self.state["reply_s"] is None else (self.state["reply_s"] * n + dt) / (n + 1)
            self._set(prompts=n + 1, reply_s=round(avg, 2))
            i += 1
            since_gain += 1
        # Finish on the winners (one last reload if the model is on a trial value).
        e, active = self._entry_and_active()
        if mode == "deep" and not self._cancel.is_set():
            rs = TS.reload_status(e, active, (active or {}).get("reload_auto") or [])
            back = [c for c in rs["reload_wanted"] if c["why"] == "back to winner"]
            if back:
                self._reload(settings, "finish on the winners")
                e, active = self._entry_and_active()
        cov = TS.coverage(e, mode=mode, pinned=unavailable(active))
        self._set(coverage=cov, eta_s=0 if cov["done"] else None,
                  phase="canceled" if self._cancel.is_set() else ("done" if cov["done"] else "stopped"),
                  summary={"winner": dict((e or {}).get("winner") or {}),
                           "prompts": self.state["prompts"], "reloads": self.state["reloads"],
                           "minutes": round((time.time() - self.state["started"]) / 60, 1),
                           "complete": cov["done"]})
        self._log("done" if cov["done"] else "stopped before full coverage")
