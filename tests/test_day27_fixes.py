"""Day 27 fixes: Update now early reload, GGUF model lookup for Settings and
the helper offer, and the leftover dns-sd advertisers after restarts."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
import gguf_split as G  # noqa: E402
import helper_offer as HO  # noqa: E402
import pairing as P  # noqa: E402
import web_catalog  # noqa: E402
import web_server  # noqa: E402
import web_settings  # noqa: E402
from web_workers import WorkerManager  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

MAIN = "Qwen2.5-Coder-7B-Instruct-Q4_K_M"
HELP = "Qwen2.5-Coder-0.5B-Instruct-Q8_0"
NODE = shutil.which("node")


def sparse(path: Path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


@unittest.skipUnless(NODE, "node not installed")
class UpdateReloadTests(unittest.TestCase):
    def test_old_done_click_slow_reply_no_early_reload(self):
        r = subprocess.run([NODE, str(ROOT / "tests/js/update_reload_harness.js")],
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok", r.stdout)

    def test_page_code_guards(self):
        html = english_source(ROOT / "proxy/web/index.html")
        self.assertIn("function isNewRun(progress, pending)", html)
        self.assertIn("j = updateView(j);", html)
        self.assertIn("setUpdatePending(true, prevRun", html)
        # Auto-tune and chat no longer repaint the update section directly.
        self.assertNotIn("renderUpdate(_updateInfo);\n  }\n  function cancelChat", html)
        self.assertEqual(html.count('typeof repaintUpdate === "function") repaintUpdate();'), 4)


class RealGgufLookupTests(unittest.TestCase):
    """A real gguf/ id from the page and real files on disk, no mocked lookup."""

    @classmethod
    def setUpClass(cls):
        d = tempfile.TemporaryDirectory()
        cls.addClassCleanup(d.cleanup)
        cls.root = Path(d.name) / "models"
        cls.main = cls.root / "bartowski--Qwen2.5-Coder-7B-Instruct-GGUF" / (MAIN + ".gguf")
        cls.helper = cls.root / "bartowski--Qwen2.5-Coder-0.5B-Instruct-GGUF" / (HELP + ".gguf")
        sparse(cls.main, 4_683_074_336)
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
        for x in (mock.patch.object(G, "GGUF_ROOTS", [self.root]),
                  mock.patch.object(HO, "STORE", self.state / "helper-offers.json")):
            x.start()
            self.addCleanup(x.stop)
        if self.helper.exists():
            self.helper.unlink()

    def get(self, path):
        with urlopen(Request(self.base + path), timeout=10) as r:
            return json.loads(r.read().decode())

    def guess_row(self, j):
        return next(o for o in j["options"] if o["id"] == "guess_ahead")

    def test_catalog_knows_gguf_ids(self):
        e = web_catalog.get_model("gguf/" + MAIN)
        self.assertEqual(e["source"], "gguf")
        self.assertEqual(e["lead_path"], str(self.main))
        self.assertEqual(self.app.model_entry("gguf/" + MAIN)["lead_path"], str(self.main))
        self.assertIsNone(web_catalog.gguf_entry("gguf/Not-On-This-Mac"))

    def test_settings_on_selectable_with_helper_on_disk(self):
        sparse(self.helper, 531_068_576)
        row = self.guess_row(self.get("/api/settings?model=gguf/" + MAIN))
        self.assertNotIn("on", row.get("disabled_values") or {})
        self.assertEqual(row["draft"]["name"], HELP)

    def test_settings_on_disabled_without_helper(self):
        row = self.guess_row(self.get("/api/settings?model=gguf/" + MAIN))
        self.assertIn("on", row.get("disabled_values") or {})

    def test_helper_button_status_when_present(self):
        sparse(self.helper, 531_068_576)
        j = self.get("/api/helper-offer?model=gguf/" + MAIN)
        self.assertIsNone(j["offer"])
        st = j["helper"]
        self.assertEqual((st["kind"], st["present"], st["present_name"]), ("gguf", True, HELP))
        self.assertIn("already on this Mac (" + HELP + ")", st["message"])

    def test_helper_offer_when_missing_and_after_not_now(self):
        j = self.get("/api/helper-offer?model=gguf/" + MAIN)
        self.assertEqual(j["offer"]["kind"], "gguf")
        self.assertEqual(j["offer"]["gguf_file"], HELP + ".gguf")
        st = j["helper"]
        self.assertFalse(st["present"])
        self.assertEqual((st["known_id"], st["known_name"]), ("gguf-qwen2.5-coder", HELP))
        HO.not_now("gguf/" + MAIN)
        self.assertIsNone(self.get("/api/helper-offer?model=gguf/" + MAIN)["offer"])
        entry = self.app.model_entry("gguf/" + MAIN)
        # The Helper download button is an explicit yes: Not now does not block it.
        self.assertEqual(HO.offer_for({}, entry, ignore_declined=True)["id"], "gguf-qwen2.5-coder")

    def test_mlx_status_is_not_gguf(self):
        st = HO.helper_status({"model_id": "mlx-community/x", "split": False},
                              {"id": "x", "lead_path": "/m/x"})
        self.assertEqual((st["kind"], st["split"]), ("mlx", False))


@unittest.skipUnless(NODE, "node not installed")
class HelperButtonTextTests(unittest.TestCase):
    def say(self, st):
        js = english_source(ROOT / "proxy/web/helpers.js")
        a = js.index("  function helperButtonText(")
        b = js.index("  async function helperButtonClick(")
        prog = js[a:b] + "\nconsole.log(JSON.stringify(helperButtonText(" + json.dumps(st) + ")));"
        r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_messages(self):
        t = self.say({"kind": "gguf", "present": True, "present_name": HELP})
        self.assertIn("already on this Mac (" + HELP + ")", t["say"])
        self.assertIn("Set Guess-ahead to On", t["say"])
        t = self.say({"kind": "gguf", "present": False, "known_id": "gguf-qwen2.5-coder",
                      "known_name": HELP, "known_size_mb": 531})
        self.assertIn("Download the " + HELP + " helper (531 MB)", t["ask"])
        self.assertIn("no known", self.say({"kind": "gguf", "present": False})["say"])
        self.assertIn("one Mac", self.say({"kind": "mlx", "split": False})["say"])
        self.assertIn("split MLX", self.say({"kind": "mlx", "split": True})["say"])
        self.assertIn("split MLX", self.say(None)["say"])


class DnsSdLeftoverTests(unittest.TestCase):
    NAME = "Caravan-55afa030f5fc"

    def test_only_own_orphans_match(self):
        uid = os.getuid()
        ps = textwrap.dedent(f"""\
            101 1 {uid} dns-sd -R {self.NAME} _caravan._tcp local 8197
            102 1 {uid} /usr/bin/dns-sd -R {self.NAME} _caravan._tcp local 8197
            103 555 {uid} dns-sd -R {self.NAME} _caravan._tcp local 8197
            104 1 {uid} dns-sd -R Caravan-024b07e84bd3 _caravan._tcp local 8197
            105 1 {uid + 1} dns-sd -R {self.NAME} _caravan._tcp local 8197
            106 1 {uid} dns-sd -B _caravan._tcp local
            107 1 {uid} dns-sd -R {self.NAME} _caravan._tcp local 8198
            """)
        self.assertEqual(P.stale_adverts(self.NAME, 8197, ps), [101, 102])

    def test_stop_sends_term_to_matches_only(self):
        uid = os.getuid()
        ps = f"201 1 {uid} dns-sd -R {self.NAME} _caravan._tcp local 8197\n"
        killed = []
        run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=ps, stderr="")
        self.assertEqual(P.stop_stale_adverts(self.NAME, 8197, run=run,
                                              kill=lambda pid, sig: killed.append(pid)), [201])
        self.assertEqual(killed, [201])

    def test_sigterm_stops_the_advertiser(self):
        code = textwrap.dedent(f"""
            import os, signal, subprocess, sys, time
            sys.path.insert(0, {str(ROOT / 'proxy')!r}); sys.path.insert(0, {str(ROOT / 'agent')!r})
            import pairing
            p = pairing.Pairing.__new__(pairing.Pairing)
            p.advert = subprocess.Popen(["sleep", "60"])
            p._watch_exit()
            print(p.advert.pid, flush=True)
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)
            """)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        pid = int(r.stdout.split()[0])
        self.assertLess(r.returncode, 0)  # still ends by SIGTERM
        deadline = time.time() + 3
        alive = True
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                alive = False
                break
            # A reaped-by-init child can linger as a zombie briefly.
            st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
            if not st or st.startswith("Z"):
                alive = False
                break
            time.sleep(0.1)
        self.assertFalse(alive, "advertiser still running after SIGTERM")


if __name__ == "__main__":
    unittest.main()
