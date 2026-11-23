"""Day 32 (local branch, waiting on Brenden's review): cloud model API keys."""
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
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
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "tools"))
import cloud_keys as CK  # noqa: E402
import web_server  # noqa: E402
import web_picker  # noqa: E402
from web_workers import WorkerManager  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

KEY = "sk-test-ABCDEFGHIJKLMNOP1234wxyz"
ENV_NAMES = [n for p in CK.PROVIDERS.values() for n in p["env"]]
HTML = english_source(ROOT / "proxy/web/index.html")


def clean_env():
    return mock.patch.dict(os.environ, {k: "" for k in ENV_NAMES + ["CARAVAN_CLOUD_KEYS_PATH"]})


class Storage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        p = clean_env(); p.start(); self.addCleanup(p.stop)

    def test_providers(self):
        st = CK.status(home=self.home)
        self.assertEqual([p["id"] for p in st["providers"]], ["ollama"])
        self.assertTrue(all(not p["set"] for p in st["providers"]))

    def test_save_is_0600_under_caravan_and_shows_only_last4(self):
        st = CK.save("ollama", KEY, home=self.home)
        path = self.home / ".caravan" / "cloud-keys.json"
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        row = st["providers"][0]
        self.assertEqual((row["set"], row["source"], row["last4"]), (True, "settings", "wxyz"))
        self.assertNotIn(KEY, json.dumps(st))
        self.assertNotIn(KEY[:-4], json.dumps(st))
        self.assertEqual(CK.resolve("ollama", home=self.home), KEY)
        # No temp files left behind.
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["cloud-keys.json"])

    def test_replace_and_remove(self):
        CK.save("ollama", KEY, home=self.home)
        CK.save("ollama", "olk-NEWKEY-5678", home=self.home)
        self.assertEqual(CK.resolve("ollama", home=self.home), "olk-NEWKEY-5678")
        st = CK.remove("ollama", home=self.home)
        self.assertFalse(st["providers"][0]["set"])
        self.assertIsNone(CK.resolve("ollama", home=self.home))

    def test_bad_key_is_refused_without_repeating_it(self):
        bad = "sk bad key with spaces"
        with self.assertRaises(CK.CloudKeyError) as cm:
            CK.save("ollama", bad, home=self.home)
        self.assertNotIn(bad, str(cm.exception))
        with self.assertRaises(CK.CloudKeyError):
            CK.save("ollama", "short", home=self.home)
        # Only Ollama Cloud for now: other providers are unknown.
        for other in ("nope", "openai", "anthropic", "openrouter"):
            with self.assertRaises(CK.CloudKeyError):
                CK.save(other, KEY, home=self.home)

    def test_environment_wins_and_is_not_editable(self):
        CK.save("ollama", KEY, home=self.home)
        with mock.patch.dict(os.environ, {"OLLAMA_API_KEY": "olk-FROMENV-9999"}):
            row = CK.status(home=self.home)["providers"][0]
            self.assertEqual((row["source"], row["last4"], row["editable"]), ("environment", "9999", False))
            self.assertEqual(CK.resolve("ollama", home=self.home), "olk-FROMENV-9999")

    def test_broken_file_is_ignored(self):
        p = self.home / ".caravan" / "cloud-keys.json"
        p.parent.mkdir(parents=True)
        p.write_text("{not json")
        self.assertFalse(CK.status(home=self.home)["providers"][0]["set"])


