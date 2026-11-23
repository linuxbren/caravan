"""Day 32 fix: daily update check setting, live toggle, and the daily loop."""
from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "tests"))
import caravan_update_check as UC  # noqa: E402
import web_server  # noqa: E402
from web_workers import WorkerManager  # noqa: E402
from test_day26_update_check import (  # noqa: E402
    NEW, OLD, SHA, FakeOpener, _offline_app, opener_for, write_package,
)
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

DAY = 86400


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.repo = write_package(Path(self.tmp.name) / "repo")

    def status(self, result, **kw):
        prefs = UC.load_prefs(self.home)
        kw.setdefault("check_daily", prefs["check_daily"])
        kw.setdefault("daily_changed_at", prefs["changed_at"])
        return UC.public_status(result, packaged=True, local=True, installed=OLD, **kw)


class DailyOffHidesStatus(Base):
    def test_daily_off_hides_a_saved_newer_answer(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(), now=1000)
        UC.save_prefs(self.home, check_daily=False, now=2000)
        p = self.status(UC.load_cache(self.home))
        self.assertFalse(p["check_daily"])
        self.assertTrue(p["daily_hidden"])
        self.assertFalse(p["newer"])          # no badge
        self.assertFalse(p["peers_behind"])
        self.assertIsNone(p["checked_at"])    # label: just the version
        self.assertEqual(p["macs"], [])       # no Mac lines
        self.assertIsNone(p["message"])
        self.assertFalse(p["can_apply"])
        self.assertEqual(p["changes"], [])

    def test_daily_off_hides_a_saved_up_to_date_answer(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(newer=False), now=1000)
        UC.save_prefs(self.home, check_daily=False, now=2000)
        p = self.status(UC.load_cache(self.home))
        self.assertIsNone(p["checked_at"])
        self.assertEqual(p["macs"], [])

    def test_check_now_before_turning_off_is_hidden_too(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for(), now=1000)
        UC.save_prefs(self.home, check_daily=False, now=2000)
        self.assertTrue(self.status(UC.load_cache(self.home))["daily_hidden"])

    def test_check_now_while_off_still_shows(self):
        UC.save_prefs(self.home, check_daily=False, now=2000)
        UC.check(self.home, self.repo, force=True, opener=opener_for(), now=3000)
        p = self.status(UC.load_cache(self.home))
        self.assertFalse(p["daily_hidden"])
        self.assertTrue(p["newer"])
        self.assertEqual(p["checked_at"], 3000)

    def test_current_setting_wins_over_the_one_saved_with_the_check(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(), now=1000)
        cache = UC.load_cache(self.home)
        self.assertTrue(cache["check_daily"])
        p = UC.public_status(cache, packaged=True, local=True, check_daily=False, daily_changed_at=2000)
        self.assertFalse(p["check_daily"])
        self.assertFalse(p["newer"])

    def test_a_running_update_is_still_shown_while_off(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(), now=1000)
        UC.save_prefs(self.home, check_daily=False, now=2000)
        prog = {"phase": "updating", "started_at": 2100, "expected": NEW,
                "macs": [{"id": "local", "mine": True, "label": "My Mac", "phase": "updating"}]}
        p = self.status(UC.load_cache(self.home), progress=prog)
        self.assertFalse(p["daily_hidden"])
        self.assertTrue(p["updating"])

    def test_turning_back_on_shows_the_saved_answer(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(), now=1000)
        UC.save_prefs(self.home, check_daily=False, now=2000)
        UC.save_prefs(self.home, check_daily=True, now=3000)
        p = self.status(UC.load_cache(self.home))
        self.assertFalse(p["daily_hidden"])
        self.assertTrue(p["newer"])
        self.assertEqual(p["checked_at"], 1000)

    def test_old_prefs_file_without_changed_at(self):
        UC.save_json(UC.prefs_path(self.home), {"check_daily": False})
        prefs = UC.load_prefs(self.home)
        self.assertEqual(prefs, {"check_daily": False, "changed_at": 0.0})


