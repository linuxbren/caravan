"""Day 30: finish chat work after a power loss or crash.

Every chat request that reaches the Caravan page (/api/chat and
/v1/chat/completions, streamed or not) is written to a journal on the
1st Mac *before* it is sent to the model, and marked done when the reply
finishes. If the Mac loses power, crashes or Caravan is killed while a
reply is being written, the entry stays unfinished. When the model is
ready again (boot restore, or the next load of the same model), Caravan
runs each unfinished request again **from the start** and saves the
whole reply, so the client can fetch it later:

    GET /api/jobs            recent jobs, newest first (no prompts)
    GET /api/jobs/<id>       one job, with the saved reply
    caravan jobs [<id>]      the same from Terminal

The job id comes back in the `X-Caravan-Job` response header, in an SSE
comment (`: caravan-job <id>`) as the stream's first line, and in the
final `caravan-meta` event / `caravan_web.job` of the reply.

It is not a mid-sentence resume: the words written before the power loss
are thrown away and the model writes the reply again. A replayed reply
can differ from the lost one unless the request pinned a seed and
temperature 0.

Limits: requests older than MAX_AGE_S are not run again ("expired"),
each request is run again at most MAX_REPLAYS times ("gave_up"),
request bodies over MAX_BODY_BYTES are not journaled, and finished jobs
are deleted after KEEP_S (at most MAX_JOBS are kept). A request whose
reply finished is never run again. A request the client cancelled (it
closed the connection) is not run again.

Privacy: the journal holds prompts and replies. It stays on this Mac in
~/.caravan/web-ui/jobs (owner-only permissions) and `caravan uninstall`
removes it with the rest of ~/.caravan. Turn it off with
`[jobs] resume = false` in ~/.caravan/config.toml or
CARAVAN_RESUME_JOBS=0; nothing is written then.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

DEFAULT_DIR = Path.home() / ".caravan" / "web-ui" / "jobs"
MAX_AGE_S = 3600
MAX_REPLAYS = 2
MAX_BODY_BYTES = 4 * 1024 * 1024
KEEP_S = 3 * 24 * 3600
MAX_JOBS = 500

OPEN = ("running", "interrupted")
FINAL = ("done", "failed", "cancelled", "expired", "gave_up", "skipped")
RECOVERED_NOTE = "Finished after a restart"


def enabled(env=None, config_path=None) -> bool:
    """On unless CARAVAN_RESUME_JOBS=0 or [jobs] resume = false."""
    env = os.environ if env is None else env
    v = str(env.get("CARAVAN_RESUME_JOBS", "")).strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    path = Path(config_path or env.get("CARAVAN_CONFIG_TOML") or Path.home() / ".caravan" / "config.toml")
    try:
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib
        cfg = tomllib.loads(path.read_text())
    except (OSError, ValueError, ImportError):
        return True
    jobs = cfg.get("jobs") if isinstance(cfg, dict) else None
    if isinstance(jobs, dict) and jobs.get("resume") is False:
        return False
    return True


def _fsync_dir(path: Path):
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class Journal:
    """One JSON file per job; every write is atomic and fsync'd."""

    def __init__(self, root=None, *, clock=time.time, owner=None):
        self.root = Path(root) if root else DEFAULT_DIR
        self.clock = clock
        self.owner = owner or uuid.uuid4().hex
        self.lock = threading.RLock()

    # ---- storage ---------------------------------------------------------
    def _path(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not job_id.startswith("job_") or "/" in job_id or ".." in job_id:
            raise KeyError(job_id)
        return self.root / (job_id + ".json")

    def _write(self, rec: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        rec["updated"] = self.clock()
        path = self._path(rec["id"])
        tmp = path.with_name(path.name + "." + uuid.uuid4().hex[:8] + ".tmp")
        data = json.dumps(rec, ensure_ascii=False, default=str).encode()
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
        _fsync_dir(self.root)

    def read(self, job_id: str):
        try:
            return json.loads(self._path(job_id).read_text())
        except (OSError, ValueError, KeyError):
            return None

    def all(self) -> list:
        out = []
        try:
            files = list(self.root.glob("job_*.json"))
        except OSError:
            return out
        for f in files:
            try:
                rec = json.loads(f.read_text())
            except (OSError, ValueError):
                continue  # half-written files never exist (atomic rename); skip junk
            if isinstance(rec, dict) and rec.get("id"):
                out.append(rec)
        out.sort(key=lambda r: (r.get("created") or 0, r.get("id")))
        return out

    def _update(self, job_id: str, **changes):
        with self.lock:
            rec = self.read(job_id)
            if rec is None:
                return None
            rec.update(changes)
            self._write(rec)
            return rec

    # ---- lifecycle -------------------------------------------------------
    def begin(self, body: dict, *, endpoint: str, model=None, session=None, stream=False):
        """Journal one request before it is sent. None when too big."""
        try:
            size = len(json.dumps(body, ensure_ascii=False).encode())
        except (TypeError, ValueError):
            return None
        if size > MAX_BODY_BYTES:
            return None
        now = self.clock()
        rec = {
            "id": "job_%d_%s" % (int(now), uuid.uuid4().hex[:10]),
            "version": 1, "status": "running", "created": now,
            "endpoint": endpoint, "model": model, "session": session,
            "stream": bool(stream), "owner": self.owner, "replays": 0,
            "request": body, "request_bytes": size,
        }
        with self.lock:
            self._write(rec)
        return rec

    def finish(self, job_id: str, *, reply="", reasoning="", response=None,
               usage=None, finish_reason=None, recovered=False):
        changes = {"status": "done", "finished": self.clock(), "reply": reply or "",
                   "reasoning": reasoning or "", "usage": usage, "finish_reason": finish_reason,
                   "response": response}
        if recovered:
            changes.update(recovered=True, note=RECOVERED_NOTE, seen=False)
        return self._update(job_id, **changes)

    def interrupt(self, job_id: str, error: str):
        """The reply stopped part-way; run it again when the model is back."""
        rec = self.read(job_id)
        if rec is None or rec.get("status") in FINAL:
            return rec
        return self._update(job_id, status="interrupted", error=str(error)[:500])

    def fail(self, job_id: str, error: str):
        return self._update(job_id, status="failed", finished=self.clock(), error=str(error)[:500])

    def cancel(self, job_id: str):
        return self._update(job_id, status="cancelled", finished=self.clock())

    def mark_seen(self, job_id: str):
        return self._update(job_id, seen=True)

    def pending(self, *, model=None) -> list:
        """Unfinished jobs to run again for `model`, oldest first.

        A `running` job written by this process is live, not lost. Too old
        or too often tried jobs are closed here so they never run again.
        """
        now = self.clock()
        out = []
        with self.lock:
            for rec in self.all():
                st = rec.get("status")
                if st not in OPEN:
                    continue
                if st == "running" and rec.get("owner") == self.owner:
                    continue
                if now - float(rec.get("created") or 0) > MAX_AGE_S:
                    self._update(rec["id"], status="expired", finished=now,
                                 error="older than %d minutes when the model came back; not run again" % (MAX_AGE_S // 60))
                    continue
                if int(rec.get("replays") or 0) >= MAX_REPLAYS:
                    self._update(rec["id"], status="gave_up", finished=now,
                                 error="stopped %d times; not run again" % (MAX_REPLAYS + 1))
                    continue
                if model is not None and rec.get("model") not in (None, model):
                    continue  # waits for its own model (until it expires)
                out.append(rec)
        return out

    def start_replay(self, job_id: str):
        """Count the try *before* running, so a crash mid-replay still counts."""
        with self.lock:
            rec = self.read(job_id)
            if rec is None or rec.get("status") not in OPEN:
                return None
            rec.update(status="running", owner=self.owner,
                       replays=int(rec.get("replays") or 0) + 1, replay_started=self.clock())
            self._write(rec)
            return rec

    def cleanup(self):
        """Delete old finished jobs and stray temp files."""
        now = self.clock()
        removed = 0
        with self.lock:
            try:
                for tmp in self.root.glob("*.tmp"):
                    try:
                        if now - tmp.stat().st_mtime > 60:
                            tmp.unlink()
                    except OSError:
                        pass
            except OSError:
                return 0
            recs = self.all()
            done = [r for r in recs if r.get("status") in FINAL]
            for r in done:
                if now - float(r.get("finished") or r.get("updated") or r.get("created") or 0) > KEEP_S:
                    try:
                        self._path(r["id"]).unlink()
                        removed += 1
                    except (OSError, KeyError):
                        pass
            recs = self.all()
            extra = len(recs) - MAX_JOBS
            for r in [r for r in recs if r.get("status") in FINAL][:max(0, extra)]:
                try:
                    self._path(r["id"]).unlink()
                    removed += 1
                except (OSError, KeyError):
                    pass
        return removed


def summary(rec: dict) -> dict:
    """List view: no prompt, a short reply preview."""
    keys = ("id", "status", "created", "updated", "finished", "endpoint", "model",
            "stream", "replays", "recovered", "note", "seen", "error", "finish_reason", "usage")
    out = {k: rec.get(k) for k in keys if k in rec}
    reply = rec.get("reply") or ""
    out["reply_preview"] = reply[:160]
    msgs = (rec.get("request") or {}).get("messages") or []
    last = next((m for m in reversed(msgs) if isinstance(m, dict) and m.get("role") == "user"), None)
    content = (last or {}).get("content")
    if isinstance(content, list):
        content = " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    out["prompt_preview"] = str(content or "")[:120]
    return out


def public(rec: dict) -> dict:
    """Full view for GET /api/jobs/<id>: drop internal fields."""
    return {k: v for k, v in rec.items() if k not in ("owner",)}


def collect_reply(data: dict):
    """Reply text, reasoning, usage and finish reason from a chat.completion."""
    reply, reasoning, finish = "", "", None
    for ch in (data or {}).get("choices") or []:
        msg = ch.get("message") or {}
        reply += msg.get("content") or ""
        reasoning += msg.get("reasoning_content") or msg.get("reasoning") or ""
        finish = ch.get("finish_reason") or finish
    return reply, reasoning, (data or {}).get("usage"), finish


class Replayer:
    """Runs unfinished jobs again once the model is ready."""

    def __init__(self, journal: Journal, *, snapshot, send, is_enabled=enabled,
                 interval=3.0, log=None):
        self.journal = journal
        self.snapshot = snapshot      # () -> worker snapshot
        self.send = send              # (body, session) -> chat.completion dict
        self.is_enabled = is_enabled
        self.interval = interval
        self.log = log or (lambda m: print("[caravan-web] " + m, flush=True))
        self._last_cleanup = 0.0
        self._stop = threading.Event()
        self.state = {"replayed": 0, "failed": 0, "last": None}

    def tick(self) -> int:
        """One pass. Returns how many jobs finished on this pass."""
        if not self.is_enabled():
            return 0
        now = time.time()
        if now - self._last_cleanup > 600:
            self._last_cleanup = now
            try:
                self.journal.cleanup()
            except Exception as e:  # noqa: BLE001
                self.log(f"job cleanup skipped: {e}")
        snap = self.snapshot() or {}
        if snap.get("status") != "ready":
            return 0
        finished = 0
        for rec in self.journal.pending(model=snap.get("model_id")):
            if (self.snapshot() or {}).get("status") != "ready":
                break
            rec = self.journal.start_replay(rec["id"])
            if rec is None:
                continue
            body = dict(rec.get("request") or {})
            body["stream"] = False
            body.pop("stream_options", None)
            self.log(f"running unfinished chat {rec['id']} again from the start (try {rec['replays']} of {MAX_REPLAYS})")
            try:
                data = self.send(body, rec.get("session"))
            except Exception as e:  # noqa: BLE001
                self.journal.interrupt(rec["id"], f"run again failed: {type(e).__name__}: {e}")
                self.state["failed"] += 1
                self.log(f"chat {rec['id']} did not finish on try {rec['replays']}: {e}")
                continue
            reply, reasoning, usage, finish = collect_reply(data)
            self.journal.finish(rec["id"], reply=reply, reasoning=reasoning, response=data,
                                usage=usage, finish_reason=finish, recovered=True)
            finished += 1
            self.state["replayed"] += 1
            self.state["last"] = rec["id"]
            self.log(f"chat {rec['id']} finished after a restart ({len(reply)} characters)")
        return finished

    def run_forever(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                self.log(f"job replay pass failed: {e}")
            self._stop.wait(self.interval)

    def start(self):
        threading.Thread(target=self.run_forever, name="caravan-job-replay", daemon=True).start()

    def stop(self):
        self._stop.set()