class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = clean_env(); p.start(); self.addCleanup(p.stop)
        mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560", packer_ssh="nobody@127.0.0.1",
                            state_dir=Path(self.tmp.name) / "state", repo=ROOT)
        app = web_server.App(mgr)
        app.nodes = lambda: {"nodes": []}
        app.configured_nodes = lambda: []
        app.update_inspect = lambda: {}
        app.cloud_keys_home = Path(self.tmp.name)
        self.home = Path(self.tmp.name)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def req(self, body=None, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        r = Request(self.base + "/api/cloud-keys", data=None if body is None else json.dumps(body).encode(),
                    headers=h, method="GET" if body is None else "POST")
        try:
            with urlopen(r, timeout=5) as resp:
                return resp.status, resp.read().decode()
        except HTTPError as e:
            return e.code, e.read().decode()

    def test_set_get_remove_never_returns_the_key_or_logs_it(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, raw = self.req({"action": "set", "provider": "ollama", "key": KEY})
            self.assertEqual(code, 200, raw)
            code2, raw2 = self.req()
            code3, raw3 = self.req({"action": "remove", "provider": "ollama"})
        for r in (raw, raw2, raw3):
            self.assertNotIn(KEY, r)
            self.assertNotIn(KEY[:-4], r)
        row = [p for p in json.loads(raw2)["providers"] if p["id"] == "ollama"][0]
        self.assertEqual((row["set"], row["last4"]), (True, "wxyz"))
        self.assertFalse([p for p in json.loads(raw3)["providers"] if p["id"] == "ollama"][0]["set"])
        self.assertNotIn(KEY, err.getvalue())
        self.assertNotIn(KEY[:-4], err.getvalue())

    def test_bad_key_is_400_without_echo(self):
        code, raw = self.req({"action": "set", "provider": "ollama", "key": "bad key here!"})
        self.assertEqual(code, 400)
        self.assertNotIn("bad key here", raw)

    def test_local_network_cannot_read_or_change_keys(self):
        CK.save("ollama", KEY, home=self.home)
        code, raw = self.req(headers={"Host": "192.168.1.20:8190"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw), {"show": False, "providers": []})
        code, raw = self.req({"action": "remove", "provider": "ollama"}, headers={"Host": "192.168.1.20:8190"})
        self.assertEqual(code, 403)
        self.assertEqual(CK.resolve("ollama", home=self.home), KEY)


class Picker(unittest.TestCase):
    def cloud_rows(self):
        web_picker._SEARCH_CACHE.clear() if hasattr(web_picker, "_SEARCH_CACHE") else None
        out = web_picker.search_catalog("", source="cloud")
        return [q for g in out["groups"] for q in (g.get("quants") or [g]) if q.get("cloud")]

    def test_cloud_rows_say_provider_and_key(self):
        with tempfile.TemporaryDirectory() as td, clean_env(), \
                mock.patch.dict(os.environ, {"CARAVAN_CLOUD_KEYS_PATH": str(Path(td) / "k.json")}):
            cloud = self.cloud_rows()
            self.assertTrue(cloud)
            self.assertTrue(all(r["provider"] == "ollama" and r["api_key_configured"] is False for r in cloud))
            CK.save("ollama", KEY)
            self.assertTrue(all(r["api_key_configured"] for r in self.cloud_rows()))


class Page(unittest.TestCase):
    def test_settings_section(self):
        self.assertIn('id="cloudKeysCard"', HTML)
        self.assertIn(">Cloud API keys</span>", HTML)
        self.assertIn('input.type = "password";', HTML)
        self.assertIn('`Set · ends in ${p.last4', HTML)  # Day 32: the + chain is one string with values now
        self.assertIn('rm.textContent = "Remove";', HTML)
        self.assertIn("refreshCloudKeys();", HTML[HTML.index("const openDrawer = () => {"):][:200])

    def test_cloud_models_say_load_and_prompt_for_a_missing_key(self):
        self.assertIn('${q.cloud ? "Load" : "Download"}', HTML)
        self.assertIn("if (q.cloud) return loadCloudModel(q, anchor);", HTML)
        self.assertIn("m.cloud ? \"cloud — open Models to Load\"", HTML)
        self.assertNotIn("framework-only for now. Set OLLAMA_API_KEY", HTML)
        fn = HTML[HTML.index("async function loadCloudModel"):HTML.index("function continueCloudLoad")]
        self.assertIn('box.className = "cloud-key-prompt";', fn)
        self.assertIn('saveText: "Save and load"', fn)
        self.assertIn("continueCloudLoad(q, now);", fn)

    def test_page_never_keeps_the_key(self):
        ed = HTML[HTML.index("function cloudKeyEditor"):HTML.index("function renderCloudKeys")]
        self.assertEqual(ed.count('input.value = "";'), 2)  # cleared after save and after an error
        self.assertNotIn("localStorage", ed)
        self.assertNotIn("console.", ed)


if __name__ == "__main__":
    unittest.main()
