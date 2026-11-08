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
        self.assertIn("gpt-oss-20b-mxfp4", ids)
        # single-node models dropped Nov 5 (shard-sized only)
        self.assertNotIn("llama-3.1-8b-4bit", ids)
        self.assertNotIn("qwen2.5-14b-4bit", ids)

    def test_get_model(self):
        m = catalog.get_model("qwen3-30b-a3b-4bit")
        self.assertIsNotNone(m)
        self.assertEqual(m["packer_layers"], 24)
        self.assertIsNone(catalog.get_model("nope"))


def _offline(app):
    """Keep HTTP tests off the network: no SSH to Minis/packer, no node probes.
    Without this, /api/models/load (inventory over SSH) and /api/models/stop
    (packer stop over SSH) hang or fail on hosts that can't reach the Minis."""
    import subprocess as _sp
    app.mgr._ssh = lambda cmd, timeout=60: _sp.CompletedProcess(["ssh"], 0, "", "")
    app.configured_nodes = lambda: []
    app.nodes = lambda: {"nodes": []}
    app.gather_model_inventories = lambda: []


class WebServerHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Manager that never touches real workers.
        mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560",
                            packer_ssh="nobody@127.0.0.1",
                            state_dir=REPO / "handoff" / "lab" / "day15-web" / "test-state",
                            repo=REPO)
        cls.app = web_server.App(mgr)
        _offline(cls.app)
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
        # Avoid live SSH to the lab packer from the unit-test host.
        self.app.list_loadable_models = lambda: [
            {"id": "qwen3-30b-a3b-4bit", "name": "Qwen3", "usable": True,
             "available_lead": True, "hf": "mlx-community/Qwen3-30B-A3B-4bit"},
        ]
        code, j = self._get("/api/models")
        self.assertEqual(code, 200)
        self.assertEqual(j.get("source"), "disk")
        self.assertEqual(len(j["models"]), 1)
        self.assertEqual(j["models"][0]["id"], "qwen3-30b-a3b-4bit")

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




class StripMarkersTest(unittest.TestCase):
    def test_strip_im_end_and_turn(self):
        self.assertEqual(
            timing.strip_reply_markers("hello<|im_end|>"),
            "hello",
        )
        self.assertEqual(
            timing.strip_reply_markers("hi<turn|>"),
            "hi",
        )
        self.assertEqual(
            timing.strip_reply_markers("ok<|turn|>more"),
            "okmore",
        )

    def test_strip_empty_and_clean(self):
        self.assertEqual(timing.strip_reply_markers(""), "")
        self.assertEqual(timing.strip_reply_markers("plain"), "plain")


class KeepAliveDrainTest(unittest.TestCase):
    """Regression: chat 409 used to skip reading the POST body, so the next
    keep-alive request on the same socket became Bad request syntax."""

    @classmethod
    def setUpClass(cls):
        mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560",
                            packer_ssh="nobody@127.0.0.1",
                            state_dir=REPO / "handoff" / "lab" / "day15-web" / "test-state-ka",
                            repo=REPO)
        cls.app = web_server.App(mgr)
        _offline(cls.app)
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

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_chat_409_drains_body_keep_alive(self):
        import http.client
        body = json.dumps({
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "max_tokens": 8,
        }).encode()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(
                "POST", "/api/chat", body=body,
                headers={"Content-Type": "application/json",
                         "Content-Length": str(len(body)),
                         "Connection": "keep-alive"},
            )
            r1 = conn.getresponse()
            raw1 = r1.read()
            self.assertEqual(r1.status, 409)
            self.assertIn(b"no model loaded", raw1)
            # Same connection must still accept a clean GET.
            conn.request("GET", "/api/status", headers={"Connection": "close"})
            r2 = conn.getresponse()
            raw2 = r2.read()
            self.assertEqual(r2.status, 200)
            j = json.loads(raw2.decode())
            self.assertEqual(j["worker"]["status"], "idle")
        finally:
            conn.close()

    def test_stop_failure_returns_json_and_keeps_socket(self):
        import http.client, subprocess as _sp
        from unittest import mock
        saved = self.app.mgr._ssh
        self.app.mgr._ssh = lambda cmd, timeout=60: _sp.CompletedProcess(["ssh"], 255, "", "unreachable")
        peer_patch = mock.patch("web_nodes.nodes_from_config", return_value=[
            {"id":"test-packer","role":"packer","host":self.app.mgr.packer_ssh,
             "ssh":self.app.mgr.packer_ssh,"peer":self.app.mgr.packer_peer}])
        peer_patch.start()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", "/api/models/stop", body=b"{}",
                         headers={"Content-Type": "application/json", "Content-Length": "2"})
            r1 = conn.getresponse()
            j = json.loads(r1.read().decode())
            self.assertEqual(r1.status, 502)
            self.assertIn("could not stop", j["error"])
            conn.request("GET", "/api/status", headers={"Connection": "close"})
            r2 = conn.getresponse(); r2.read()
            self.assertEqual(r2.status, 200)
        finally:
            self.app.mgr._ssh = saved
            peer_patch.stop()
            conn.close()

    def test_stop_drains_body_keep_alive(self):
        import http.client
        body = b"{}"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(
                "POST", "/api/models/stop", body=body,
                headers={"Content-Type": "application/json",
                         "Content-Length": str(len(body)),
                         "Connection": "keep-alive"},
            )
            r1 = conn.getresponse()
            r1.read()
            self.assertEqual(r1.status, 200)
            conn.request("GET", "/api/status", headers={"Connection": "close"})
            r2 = conn.getresponse()
            raw2 = r2.read()
            self.assertEqual(r2.status, 200)
            json.loads(raw2.decode())
        finally:
            conn.close()


