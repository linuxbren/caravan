"""Day 15: Caravan web UI — timing math + HTTP endpoints (no MLX, no Minis)."""
from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))

import web_timing as timing  # noqa: E402
import web_catalog as catalog  # noqa: E402
import web_server  # noqa: E402
from web_workers import WorkerManager  # noqa: E402


class TimingMathTest(unittest.TestCase):
    def test_offset_median_and_uncertainty(self):
        # Perfect sync, 10 ms RTT each way → offset 0, unc >= 5 ms.
        samples = [
            {"client_send": 1000.000, "server_recv": 1000.005, "client_recv": 1000.010},
            {"client_send": 1001.000, "server_recv": 1001.005, "client_recv": 1001.010},
            {"client_send": 1002.000, "server_recv": 1002.006, "client_recv": 1002.010},
        ]
        r = timing.estimate_offset(samples)
        self.assertEqual(r["n"], 3)
        self.assertAlmostEqual(r["offset_s"], 0.0, places=3)
        self.assertGreaterEqual(r["uncertainty_s"], 0.004)
        self.assertAlmostEqual(r["rtt_s"], 0.010, places=3)

    def test_offset_nonzero(self):
        # Mini clock 1.5 s ahead of browser.
        samples = [
            {"client_send": 10.0, "server_recv": 11.505, "client_recv": 10.010},
            {"client_send": 11.0, "server_recv": 12.505, "client_recv": 11.010},
        ]
        r = timing.estimate_offset(samples)
        self.assertAlmostEqual(r["offset_s"], 1.5, places=2)

    def test_empty_samples(self):
        r = timing.estimate_offset([])
        self.assertIsNone(r["offset_s"])
        self.assertEqual(r["n"], 0)

    def test_gaps(self):
        g = timing.chat_gaps({
            "sent": 100.00, "received": 100.03,
            "first_word": 101.58, "done": 103.20,
        })
        self.assertAlmostEqual(g["send_to_receive_s"], 0.03, places=4)
        self.assertAlmostEqual(g["receive_to_first_s"], 1.55, places=4)
        self.assertAlmostEqual(g["first_to_done_s"], 1.62, places=4)
        self.assertAlmostEqual(g["send_to_done_s"], 3.20, places=4)

    def test_reply_stats_from_usage(self):
        usage = {
            "prompt_tokens": 4096,
            "completion_tokens": 128,
            "prompt_tokens_details": {"cached_tokens": 4096},
            "caravan": {
                "how": "shared-prefix-hit-memory",
                "prefill_s": 0.4,
                "ttft_s": 1.55,
                "total_s": 4.55,
                "speculate": {"k": 4, "from_draft": 60, "accepted_frac": 0.47},
                "learn": {"winner": {"shared_prefix": True}},
                "peak_gb": 10.5,
            },
        }
        s = timing.reply_stats(usage)
        self.assertEqual(s["prompt_tokens"], 4096)
        self.assertEqual(s["completion_tokens"], 128)
        self.assertTrue(s["shared_start"])
        self.assertAlmostEqual(s["read_tok_s"], 4096 / 0.4, places=1)
        # write over (total - ttft) = 3.0 s → 128/3 ≈ 42.67
        self.assertAlmostEqual(s["write_tok_s"], 128 / 3.0, places=1)
        self.assertEqual(s["guess_ahead"]["k"], 4)
        self.assertEqual(s["tuned"]["shared_prefix"], True)

    def test_reply_stats_missing_fields_stay_none(self):
        s = timing.reply_stats({})
        self.assertIsNone(s["write_tok_s"])
        self.assertIsNone(s["ttft_s"])
        self.assertFalse(s["shared_start"])

    def test_projection(self):
        self.assertAlmostEqual(timing.mini_to_browser(100.5, 1.5), 99.0, places=6)
        self.assertAlmostEqual(timing.browser_to_mini(99.0, 1.5), 100.5, places=6)
        self.assertIsNone(timing.mini_to_browser(1.0, None))


class CatalogTest(unittest.TestCase):
    def test_catalog_has_day13_models(self):
        ids = {m["id"] for m in catalog.CATALOG}
        self.assertIn("qwen3-30b-a3b-4bit", ids)
        self.assertIn("gemma-4-26b-a4b-4bit", ids)
        self.assertIn("llama-3.1-8b-4bit", ids)

    def test_get_model(self):
        m = catalog.get_model("qwen3-30b-a3b-4bit")
        self.assertIsNotNone(m)
        self.assertEqual(m["packer_layers"], 24)
        self.assertIsNone(catalog.get_model("nope"))


class WebServerHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Manager that never touches real workers.
        mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560",
                            packer_ssh="nobody@127.0.0.1",
                            state_dir=REPO / "handoff" / "lab" / "day15-web" / "test-state",
                            repo=REPO)
        cls.app = web_server.App(mgr)
        # Bind ephemeral port on localhost.
        class _S(ThreadingHTTPServer):
            def server_bind(self):
                import socketserver
                socketserver.TCPServer.server_bind(self)
                self.server_name = self.server_address[0]
                self.server_port = self.server_address[1]
        cls.httpd = _S(("127.0.0.1", 0), web_server.make_handler(cls.app))
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        with urlopen(self.base + path, timeout=5) as r:
            return r.status, json.loads(r.read().decode())

    def _post(self, path, body):
        req = Request(self.base + path, data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())

    def test_index_html(self):
        with urlopen(self.base + "/", timeout=5) as r:
            self.assertEqual(r.status, 200)
            body = r.read().decode()
            self.assertIn("Caravan", body)
            self.assertIn("How far we’ve come", body)

    def test_time_endpoint(self):
        code, j = self._post("/api/time", {"client_send": 1234.5})
        self.assertEqual(code, 200)
        self.assertEqual(j["client_send"], 1234.5)
        self.assertIsInstance(j["server_recv"], float)
        self.assertGreaterEqual(j["server_send"], j["server_recv"])

    def test_models_endpoint(self):
        code, j = self._get("/api/models")
        self.assertEqual(code, 200)
        self.assertGreaterEqual(len(j["models"]), 3)

    def test_journey_endpoint(self):
        code, j = self._get("/api/journey")
        self.assertEqual(code, 200)
        self.assertIn("highlights", j)
        self.assertIn("qwen3_write", j["series"])
        # Real Day 12/13 numbers present.
        pts = {p["v"]: p["n"] for p in j["series"]["qwen3_write"]["points"]}
        self.assertEqual(pts["v0"], 41.4)
        self.assertEqual(pts["v3"], 59.0)

    def test_status_endpoint(self):
        code, j = self._get("/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(j["worker"]["status"], "idle")

    def test_chat_rejects_when_idle(self):
        req = Request(self.base + "/api/chat",
                      data=json.dumps({"messages": [{"role": "user", "content": "hi"}],
                                       "stream": False}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as cm:
            urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 409)

    def test_load_unknown_model(self):
        from urllib.error import HTTPError
        req = Request(self.base + "/api/models/load",
                      data=json.dumps({"model_id": "nope"}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(HTTPError) as cm:
            urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
