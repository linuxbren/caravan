"""Day 30: request journal — finish chat work after a power loss.

Covers crash safety of the journal files, run-again-once, the limits
(age, tries, size, retention), the opt-out, the /api/chat and
/v1/chat/completions wiring (job id header, SSE comment, interrupted
replies) and GET /api/jobs.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests"))

import request_journal as RJ  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

BODY = {"model": "x", "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 8}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class JournalFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "jobs"
        self.clock = Clock()

    def j(self, owner="a"):
        return RJ.Journal(self.root, clock=self.clock, owner=owner)

    def test_begin_is_fsynced_private_and_readable(self):
        calls = []
        real = os.fsync
        with mock.patch.object(RJ.os, "fsync", side_effect=lambda fd: (calls.append(fd), real(fd))):
            rec = self.j().begin(BODY, endpoint="/v1/chat/completions", model="m", session="s", stream=True)
        self.assertGreaterEqual(len(calls), 2, "file and directory fsync")
        path = self.root / (rec["id"] + ".json")
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(self.root.stat().st_mode & 0o777), "0o700")
        saved = json.loads(path.read_text())
        self.assertEqual(saved["status"], "running")
        self.assertEqual(saved["request"], BODY)

    def test_crash_mid_write_keeps_the_old_record(self):
        jr = self.j()
        rec = jr.begin(BODY, endpoint="/api/chat", model="m")
        with mock.patch.object(RJ.os, "replace", side_effect=OSError("power lost")):
            with self.assertRaises(OSError):
                jr.finish(rec["id"], reply="half")
        again = self.j("b").read(rec["id"])
        self.assertEqual(again["status"], "running")      # still unfinished -> runs again
        self.assertEqual([r["id"] for r in self.j("b").all()], [rec["id"]])
        self.assertTrue(list(self.root.glob("*.tmp")))     # leftover temp file ignored
        self.clock.t += 120
        os.utime(next(self.root.glob("*.tmp")), (self.clock.t - 120, self.clock.t - 120))
        self.j("b").cleanup()
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_junk_file_is_skipped(self):
        self.root.mkdir(parents=True)
        (self.root / "job_1_bad.json").write_text("{not json")
        self.assertEqual(self.j().all(), [])

    def test_size_cap(self):
        big = dict(BODY, messages=[{"role": "user", "content": "x" * (RJ.MAX_BODY_BYTES + 1)}])
        self.assertIsNone(self.j().begin(big, endpoint="/api/chat"))
        self.assertFalse(self.root.exists() and list(self.root.glob("job_*.json")))

    def test_bad_ids_rejected(self):
        self.assertIsNone(self.j().read("../../etc/passwd"))
        self.assertIsNone(self.j().read("job_1/../../x"))


class ReplayOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = Clock()
        self.sent = []
        self.status = {"status": "ready", "model_id": "gguf/m"}

    def journal(self, owner):
        return RJ.Journal(self.root, clock=self.clock, owner=owner)

    def replayer(self, jr, send=None):
        def ok(body, session):
            self.sent.append((body, session))
            return {"choices": [{"message": {"content": "OK", "reasoning_content": "hm"},
                                 "finish_reason": "stop"}], "usage": {"completion_tokens": 1}}
        return RJ.Replayer(jr, snapshot=lambda: dict(self.status), send=send or ok,
                           is_enabled=lambda: True, log=lambda m: None)

    def test_lost_job_runs_again_once_and_is_saved(self):
        before = self.journal("before-power-loss")
        rec = before.begin(dict(BODY, stream=True, stream_options={"include_usage": True}),
                           endpoint="/v1/chat/completions", model="gguf/m", session="sess", stream=True)
        after = self.journal("after-boot")
        rp = self.replayer(after)
        self.assertEqual(rp.tick(), 1)
        self.assertEqual(rp.tick(), 0)
        self.assertEqual(self.replayer(self.journal("third-boot")).tick(), 0)
        self.assertEqual(len(self.sent), 1)
        body, session = self.sent[0]
        self.assertFalse(body["stream"])
        self.assertNotIn("stream_options", body)
        self.assertEqual(session, "sess")
        done = after.read(rec["id"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["reply"], "OK")
        self.assertEqual(done["reasoning"], "hm")
        self.assertTrue(done["recovered"])
        self.assertEqual(done["note"], "Finished after a restart")
        self.assertEqual(done["replays"], 1)

    def test_finished_jobs_never_run_again(self):
        jr = self.journal("a")
        rec = jr.begin(BODY, endpoint="/api/chat", model="gguf/m")
        jr.finish(rec["id"], reply="done before")
        self.assertEqual(self.replayer(self.journal("b")).tick(), 0)
        self.assertEqual(self.sent, [])

    def test_cancelled_and_failed_never_run_again(self):
        jr = self.journal("a")
        jr.cancel(jr.begin(BODY, endpoint="/api/chat", model="gguf/m")["id"])
        jr.fail(jr.begin(BODY, endpoint="/api/chat", model="gguf/m")["id"], "HTTP 400")
        self.assertEqual(self.replayer(self.journal("b")).tick(), 0)

    def test_live_request_of_this_process_is_left_alone(self):
        jr = self.journal("a")
        jr.begin(BODY, endpoint="/api/chat", model="gguf/m")
        self.assertEqual(self.replayer(jr).tick(), 0)

    def test_interrupted_in_this_process_runs_again(self):
        jr = self.journal("a")
        rec = jr.begin(BODY, endpoint="/api/chat", model="gguf/m")
        jr.interrupt(rec["id"], "llama-server went away")
        self.assertEqual(self.replayer(jr).tick(), 1)

    def test_waits_until_ready(self):
        self.journal("a").begin(BODY, endpoint="/api/chat", model="gguf/m")
        self.status = {"status": "starting_lead", "model_id": "gguf/m"}
        rp = self.replayer(self.journal("b"))
        self.assertEqual(rp.tick(), 0)
        self.status = {"status": "ready", "model_id": "gguf/m"}
        self.assertEqual(rp.tick(), 1)

    def test_waits_for_its_own_model(self):
        self.journal("a").begin(BODY, endpoint="/api/chat", model="gguf/m")
        self.status = {"status": "ready", "model_id": "gguf/other"}
        self.assertEqual(self.replayer(self.journal("b")).tick(), 0)

    def test_too_old_is_expired_not_run(self):
        rec = self.journal("a").begin(BODY, endpoint="/api/chat", model="gguf/m")
        self.clock.t += RJ.MAX_AGE_S + 1
        jr = self.journal("b")
        self.assertEqual(self.replayer(jr).tick(), 0)
        self.assertEqual(jr.read(rec["id"])["status"], "expired")
        self.assertEqual(self.sent, [])

    def test_at_most_two_tries(self):
        rec = self.journal("a").begin(BODY, endpoint="/api/chat", model="gguf/m")
        tries = []

        def boom(body, session):
            tries.append(1)
            raise OSError("model went away again")
        jr = self.journal("b")
        rp = self.replayer(jr, send=boom)
        for _ in range(5):
            rp.tick()
        self.assertEqual(len(tries), RJ.MAX_REPLAYS)
        self.assertEqual(jr.read(rec["id"])["status"], "gave_up")

    def test_crash_during_replay_still_counts(self):
        rec = self.journal("a").begin(BODY, endpoint="/api/chat", model="gguf/m")
        self.journal("b").start_replay(rec["id"])         # power lost again mid-replay
        self.journal("c").start_replay(rec["id"])         # and again
        jr = self.journal("d")
        self.assertEqual(self.replayer(jr).tick(), 0)
        self.assertEqual(jr.read(rec["id"])["status"], "gave_up")

    def test_disabled_does_nothing(self):
        self.journal("a").begin(BODY, endpoint="/api/chat", model="gguf/m")
        rp = self.replayer(self.journal("b"))
        rp.is_enabled = lambda: False
        self.assertEqual(rp.tick(), 0)


class Retention(unittest.TestCase):
    def test_old_finished_jobs_deleted_open_kept(self):
        with tempfile.TemporaryDirectory() as d:
            clock = Clock()
            jr = RJ.Journal(d, clock=clock, owner="a")
            old = jr.begin(BODY, endpoint="/api/chat")
            jr.finish(old["id"], reply="x")
            open_ = jr.begin(BODY, endpoint="/api/chat")
            clock.t += RJ.KEEP_S + 1
            self.assertEqual(jr.cleanup(), 1)
            self.assertIsNone(jr.read(old["id"]))
            self.assertIsNotNone(jr.read(open_["id"]))

    def test_job_count_cap(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(RJ, "MAX_JOBS", 3):
            clock = Clock()
            jr = RJ.Journal(d, clock=clock, owner="a")
            ids = []
            for i in range(5):
                clock.t += 1
                r = jr.begin(BODY, endpoint="/api/chat")
                jr.finish(r["id"], reply=str(i))
                ids.append(r["id"])
            jr.cleanup()
            self.assertEqual([r["id"] for r in jr.all()], ids[2:])


class OptOut(unittest.TestCase):
    def test_default_on(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(RJ.enabled({}, Path(d) / "missing.toml"))

    def test_env_off(self):
        self.assertFalse(RJ.enabled({"CARAVAN_RESUME_JOBS": "0"}))

    def test_config_off(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[jobs]\nresume = false\n")
            self.assertFalse(RJ.enabled({}, p))
            p.write_text("[jobs]\nresume = true\n")
            self.assertTrue(RJ.enabled({}, p))


class FakeLead(BaseHTTPRequestHandler):
    mode = "ok"
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeLead.seen.append(body)
        if not body.get("stream"):
            data = json.dumps({"object": "chat.completion", "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "Hello there"},
                 "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()

        def ev(o):
            self.wfile.write(b"data: " + json.dumps(o).encode() + b"\n\n")
            self.wfile.flush()
        ev({"choices": [{"index": 0, "delta": {"content": "Hel"}}]})
        if FakeLead.mode == "die":
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        ev({"choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": "stop"}]})
        ev({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
        self.wfile.write(b"data: [DONE]\n\n")


class ChatWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import web_server
        from web_workers import WorkerManager
        from test_web_server import _offline
        cls.tmp = tempfile.TemporaryDirectory()
        cls.lead = ThreadingHTTPServer(("127.0.0.1", 0), FakeLead)
        threading.Thread(target=cls.lead.serve_forever, daemon=True).start()
        mgr = WorkerManager(lead_port=cls.lead.server_address[1], packer_peer="127.0.0.1:5560",
                            packer_ssh="nobody@127.0.0.1", state_dir=Path(cls.tmp.name) / "state", repo=REPO)
        cls.app = web_server.App(mgr)
        _offline(cls.app)
        with mgr._lock:
            mgr.state.update(status="ready", model_id="gguf/m", backend="llama")
        cls.app.jobs = RJ.Journal(Path(cls.tmp.name) / "jobs", owner="web")
        cls.app.jobs_enabled = lambda: True
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(cls.app))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.lead.shutdown()
        cls.lead.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        FakeLead.mode = "ok"

    def post(self, path, body):
        return urlopen(Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"}), timeout=10)

    def get(self, path):
        with urlopen(self.base + path, timeout=10) as r:
            return json.loads(r.read().decode())

    def test_non_stream_has_job_header_and_saved_reply(self):
        with self.post("/v1/chat/completions", dict(BODY, stream=False)) as r:
            job = r.headers["X-Caravan-Job"]
            data = json.loads(r.read().decode())
        self.assertEqual(data["caravan_web"]["job"], job)
        rec = self.get("/api/jobs/" + job)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["reply"], "Hello there")
        self.assertEqual(rec["endpoint"], "/v1/chat/completions")
        self.assertNotIn("owner", rec)

    def test_stream_first_line_is_job_comment(self):
        with self.post("/api/chat", dict(BODY, stream=True)) as r:
            job = r.headers["X-Caravan-Job"]
            text = r.read().decode()
        self.assertTrue(text.startswith(": caravan-job " + job + "\n\n"), text[:80])
        self.assertIn('"job": "%s"' % job, text)
        rec = self.get("/api/jobs/" + job)
        self.assertEqual((rec["status"], rec["reply"], rec["finish_reason"]), ("done", "Hello", "stop"))

    def test_model_dies_mid_stream_then_runs_again(self):
        FakeLead.mode = "die"
        with self.post("/v1/chat/completions", dict(BODY, stream=True)) as r:
            job = r.headers["X-Caravan-Job"]
            text = r.read().decode()
        self.assertIn("caravan_interrupted", text)
        self.assertIn("/api/jobs/" + job, text)
        self.assertEqual(self.get("/api/jobs/" + job)["status"], "interrupted")
        FakeLead.mode = "ok"
        sent = []

        def send(body, session):
            sent.append(body)
            with urlopen(Request(f"http://127.0.0.1:{self.lead.server_address[1]}/v1/chat/completions",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"}), timeout=10) as r:
                return json.loads(r.read().decode())
        rp = RJ.Replayer(self.app.jobs, snapshot=self.app.mgr.snapshot, send=send,
                         is_enabled=lambda: True, log=lambda m: None)
        rp.tick()
        rp.tick()
        self.assertEqual(len([b for b in sent if b["messages"] == BODY["messages"]]), 1)
        rec = self.get("/api/jobs/" + job)
        self.assertEqual((rec["status"], rec["reply"], rec["note"]), ("done", "Hello there", "Finished after a restart"))
        unseen = self.get("/api/jobs?unseen=1")["jobs"]
        self.assertIn(job, [j["id"] for j in unseen])
        self.assertEqual(json.loads(self.post("/api/jobs/%s/seen" % job, {}).read()), {"ok": True})
        self.assertNotIn(job, [j["id"] for j in self.get("/api/jobs?unseen=1")["jobs"]])

    def test_list_has_no_prompts_and_limits(self):
        self.post("/api/chat", dict(BODY, stream=False)).read()
        data = self.get("/api/jobs")
        self.assertTrue(data["enabled"])
        self.assertEqual(data["limits"]["max_replays"], 2)
        self.assertNotIn("request", data["jobs"][0])
        self.assertEqual(data["jobs"][0]["prompt_preview"], "Say OK")

    def test_unknown_job_404(self):
        with self.assertRaises(HTTPError) as cm:
            self.get("/api/jobs/job_1_nope")
        self.assertEqual(cm.exception.code, 404)

    def test_opt_out_writes_nothing(self):
        self.app.jobs_enabled = lambda: False
        try:
            before = len(self.app.jobs.all())
            with self.post("/api/chat", dict(BODY, stream=False)) as r:
                self.assertIsNone(r.headers.get("X-Caravan-Job"))
                r.read()
            self.assertEqual(len(self.app.jobs.all()), before)
        finally:
            self.app.jobs_enabled = lambda: True


class CliAndDocs(unittest.TestCase):
    def test_cli_formats(self):
        import caravan_jobs as CJ
        out = CJ.format_list({"enabled": True, "jobs": [
            {"id": "job_1_a", "created": 1, "status": "done", "recovered": True, "prompt_preview": "Say OK"}]})
        self.assertIn("finished after a restart", out)
        job = CJ.format_job({"id": "job_1_a", "status": "done", "recovered": True, "replays": 1,
                             "created": 1, "finished": 2, "reply": "OK"})
        self.assertIn("from the start", job)
        self.assertTrue(job.endswith("OK"))

    def test_cli_wired(self):
        src = english_source(REPO / "tools" / "caravan.py")
        self.assertIn('argv[0] == "jobs"', src)

    def test_docs_say_from_the_start(self):
        for doc in ("docs/WEB.md", "docs/DAY30.md"):
            self.assertIn("from the start", (REPO / doc).read_text(), doc)

    def test_page_shows_recovered_note(self):
        html = english_source(REPO / "proxy" / "web" / "index.html")
        self.assertIn("Finished after a restart", html)
        self.assertIn('/api/jobs?unseen=1', html)


if __name__ == "__main__":
    unittest.main()