class IndexHtmlContractTest(unittest.TestCase):
    def test_ui_has_send_guards_and_timeouts(self):
        html = (REPO / "proxy" / "web" / "index.html").read_text()
        self.assertIn("cancelChat", html)
        self.assertIn("stripMarkers", html)
        self.assertIn("thinking…", html)
        self.assertIn("FIRST_MS", html)
        self.assertIn("chatAbort", html)
        self.assertIn('st !== "ready" || state.streaming', html)

if __name__ == "__main__":
    unittest.main()


class PageInsecureContextTest(unittest.TestCase):
    """The page is served over plain http on the Tailscale IP (not a secure
    context), where crypto.randomUUID is undefined. Sending must not depend on it."""

    def test_no_bare_random_uuid(self):
        html = (REPO / "proxy" / "web" / "index.html").read_text()
        self.assertIn("function newSessionId()", html)
        self.assertIn("getRandomValues", html)
        bare = [ln for ln in html.splitlines()
                if "randomUUID()" in ln and "typeof c.randomUUID" not in ln]
        self.assertEqual(bare, [], "crypto.randomUUID() used without a fallback")


class WorkerEndMarkerTest(unittest.TestCase):
    def test_strip_eot(self):
        sys.path.insert(0, str(REPO / "agent"))
        try:
            import mlx_worker
        except Exception as e:  # mlx not installed on this box
            self.skipTest(f"mlx_worker import: {e}")
        self.assertEqual(mlx_worker.strip_end_markers("Hi there!<|eot_id|>"), "Hi there!")
        self.assertEqual(mlx_worker.strip_end_markers("<|eot_id|>"), "")
        self.assertEqual(mlx_worker.strip_end_markers(""), "")
        self.assertEqual(mlx_worker.strip_end_markers("a <b> c"), "a <b> c")


import web_settings  # noqa: E402


