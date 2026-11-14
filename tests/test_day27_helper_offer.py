"""Day 27: offer a missing Guess-ahead helper, only with the user's OK."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
import helper_offer as HO  # noqa: E402
import gguf_split as G  # noqa: E402
import caravan_bench as B  # noqa: E402
import web_server  # noqa: E402
import web_catalog  # noqa: E402
from web_workers import WorkerManager  # noqa: E402

QWEN = "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"


class MatchTests(unittest.TestCase):
    def test_known_pairs(self):
        self.assertEqual(HO.match_gguf(QWEN)["id"], "gguf-qwen2.5-coder")
        self.assertTrue(HO.match_gguf(QWEN)["measured"])
        self.assertEqual(HO.match_gguf("Qwen2.5-7B-Instruct-Q4_K_M.gguf")["id"], "gguf-qwen2.5")
        self.assertEqual(HO.match_gguf("Qwen_Qwen3-8B-Q4_K_M.gguf")["id"], "gguf-qwen3")
        self.assertEqual(HO.match_gguf("Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf")["id"], "gguf-llama3")

    def test_no_pair_for_small_or_unknown(self):
        for name in ("Llama-3.2-3B-Instruct-Q2_K_L.gguf", "Qwen2.5-Coder-0.5B-Instruct-Q8_0.gguf",
                     "gemma-3-12b-it-Q4_K_M.gguf", "Mistral-7B-Instruct-v0.3-Q4_K_M.gguf"):
            self.assertIsNone(HO.match_gguf(name), name)

    def test_helper_files_are_gguf_and_small(self):
        for h in HO.HELPERS:
            self.assertTrue(h["gguf_file"].endswith(".gguf"))
            self.assertLess(h["bytes"], 1.5e9)


class GenerationTests(unittest.TestCase):
    def test_draft_needs_same_generation(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / "Qwen_Qwen3-8B-Q4_K_M.gguf"
            with open(main, "wb") as f:
                f.truncate(4_500_000_000)
            old = Path(d) / "Qwen2.5-Coder-0.5B-Instruct-Q8_0.gguf"
            with open(old, "wb") as f:
                f.truncate(531_000_000)
            inv = [{"path": str(old), "name": old.stem}]
            self.assertIsNone(G.find_gguf_draft(main, inventory=inv))
            main2 = Path(d) / QWEN
            with open(main2, "wb") as f:
                f.truncate(4_500_000_000)
            self.assertIsNotNone(G.find_gguf_draft(main2, inventory=inv))


class OfferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "helper-offers.json"

    def offer(self, **kw):
        kw.setdefault("find_draft", lambda p: None)
        return HO.gguf_offer("gguf/qwen", "/m/" + QWEN, store_path=self.store, **kw)

    def test_offer_line_and_download_body(self):
        o = self.offer()
        self.assertEqual(o["message"], "Download helper for faster replies?")
        self.assertEqual(o["kind"], "gguf")
        self.assertEqual(o["size_mb"], 531)
        self.assertEqual(HO.download_body(o), {
            "repo_id": "bartowski/Qwen2.5-Coder-0.5B-Instruct-GGUF", "source": "gguf",
            "gguf_file": "Qwen2.5-Coder-0.5B-Instruct-Q8_0.gguf"})

    def test_no_offer_when_helper_on_disk_or_downloading(self):
        self.assertIsNone(self.offer(find_draft=lambda p: {"path": "/x.gguf"}))
        job = {"repo_id": "bartowski/Qwen2.5-Coder-0.5B-Instruct-GGUF", "status": "running"}
        self.assertIsNone(self.offer(jobs=[job]))
        self.assertIsNotNone(self.offer(jobs=[dict(job, status="done")]))

    def test_not_now_is_per_model_and_kept(self):
        HO.not_now("gguf/qwen", path=self.store)
        self.assertIsNone(self.offer())
        self.assertTrue(HO.declined("gguf/qwen", self.store))
        self.assertFalse(HO.declined("gguf/other", self.store))
        o = HO.gguf_offer("gguf/other", "/m/" + QWEN, store_path=self.store, find_draft=lambda p: None)
        self.assertIsNotNone(o)
        self.assertIn("gguf/qwen", json.loads(self.store.read_text())["not_now"])

    def test_offer_for_mlx_only_through_split_table(self):
        snap = {"model_id": "mlx-community/X-4bit", "split": False}
        with mock.patch("web_helpers.offer", return_value=None):
            self.assertIsNone(HO.offer_for(snap, {"id": "mlx-community/X-4bit", "source": "mlx"},
                                           store_path=self.store))
        fake = {"id": "p1", "repo_id": "mlx-community/H", "size_mb": 300, "declined": False}
        with mock.patch("web_helpers.offer", return_value=fake):
            o = HO.offer_for(snap, {"id": "mlx-community/X-4bit", "source": "mlx"}, store_path=self.store)
            self.assertEqual(o["kind"], "mlx")
            self.assertEqual(HO.download_body(o), {"repo_id": "mlx-community/H", "helper_id": "p1"})
            HO.not_now("mlx-community/X-4bit", path=self.store)
            self.assertIsNone(HO.offer_for(snap, {"id": "mlx-community/X-4bit", "source": "mlx"},
                                           store_path=self.store))


class CliPromptTests(unittest.TestCase):
    OFFER = {"offer": {"id": "gguf-qwen2.5-coder", "model": "gguf/q", "size_mb": 531}}

    def fake(self):
        calls = []

        def op(url, data=None, timeout=None):
            calls.append((url, json.loads(data.decode()) if data else None))
            if "/api/helper-offer?" in url:
                return self.OFFER
            if url.endswith("/answer"):
                return {"job": {"id": "j1", "status": "queued"}} if calls[-1][1]["action"] == "download" else {"ok": True}
            if "/api/picker/jobs/j1" in url:
                return {"id": "j1", "status": "done", "progress": {"lead": {"pct": 100}}}
            return {}
        return op, calls

    def actions(self, calls):
        return [c[1]["action"] for c in calls if c[1]]

    def test_no_terminal_never_downloads(self):
        op, calls = self.fake()
        out = io.StringIO()
        r = B.offer_helpers(8190, ["gguf/q"], urlopen=op, isatty=False, out=out,
                            ask=lambda q: self.fail("must not ask"))
        self.assertEqual(r, [("gguf/q", "no-terminal")])
        self.assertEqual(self.actions(calls), [])

    def test_enter_or_n_is_not_now(self):
        for reply in ("", "n", "no"):
            op, calls = self.fake()
            r = B.offer_helpers(8190, ["gguf/q"], urlopen=op, isatty=True, out=io.StringIO(),
                                ask=lambda q: reply)
            self.assertEqual(r, [("gguf/q", "not_now")])
            self.assertEqual(self.actions(calls), ["not_now"])

    def test_yes_downloads_and_waits(self):
        op, calls = self.fake()
        out = io.StringIO()
        asked = []
        r = B.offer_helpers(8190, ["gguf/q"], urlopen=op, isatty=True, out=out,
                            ask=lambda q: asked.append(q) or "y", sleep=lambda s: None)
        self.assertIn("Download helper for faster replies? (531 MB) [y/N]", asked[0])
        self.assertEqual(r, [("gguf/q", "done")])
        self.assertEqual(self.actions(calls), ["download"])
        self.assertIn("Helper ready", out.getvalue())

    def test_no_offer_no_question(self):
        out = io.StringIO()
        r = B.offer_helpers(8190, ["gguf/q"], urlopen=lambda *a, **k: {"offer": None},
                            isatty=True, out=out, ask=lambda q: self.fail("must not ask"))
        self.assertEqual(r, [])
        self.assertEqual(out.getvalue(), "")


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        state = tempfile.TemporaryDirectory()
        cls.addClassCleanup(state.cleanup)
        cls.state = Path(state.name)
        cls.mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560",
                                packer_ssh="nobody@127.0.0.1", state_dir=cls.state, repo=ROOT)
        cls.app = web_server.App(cls.mgr)
        cls.app.nodes = lambda: {"nodes": []}
        cls.app.configured_nodes = lambda: []
        cls.app.update_inspect = lambda: {}

        class _S(ThreadingHTTPServer):
            def server_bind(self):
                import socketserver
                socketserver.TCPServer.server_bind(self)
                self.server_name = self.server_address[0]
                self.server_port = self.server_address[1]
        cls.httpd = _S(("127.0.0.1", 0), web_server.make_handler(cls.app))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        p = [mock.patch.object(HO, "STORE", self.state / "helper-offers.json"),
             mock.patch.object(G, "find_gguf_draft", lambda *a, **k: None),
             mock.patch.object(web_catalog, "get_model",
                               lambda mid: {"id": mid, "source": "gguf", "lead_path": "/m/" + QWEN})]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def call(self, path, body=None, headers=None):
        hdrs = {"Content-Type": "application/json"}
        hdrs.update(headers or {})
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers=hdrs, method="POST" if body is not None else "GET")
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_local_get_offers_then_not_now_hides(self):
        code, j = self.call("/api/helper-offer?model=gguf/qwen-a")
        self.assertEqual(code, 200)
        self.assertTrue(j["show"])
        self.assertEqual(j["offer"]["repo_id"], "bartowski/Qwen2.5-Coder-0.5B-Instruct-GGUF")
        code, j = self.call("/api/helper-offer/answer", {"model": "gguf/qwen-a", "action": "not_now"})
        self.assertEqual(code, 200)
        code, j = self.call("/api/helper-offer?model=gguf/qwen-a")
        self.assertFalse(j["show"])

    def test_lan_view_hidden_and_forbidden(self):
        lan = {"Host": "192.168.1.20:8190"}
        code, j = self.call("/api/helper-offer?model=gguf/qwen-b", headers=lan)
        self.assertEqual((code, j["show"], j.get("lan")), (200, False, True))
        code, j = self.call("/api/helper-offer/answer",
                            {"model": "gguf/qwen-b", "helper_id": "gguf-qwen2.5-coder", "action": "download"},
                            headers=lan)
        self.assertEqual(code, 403)

    def test_download_needs_matching_offer(self):
        code, j = self.call("/api/helper-offer/answer",
                            {"model": "gguf/qwen-c", "helper_id": "wrong", "action": "download"})
        self.assertEqual(code, 409)
        code, j = self.call("/api/helper-offer/answer", {"model": "gguf/qwen-c", "action": "maybe"})
        self.assertEqual(code, 400)


class GuessAheadAutoTests(unittest.TestCase):
    def test_yes_sets_auto_unless_pinned_on(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560",
                                packer_ssh="nobody@127.0.0.1", state_dir=Path(d), repo=ROOT)
            from web_restore import Store
            Store(Path(d) / "last-model.json").write({"model_id": "m", "engine": "gguf", "settings": {"guess_ahead": "off"}})
            mgr._set(model_id="m", page_settings={"guess_ahead": "off", "kv_bits": "auto"})
            self.assertEqual(mgr.guess_ahead_auto(), "auto")
            self.assertEqual(mgr.snapshot()["page_settings"]["guess_ahead"], "auto")
            self.assertEqual(mgr.snapshot()["page_settings"]["kv_bits"], "auto")
            self.assertEqual(Store(Path(d) / "last-model.json").read()["settings"]["guess_ahead"], "auto")
            mgr._set(page_settings={"guess_ahead": "on"})
            self.assertEqual(mgr.guess_ahead_auto(), "on")


class PageTests(unittest.TestCase):
    def test_page_has_one_line_and_no_popup(self):
        html = (ROOT / "proxy/web/index.html").read_text()
        self.assertIn('id="helperLine"', html)
        self.assertLess(html.index("/helper_line.js"), html.index("/helpers.js"))
        js = (ROOT / "proxy/web/helper_line.js").read_text()
        self.assertIn("window.caravanHelperLine = true", js)
        self.assertIn("Not now", js)
        self.assertIn("data.lan", js)
        self.assertIn("!window.caravanHelperLine", (ROOT / "proxy/web/helpers.js").read_text())


if __name__ == "__main__":
    unittest.main()


class SpeedupsSingleMlxTests(unittest.TestCase):
    def test_single_mac_mlx_guess_ahead_row_says_why(self):
        import caravan_speedups as SU
        st = {"split": False, "worker": {"split": False},
              "active": {"guess_ahead": False, "two_chats_available": True}}
        with mock.patch.object(SU, "load_with", return_value=st), \
                mock.patch.object(SU, "run_set", return_value={"write_tok_s": 20.0}):
            out = SU.run_side("mlx", "mlx-community/X", port=1, urlopen=None, status_fn=None,
                              window_fn=lambda *a: 32768,
                              sets_args={"run_short": True, "run_edits": False, "run_long": False})
        ga = [r for r in out["rows"] if r["mode"] == "Guess-ahead"]
        self.assertEqual(len(ga), 1)
        self.assertIn("split models only", ga[0]["reason"])
