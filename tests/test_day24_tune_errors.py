"""Self-tuning and Optimize now errors: a short plain reason on the page,
full detail in the log only."""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "agent"), str(REPO / "proxy")]

import web_optimize as WO
import web_settings
import web_tune_errors as TE
import web_gguf_optimize as WGO

HTML = (REPO / "proxy" / "web" / "index.html").read_text()


FORBIDDEN = (
    "HTTPError",
    "Traceback",
    "prf-hays",
    "exo1",
    "exo2",
    "127.0.0.1",
    "/Users/",
    "/home/",
    "Errno",
    "urlopen",
)


class PlainTuneErrorTest(unittest.TestCase):
    def test_http_400_mentions_memory_compression_not_raw(self):
        schedule = [{"name": "kv_bits", "state": "running"}]
        raw = "HTTPError: HTTP Error 400: Bad Request {\"error\": \"prompt: boom\"}"
        msg = TE.plain_tune_error(raw, schedule=schedule, source="self_tune", detail=raw)
        self.assertIn("Self-tuning stopped", msg)
        self.assertIn("Memory compression", msg)
        self.assertIn("rejected", msg)
        self.assertIn("previous settings", msg)
        for bad in FORBIDDEN + ("prompt:", "kv_bits", "400"):
            self.assertNotIn(bad, msg)

    def test_optimize_now_wording_and_timeout(self):
        msg = TE.plain_tune_error("URLError: timed out", source="optimize_now")
        self.assertIn("Optimize now stopped", msg)
        self.assertIn("took too long", msg)
        self.assertNotIn("URLError", msg)

    def test_reload_and_restore(self):
        msg = TE.plain_tune_error("RuntimeError: reload failed: load failed", source="optimize_now")
        self.assertIn("didn't finish reloading", msg)
        self.assertIn("Try loading again", msg)
        self.assertNotIn("RuntimeError", msg)
        msg = TE.plain_tune_error("restore failed: preflight denied")
        self.assertIn("couldn't return to the previous settings", msg)
        self.assertNotIn("preflight", msg)

    def test_never_interpolates_paths_or_hosts(self):
        raw = "HTTPError: HTTP Error 500: Internal Server Error at /Users/brenden/.caravan on prf-hays-exo01"
        msg = TE.plain_tune_error(raw, detail=raw)
        for bad in FORBIDDEN:
            self.assertNotIn(bad, msg)

    def test_http_body_captured_for_the_log(self):
        body = b'{"error": "prompt: unexpected keyword thinking"}'
        exc = HTTPError("http://127.0.0.1:8194/v1/chat/completions", 400, "Bad Request",
                        hdrs={}, fp=io.BytesIO(body))
        got = TE.http_body(exc)
        self.assertIn("unexpected keyword", got)
        # Second read still works (cached).
        self.assertEqual(TE.http_body(exc), got)
        detail = TE.detail_of(exc)
        self.assertIn("400", detail)
        self.assertIn("unexpected keyword", detail)
        # Page sentence stays plain.
        msg = TE.plain_tune_error(exc, schedule=[{"name": "kv_bits", "state": "running"}],
                                  source="self_tune", detail=detail)
        self.assertIn("Memory compression", msg)
        self.assertNotIn("unexpected keyword", msg)
        self.assertNotIn("127.0.0.1", msg)


class PublicSnapshotTest(unittest.TestCase):
    def test_status_subset_drops_raw_detail(self):
        snap = {
            "running": False, "mode": "now", "phase": "stopped (error)",
            "eta_s": 0, "source": "self_tune",
            "schedule": [{"name": "kv_bits", "state": "running"}],
            "error": "HTTPError: HTTP Error 400: Bad Request",
            "error_detail": "HTTPError: HTTP Error 400: Bad Request {\"error\":\"prompt: x\"} /Users/brenden/.caravan",
            "log": [{"msg": "secret"}],
        }
        out = TE.public_optimize_status(snap)
        self.assertEqual(set(out), {"running", "mode", "phase", "eta_s", "error", "source"})
        self.assertNotIn("error_detail", out)
        self.assertNotIn("log", out)
        self.assertIn("Self-tuning stopped", out["error"])
        self.assertIn("Memory compression", out["error"])
        for bad in FORBIDDEN + ("prompt:",):
            self.assertNotIn(bad, out["error"])