class DueAndOffline(Base):
    def test_due_once_a_day(self):
        cache = {"checked_at": 1000, "installed": OLD, "available": OLD}
        self.assertFalse(UC.due_for_check(cache, now=1000 + DAY - 1, installed=OLD))
        self.assertTrue(UC.due_for_check(cache, now=1000 + DAY, installed=OLD))

    def test_a_check_saved_in_the_future_is_due(self):
        cache = {"checked_at": 10 * DAY, "installed": OLD, "available": OLD}
        self.assertTrue(UC.due_for_check(cache, now=1000, installed=OLD))

    def test_offline_is_saved_and_retried_hourly(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(newer=False), now=1000)
        down = FakeOpener(fail=OSError("down"))
        r = UC.check(self.home, self.repo, force=False, opener=down, now=1000 + DAY)
        self.assertTrue(r["offline"])
        cache = UC.load_cache(self.home)
        self.assertTrue(cache["offline"])                  # saved: page and label stop saying up to date
        self.assertEqual(cache["checked_at"], 1000)        # the last good answer's time is kept
        self.assertEqual(cache["attempted_at"], 1000 + DAY)
        self.assertFalse(UC.due_for_check(cache, now=1000 + DAY + 1800, installed=OLD))
        self.assertTrue(UC.due_for_check(cache, now=1000 + DAY + 3600, installed=OLD))
        self.assertEqual(self.status(cache)["offline"], True)

    def test_failed_check_now_with_fresh_answer_retries_within_the_hour(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(newer=False), now=1000)
        UC.check(self.home, self.repo, force=True, opener=FakeOpener(fail=OSError("x")), now=2000)
        cache = UC.load_cache(self.home)
        self.assertTrue(UC.due_for_check(cache, now=2000 + 3600, installed=OLD))

    def test_back_online_clears_offline(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(newer=False), now=1000)
        UC.check(self.home, self.repo, force=False, opener=FakeOpener(fail=OSError("x")), now=1000 + DAY)
        r = UC.check(self.home, self.repo, force=False, opener=opener_for(newer=False), now=1000 + DAY + 3600)
        self.assertFalse(r["offline"])
        self.assertFalse(UC.load_cache(self.home)["offline"])

    def test_broken_http_response_is_quiet(self):
        def boom(req, timeout=None):
            raise http.client.IncompleteRead(b"")
        self.assertIsNone(UC.fetch_published(opener=boom))
        self.assertIsNone(UC.fetch_compare(OLD, NEW, opener=boom))
        self.assertIsNone(UC.fetch_commit_date(OLD, opener=boom))
        r = UC.check(self.home, self.repo, force=True, opener=boom, now=1000)
        self.assertTrue(r["offline"])


class ComparesThePin(Base):
    def test_compares_installed_pin_with_published_manifest(self):
        r = UC.check(self.home, self.repo, force=True, opener=opener_for(), now=1000)
        self.assertEqual(r["installed"], OLD)
        self.assertEqual(r["available"], NEW)
        self.assertTrue(r["newer"])
        self.assertTrue(any("packaging-version" in u for u in opener_for().mapping))

    def test_after_this_mac_updates_the_saved_answer_is_not_newer(self):
        r = UC.check(self.home, self.repo, force=True, opener=opener_for(), now=1000)
        p = UC.public_status(r, packaged=True, local=True, check_daily=True, installed=NEW)
        self.assertFalse(p["newer"])

    def test_new_install_triggers_a_check(self):
        UC.check(self.home, self.repo, force=False, opener=opener_for(), now=1000)
        write_package(self.repo, ref=NEW)
        self.assertTrue(UC.due_for_check(UC.load_cache(self.home), now=1100, installed=NEW))


class DailyLoop(Base):
    def test_loop_survives_a_failed_round(self):
        calls = []
        orig = UC.maybe_auto_check

        def flaky(home, repo, **kw):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("disk full")
            return orig(home, repo, **kw)
        logs = []
        UC.maybe_auto_check = flaky
        try:
            UC.run_daily_loop(self.home, self.repo, sleep=lambda s: None, rounds=3,
                              log=logs.append, opener=opener_for(newer=False))
        finally:
            UC.maybe_auto_check = orig
        self.assertEqual(len(calls), 3)
        self.assertIn("disk full", logs[0])
        self.assertIsNotNone(UC.load_cache(self.home))

    def test_loop_checks_once_a_day_across_restarts(self):
        op = opener_for(newer=False)
        UC.run_daily_loop(self.home, self.repo, sleep=lambda s: None, rounds=1, opener=op, now=1000)
        n = len(op.calls)
        self.assertGreater(n, 0)
        # A "restart" an hour later: the saved check is fresh, no fetch.
        UC.run_daily_loop(self.home, self.repo, sleep=lambda s: None, rounds=1, opener=op, now=1000 + 3600)
        self.assertEqual(len(op.calls), n)
        UC.run_daily_loop(self.home, self.repo, sleep=lambda s: None, rounds=1, opener=op, now=1000 + DAY)
        self.assertGreater(len(op.calls), n)

    def test_loop_honors_the_setting(self):
        UC.save_prefs(self.home, check_daily=False)
        op = opener_for()
        UC.run_daily_loop(self.home, self.repo, sleep=lambda s: None, rounds=2, opener=op)
        self.assertEqual(op.calls, [])

    def test_loop_sleeps_an_hour_between_rounds(self):
        slept = []
        UC.run_daily_loop(self.home, self.repo, sleep=slept.append, rounds=3, opener=opener_for(newer=False))
        self.assertEqual(slept, [3600, 3600])

    def test_web_server_uses_the_loop(self):
        src = english_source(ROOT / "proxy/web_server.py")
        self.assertIn("_UC.run_daily_loop(", src)