class WebSettingsTest(unittest.TestCase):
    def test_all_auto_adds_no_flags(self):
        self.assertEqual(web_settings.to_args({}), ([], []))
        self.assertTrue(all(v == "auto" for v in web_settings.normalize(None).values()))

    def test_each_toggle_maps_to_real_flags(self):
        lead, packer = web_settings.to_args({
            "guess_ahead": "off", "self_tune": "off", "shared_start": "on",
            "pipeline_chats": "1", "fuse_kernels": "on", "kv_bits": "8", "keepalive": "off"})
        for f in ("--no-split-draft", "--no-learn", "--split-shared-prefix-cache",
                  "--no-split-keepalive"):
            self.assertIn(f, lead)
        self.assertEqual(lead[lead.index("--split-pipeline-chats") + 1], "1")
        self.assertEqual(packer, ["--fuse-kernels", "all", "--kv-bits", "8"])
        self.assertIn("--pin-guess-ahead", web_settings.to_args({"guess_ahead": "on"})[0])
        self.assertIn("--no-split-shared-prefix-cache",
                      web_settings.to_args({"shared_start": "off"})[0])

    def test_flags_parse_in_worker(self):
        """Every flag the page can emit must be accepted by mlx_worker's parser."""
        sys.path.insert(0, str(REPO / "agent"))
        try:
            import mlx_worker
        except Exception as e:
            self.skipTest(f"mlx_worker import: {e}")
        combos = [{"guess_ahead": "on", "shared_start": "off", "kv_bits": "4"},
                  {"guess_ahead": "off", "self_tune": "off", "shared_start": "on",
                   "pipeline_chats": "2", "fuse_kernels": "on", "keepalive": "off"}]
        for c in combos:
            lead, packer = web_settings.to_args(c)
            a = mlx_worker.build_parser().parse_args(["--model", "/m"] + lead)
            mlx_worker.build_parser().parse_args(["--model", "/m"] + packer)
            if "--no-learn" in lead:
                self.assertTrue(a.no_learn)
            if c.get("shared_start") == "off":
                self.assertTrue(a.no_split_shared_prefix_cache)
            if c.get("guess_ahead") == "on":
                self.assertTrue(a.pin_guess_ahead)

    def test_rejects_unknown(self):
        with self.assertRaises(ValueError):
            web_settings.normalize({"turbo": "on"})
        with self.assertRaises(ValueError):
            web_settings.normalize({"kv_bits": "3"})

    def test_active_in_reply_stats(self):
        st = timing.reply_stats({"caravan": {"active": {"guess_ahead": True, "kv_bits": 16}}})
        self.assertEqual(st["active"]["kv_bits"], 16)
        self.assertIsNone(timing.reply_stats({})["active"])


class WebSettingsHTTPTest(WebServerHTTPTest):
    def test_settings_endpoint(self):
        code, j = self._get("/api/settings")
        self.assertEqual(code, 200)
        ids = [o["id"] for o in j["options"]]
        self.assertIn("guess_ahead", ids)
        self.assertIn("shared_start", ids)
        self.assertEqual(j["current"]["guess_ahead"], "auto")

    def test_page_has_toggles(self):
        with urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode()
        # "ran with:" wording dropped on purpose in ba60fa9 (green chips suffice).
        for needle in ('id="optRows"', 'id="btnApply"', 'id="activeChips"',
                       "settings: state.choice"):
            self.assertIn(needle, html)


class PageOrderTest(unittest.TestCase):
    """Day 15: Brenden's order, most important first."""

    def test_section_order(self):
        html = (REPO / "proxy" / "web" / "index.html").read_text()
        body = html[html.index("<body>"):]
        # ba60fa9 (Day 16) intentionally moved load progress into the chat
        # column (progressCard, shown only on problems) and the string card
        # into the left Topology drawer, so those two left the main order.
        order = ["a-chat", "a-last", "a-settings", "a-clock", "a-miles", "a-journey"]
        pos = [body.index(f'{c}"') for c in order]
        self.assertEqual(pos, sorted(pos))
        self.assertIn('id="progressCard"', body)
        self.assertIn('id="topoDrawer"', body)
        self.assertLess(body.index('id="modelSelect"'), body.index('id="optRows"'))
        self.assertGreater(body.index('id="modelSelect"'), body.index('a-settings"'))


class SelfTuneFirstTest(unittest.TestCase):
    def test_self_tune_first(self):
        self.assertEqual(web_settings.OPTIONS[0]["id"], "self_tune")
        self.assertEqual([o["id"] for o in web_settings.OPTIONS[1:]],
                         ["guess_ahead", "prompt_lookup", "shared_start", "pipeline_chats",
                          "fuse_kernels", "kv_bits", "keepalive"])
        html = (REPO / "proxy" / "web" / "index.html").read_text()
        self.assertIn('(b.id === "self_tune") - (a.id === "self_tune")', html)


class SelfTuneAutoResetTest(unittest.TestCase):
    def setUp(self):
        self.html = (REPO / "proxy" / "web" / "index.html").read_text()

    def test_self_tune_auto_resets_all(self):
        self.assertIn('row.dataset.id === "self_tune" && b.dataset.v === "auto"', self.html)
        self.assertIn('for (const o of state.opts) state.choice[o.id] = "auto";', self.html)

    def test_pinned_note(self):
        self.assertIn("pinned — self-tuning can't change these", self.html)
        self.assertIn('state.choice.self_tune !== "auto"', self.html)

    def test_auto_shows_resolved(self):
        self.assertIn("`Auto (${v})`", self.html)