class OptimizerPlainErrorTest(unittest.TestCase):
    """A 400 from the model during a trial becomes a plain page sentence."""

    def setUp(self):
        import optimize_schedule as AB
        self.AB = AB
        self.active = dict(self_tune=True, guess_ahead=False, guess_ahead_loaded=False,
                           shared_start=False, pipeline_chats=1, keepalive=None,
                           kv_bits=16, fuse_kernels="off", pinned=[])

    def _mgr(self):
        import optimize_schedule as AB

        class Mgr:
            def __init__(self):
                self._lead_path = "/model"
                self._loaded_entry = {"id": "m", "placement": {"nodes": ["a"]}}
                self.active = copy.deepcopy(ACTIVE if False else {})
                self.active = copy.deepcopy(
                    dict(self_tune=True, guess_ahead=False, guess_ahead_loaded=False,
                         shared_start=False, pipeline_chats=1, keepalive=None,
                         kv_bits=16, fuse_kernels="off", pinned=[]))
                self.entry = {}
                self.reloads = []
                self.controls = []
                self.state = dict(status="ready", model_id="m", split=False,
                                  settings=web_settings.normalize({}))

            def snapshot(self):
                return copy.deepcopy(self.state)

            def lead_active_settings(self):
                return dict(self.active)

            def optimize_hardware(self):
                return [dict(id="a", host="local", chip="Apple M4", cpus=10,
                             ram={"total_gb": 32})]

            def _tuned_entry(self, *a, **k):
                return {}, self.entry

            def sweep(self, body):
                self.controls.append(copy.deepcopy(body))
                return {"paused": not body.get("release")}

            def switch(self, model_id, wait, settings, entry, sweep):
                self.reloads.append(copy.deepcopy(sweep))
                self.active.update(sweep["force"])

        return Mgr()

    def test_http_400_is_plain_and_body_is_in_detail(self):
        mgr = self._mgr()

        def send(msgs):
            raise HTTPError(
                "http://127.0.0.1:8194/v1/chat/completions", 400, "Bad Request",
                hdrs={}, fp=io.BytesIO(b'{"error": "prompt: unexpected keyword thinking"}'))

        opt = WO.Optimizer(mgr, send=send)
        opt.start(source="self_tune")
        opt._thread.join(5)
        snap = opt.snapshot()
        self.assertFalse(snap["running"])
        self.assertEqual(snap["phase"], "stopped (error)")
        self.assertIn("Self-tuning stopped", snap["error"])
        self.assertIn("rejected", snap["error"])
        self.assertIn("previous settings", snap["error"])
        for bad in FORBIDDEN + ("prompt:", "unexpected keyword", "thinking"):
            self.assertNotIn(bad, snap["error"])
        self.assertIn("unexpected keyword thinking", snap.get("error_detail") or "")
        self.assertIn("400", snap.get("error_detail") or "")
        # The worker was released / restored.
        self.assertTrue(any(c.get("release") for c in mgr.controls))
        public = TE.public_optimize_status(snap)
        self.assertNotIn("error_detail", public)
        self.assertEqual(public["error"], snap["error"])

    def test_gguf_tuner_error_is_plain(self):
        class Mgr:
            def __init__(self):
                self._loaded_entry = {"id": "gguf/m", "source": "gguf", "lead_path": "/tmp/m.gguf"}
                self._snap = {"status": "ready", "model_id": "gguf/m", "backend": "llama",
                              "gguf": {"nodes": ["a", "b"]}, "settings": {}}

            def snapshot(self):
                return dict(self._snap)

            def switch(self, mid, wait=False, settings=None, entry=None):
                return self.snapshot()

        class BoomTuner:
            def __init__(self, *a, **k):
                pass

            def run(self):
                return {"status": "error: HTTPError: HTTP Error 400: Bad Request",
                        "best": {}, "tried": [], "before": None, "after": None}

        opt = WGO.GgufOptimizer(
            Mgr(), tuner_cls=BoomTuner, measure=lambda: 10.0,
            store_path=Path(tempfile.mkdtemp()) / "t.json", sleep=lambda s: None)
        opt.start(source="optimize_now")
        for _ in range(200):
            if not opt.snapshot()["running"]:
                break
            import time
            time.sleep(0.01)
        snap = opt.snapshot()
        self.assertEqual(snap["phase"], "stopped (error)")
        self.assertIn("Optimize now stopped", snap["error"])
        self.assertIn("rejected", snap["error"])
        self.assertNotIn("HTTPError", snap["error"])
        self.assertIn("HTTP Error 400", snap.get("error_detail") or "")


class DocsAndPageTest(unittest.TestCase):
    def test_page_paints_error_next_to_self_tuning(self):
        # Visible Self-tuning area, not only the closed Advanced panel.
        self.assertIn('id="selfTuneNote"', HTML)
        self.assertIn('id="tuneNote"', HTML)
        self.assertIn("if (opt && opt.error && !opt.running) lines.push", HTML)
        self.assertIn('note.textContent = String(opt.error)', HTML)
        self.assertIn('note.textContent = String(j.error)', HTML)
        # Full raw detail must not be painted from error_detail on the optimize path.
        # The load-status error_detail slot is a different element and stays as-is.
        self.assertNotIn("j.error_detail", HTML)
        self.assertNotIn("opt.error_detail", HTML)

    def test_docs_mention_plain_reason(self):
        day = (REPO / "docs" / "DAY24.md").read_text()
        self.assertIn("Self-tuning error with no reason on the page", day)
        self.assertIn("A trial setting was rejected", day)
        self.assertIn("next to Self-tuning", day)
        self.assertIn("full detail goes to the log only", day)
        self.assertNotIn("prf-hays", day.split("### Live review: Self-tuning error")[-1])
        self.assertNotIn("exo1", day.split("### Live review: Self-tuning error")[-1])


# Import ACTIVE-less docs check is enough; DAY24 section is added before commit.

if __name__ == "__main__":
    unittest.main()