class ToggleApi(unittest.TestCase):
    def setUp(self):
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560",
                            packer_ssh="nobody@127.0.0.1", state_dir=Path(state.name), repo=ROOT)
        app = web_server.App(mgr)
        _offline_app(app)
        self.home = Path(state.name) / "home"
        self.home.mkdir()
        self.repo = write_package(Path(state.name) / "repo")
        app.update_home = self.home
        app.update_repo = self.repo
        self.opener = opener_for()
        app.update_opener = self.opener
        app.update_inspect = lambda: {}
        app.update_ssh = lambda *a, **k: (_ for _ in ()).throw(OSError("no ssh in tests"))

        class _S(ThreadingHTTPServer):
            def server_bind(self):
                import socketserver
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = self.server_address[:2]
        self.httpd = _S(("127.0.0.1", 0), web_server.make_handler(app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def _req(self, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(self.base + "/api/update", data=data,
                      headers={"Content-Type": "application/json"},
                      method="POST" if body is not None else "GET")
        try:
            with urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            return json.loads(e.read().decode())

    def test_off_clears_and_on_restores_from_a_fresh_answer(self):
        UC.check(self.home, self.repo, force=False, opener=self.opener)
        self.assertTrue(self._req()["newer"])
        off = self._req({"action": "set", "check_daily": False})
        self.assertTrue(off["daily_hidden"])
        self.assertFalse(off["newer"])
        self.assertIsNone(off["checked_at"])
        self.assertEqual(off["macs"], [])
        got = self._req()
        self.assertTrue(got["daily_hidden"])
        n = len(self.opener.calls)
        on = self._req({"action": "set", "check_daily": True})
        self.assertFalse(on["daily_hidden"])
        self.assertTrue(on["newer"])
        self.assertIsNotNone(on["checked_at"])
        self.assertEqual(len(self.opener.calls), n)   # fresh: no new fetch

    def test_on_with_a_stale_answer_checks_right_away(self):
        UC.check(self.home, self.repo, force=False, opener=self.opener, now=1000)
        self._req({"action": "set", "check_daily": False})
        n = len(self.opener.calls)
        on = self._req({"action": "set", "check_daily": True})
        self.assertGreater(len(self.opener.calls), n)
        self.assertGreater(on["checked_at"], 1000)
        self.assertTrue(on["newer"])

    def test_check_now_while_off_shows_the_answer(self):
        self._req({"action": "set", "check_daily": False})
        j = self._req({"action": "check"})
        self.assertFalse(j["daily_hidden"])
        self.assertTrue(j["newer"])
        self.assertTrue(self._req()["newer"])
        blob = json.dumps(j)
        self.assertNotIn(NEW, blob)
        self.assertNotIn(SHA, blob)


class Page(unittest.TestCase):
    html = english_source(ROOT / "proxy/web/index.html")

    def test_version_state_honors_daily_hidden_in_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        js = self.html[self.html.index("function versionState"):self.html.index("function paintVersionLabel")]
        prog = js + """
const cases = [[{checked_at:1, daily_hidden:true, check_daily:false}, ""],
  [{newer:true, daily_hidden:true}, ""], [{checked_at:1, check_daily:false}, "ok"],
  [{checked_at:1, check_daily:true}, "ok"], [{newer:true, check_daily:false}, "update"]];
for (const [u, want] of cases) { if (versionState(u) !== want) { console.log("FAIL", JSON.stringify(u)); process.exit(1); } }
console.log("ok");
"""
        out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.stdout.strip(), "ok", out.stdout + out.stderr)

    def test_toggle_repaints_live(self):
        i = self.html.index('$("updateDailySwitch").addEventListener("click"')
        handler = self.html[i:i + 1800]
        self.assertIn("daily_hidden: true", handler)
        self.assertIn("renderUpdate(Object.assign({}, _updateInfo", handler)
        self.assertIn('action: "set"', handler)
        # renderUpdate repaints the label and the badge from the same answer.
        render = self.html[self.html.index("function renderUpdate(j)"):]
        self.assertIn("paintVersionLabel();", render[:500])
        self.assertIn("paintUpdateBadge(j);", render)


if __name__ == "__main__":
    unittest.main()
