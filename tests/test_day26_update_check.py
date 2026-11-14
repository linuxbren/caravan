"""Daily update check, cache, offline, keep-model preview, and endpoint guards."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))
import caravan_update_check as UC  # noqa: E402
import caravan as cli  # noqa: E402
import web_server  # noqa: E402
from web_workers import WorkerManager  # noqa: E402


OLD = "a" * 40
NEW = "b" * 40
SHA = "c" * 64
MANIFEST = f"{NEW} {SHA}\n"
SAME = f"{OLD} {SHA}\n"


def write_package(folder, ref=OLD):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".caravan-package").write_text(ref + "\n")
    (folder / ".caravan-package-files").write_text("")
    (folder / ".caravan-role").write_text("lead\n")
    return folder


class FakeResponse:
    def __init__(self, body, url=""):
        if isinstance(body, str):
            body = body.encode()
        self._body = body
        self.url = url

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, mapping=None, fail=None):
        self.mapping = dict(mapping or {})
        self.fail = fail
        self.calls = []

    def __call__(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        self.calls.append(url)
        if self.fail:
            raise self.fail
        for key, value in self.mapping.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return FakeResponse(value, url)
        raise OSError("offline: " + url)


def compare_payload(subjects, files, date="2026-11-13T18:00:00Z"):
    commits = []
    for subject in subjects:
        commits.append({
            "sha": "d" * 40,
            "commit": {
                "message": subject,
                "committer": {"date": date},
                "author": {"date": date},
            },
        })
    return json.dumps({
        "commits": commits,
        "files": [{"filename": f} for f in files],
    })


def commit_payload(date="2026-11-12T18:00:00Z", message="Day 25 pin"):
    return json.dumps({
        "commit": {
            "message": message,
            "committer": {"date": date},
            "author": {"date": date},
        }
    })


def opener_for(newer=True, files=None, subjects=None, old_date="2026-11-12T18:00:00Z"):
    files = files if files is not None else ["proxy/web_server.py", "docs/DAY26.md"]
    subjects = subjects if subjects is not None else [
        "Publish Day 26 follow-up Voice design notes source pin",
        "Day 26: Daily update check and Update in Settings",
    ]
    published = MANIFEST if newer else SAME
    mapping = {
        "packaging-version": published,
        "compare/": compare_payload(subjects, files),
        f"commits/{OLD}": commit_payload(old_date),
        f"commits/{NEW}": commit_payload("2026-11-13T18:00:00Z"),
    }
    return FakeOpener(mapping)


class ManifestAndLabelTests(unittest.TestCase):
    def test_parse_manifest_accepts_valid_line(self):
        parsed = UC.parse_manifest(f"  {OLD}   {SHA}\n")
        self.assertEqual(parsed["ref"], OLD)
        self.assertEqual(parsed["sha256"], SHA)

    def test_parse_manifest_rejects_short_or_non_hex(self):
        self.assertIsNone(UC.parse_manifest(""))
        self.assertIsNone(UC.parse_manifest("abcd efgh"))
        self.assertIsNone(UC.parse_manifest(OLD + " " + "g" * 64))
        self.assertIsNone(UC.parse_manifest(OLD))

    def test_plain_date_uses_chicago_zone(self):
        # 11pm UTC on Nov 12 is still Nov 12 in Chicago (UTC-6).
        self.assertEqual(UC.plain_date("2026-11-12T18:00:00Z"), "November 12")
        # 5am UTC on Nov 13 is Nov 12 in Chicago.
        self.assertEqual(UC.plain_date("2026-11-13T05:00:00Z"), "November 12")
        # Afternoon UTC on Nov 13 is Nov 13 in Chicago.
        self.assertEqual(UC.plain_date("2026-11-13T18:00:00Z"), "November 13")

    def test_pin_subjects_are_skipped_in_preview(self):
        payload = json.loads(compare_payload(
            [
                "Publish Day 26 follow-up Voice design notes source pin",
                "Day 26: Daily update check and Update in Settings",
                "Publish Day 26 follow-up update-check source pin",
            ],
            ["proxy/web/index.html"],
        ))
        preview = UC.preview_from_compare(payload)
        self.assertEqual(preview["changes"], ["Day 26: Daily update check and Update in Settings"])
        self.assertIs(preview["reload_model"], False)

    def test_keep_model_from_web_only_files(self):
        self.assertFalse(UC.reload_model_from_files([
            "proxy/web_server.py", "tools/caravan.py", "docs/DAY26.md",
        ]))
        self.assertEqual(UC.keep_model_text(False), UC.KEEP_MODEL)

    def test_reload_model_from_agent_or_requirements(self):
        self.assertTrue(UC.reload_model_from_files(["agent/mlx_worker.py"]))
        self.assertTrue(UC.reload_model_from_files(["runtime/llama-release.json"]))
        self.assertTrue(UC.reload_model_from_files(["requirements-mac.lock"]))
        self.assertTrue(UC.reload_model_from_files(["requirements-mac.txt"]))
        self.assertEqual(UC.keep_model_text(True), UC.RELOAD_MODEL)
        self.assertIsNone(UC.keep_model_text(None))


class CacheAndOfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.repo = write_package(Path(self.tmp.name) / "repo")
        self.home.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_check_finds_a_newer_pin(self):
        result = UC.check(self.home, self.repo, force=True, opener=opener_for())
        self.assertTrue(result["newer"])
        self.assertEqual(result["available"], NEW)
        self.assertEqual(result["current_label"], "November 12")
        self.assertEqual(result["available_label"], "November 13")
        self.assertIn("Daily update check and Update in Settings", " ".join(result["changes"]))
        self.assertIs(result["reload_model"], False)
        self.assertFalse(result["offline"])

    def test_fresh_cache_is_not_refetched(self):
        opener = opener_for()
        first = UC.check(self.home, self.repo, force=True, opener=opener, now=1000)
        n = len(opener.calls)
        second = UC.check(
            self.home, self.repo, force=False, opener=opener, now=1000 + 60, interval=86400,
        )
        self.assertEqual(len(opener.calls), n)
        self.assertEqual(second["available"], first["available"])
        self.assertTrue(second["newer"])

    def test_stale_cache_is_refetched(self):
        opener = opener_for()
        UC.check(self.home, self.repo, force=True, opener=opener, now=1000)
        n = len(opener.calls)
        UC.check(
            self.home, self.repo, force=False, opener=opener, now=1000 + 90000, interval=86400,
        )
        self.assertGreater(len(opener.calls), n)

    def test_due_when_installed_version_changes(self):
        cache = {"checked_at": 1000, "installed": OLD, "available": NEW}
        self.assertTrue(UC.due_for_check(cache, now=1100, interval=86400, installed=NEW))
        self.assertFalse(UC.due_for_check(cache, now=1100, interval=86400, installed=OLD))

    def test_offline_keeps_cache_and_does_not_raise(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for(), now=1000)
        result = UC.check(
            self.home, self.repo, force=True,
            opener=FakeOpener(fail=OSError("network down")),
            now=2000,
        )
        self.assertTrue(result["newer"])
        self.assertTrue(result["offline"])
        self.assertEqual(result["available"], NEW)

    def test_offline_with_no_cache_is_quiet(self):
        result = UC.check(
            self.home, self.repo, force=True,
            opener=FakeOpener(fail=OSError("offline")),
        )
        self.assertFalse(result["newer"])
        self.assertTrue(result["offline"])
        self.assertIsNone(result["available"])
        payload = UC.public_status(result, packaged=True)
        # Automatic quiet: no alarm message when a first check is offline.
        self.assertFalse(payload["newer"])
        self.assertIsNone(payload["message"])

    def test_same_pin_is_up_to_date(self):
        result = UC.check(self.home, self.repo, force=True, opener=opener_for(newer=False))
        self.assertFalse(result["newer"])
        self.assertEqual(result["available"], OLD)
        payload = UC.public_status(result, packaged=True)
        # No confusing "This Mac is on the … version." line: one line per Mac.
        self.assertIsNone(payload["message"])
        self.assertEqual(
            [(m["label"], m["status"]) for m in payload["macs"]],
            [("My Mac", "current")],
        )

    def test_each_mac_gets_one_status_line_in_the_same_format(self):
        result = UC.check(self.home, self.repo, force=True, opener=opener_for())
        result["macs"] = [
            {"id": "a", "label": "2nd Mac", "mine": False, "phase": "current", "status": "current", "help": []},
            {"id": "b", "label": "3rd Mac", "mine": False, "phase": "offline", "status": "failed", "help": ["x"]},
        ]
        payload = UC.public_status(result, packaged=True, local=True)
        self.assertEqual(payload["message"], "A November 13 update is ready.")
        self.assertEqual(
            [(m["label"], m["status"]) for m in payload["macs"]],
            [("1st Mac", "update available"), ("2nd Mac", "current"),
             ("3rd Mac", "couldn't check")],
        )
        # Not reaching a Mac during a check is not a failed update.
        self.assertFalse(payload["can_retry"])
        self.assertNotIn("This Mac is on the", json.dumps(payload))

    def test_check_daily_off_skips_automatic_check(self):
        UC.save_prefs(self.home, check_daily=False)
        opener = opener_for()
        out = UC.maybe_auto_check(self.home, self.repo, opener=opener, now=1000)
        self.assertFalse(opener.calls)
        # Manual Check now still runs.
        result = UC.check(self.home, self.repo, force=True, opener=opener)
        self.assertTrue(result["newer"])
        self.assertTrue(opener.calls)

    def test_check_daily_defaults_to_on(self):
        self.assertTrue(UC.load_prefs(self.home)["check_daily"])

    def test_source_checkout_does_not_claim_an_update(self):
        bare = Path(self.tmp.name) / "src"
        bare.mkdir()
        result = UC.check(self.home, bare, force=True, opener=opener_for())
        self.assertFalse(result["newer"])
        self.assertEqual(result["error"], "not-packaged")
        payload = UC.public_status(result, packaged=False)
        self.assertIn("source checkout", payload["message"].lower())
        self.assertFalse(payload["can_apply"])

    def test_helper_note_when_a_second_mac_is_recorded(self):
        ui = self.home / ".caravan" / "web-ui"
        ui.mkdir(parents=True)
        (ui / "remote-worker.json").write_text(json.dumps({"ssh": "helper-mac"}))
        def silent_ssh(*args, **kwargs):
            raise OSError("offline")
        result = UC.check(
            self.home, self.repo, force=True, opener=opener_for(),
            ssh_runner=silent_ssh,
        )
        self.assertTrue(result["helper"])
        payload = UC.public_status(result, packaged=True, local=True)
        self.assertIn("other Macs", payload["helper_text"])

    def test_progress_promotes_to_done_when_the_new_ref_is_installed(self):
        UC.save_progress(self.home, {
            "phase": "updating",
            "expected": NEW,
            "old": OLD,
            "started_at": time.time(),
            "message": UC.OPENING,
        })
        write_package(self.repo, ref=NEW)
        out = UC.resolve_progress(self.home, self.repo)
        self.assertEqual(out["phase"], "done")
        self.assertEqual(UC.load_progress(self.home)["phase"], "done")

    def test_progress_promotes_to_failed_after_timeout_on_old_ref(self):
        UC.save_progress(self.home, {
            "phase": "updating",
            "expected": NEW,
            "old": OLD,
            "started_at": time.time() - 400,
            "message": UC.OPENING,
        })
        out = UC.resolve_progress(self.home, self.repo)
        self.assertEqual(out["phase"], "failed")
        self.assertIn("previous version", out["message"])


class LocalOwnerAndBusyTests(unittest.TestCase):
    def handler(self, addr="127.0.0.1", host="127.0.0.1:8190", extra=None):
        class H:
            pass
        h = H()
        h.client_address = (addr, 54321)
        headers = {"Host": host}
        if extra:
            headers.update(extra)
        h.headers = {k: v for k, v in headers.items()}
        # Case-insensitive get like HTTP headers
        class Headers(dict):
            def get(self, key, default=None):
                for k, v in self.items():
                    if k.lower() == str(key).lower():
                        return v
                return default
        h.headers = Headers(headers)
        return h

    def test_loopback_host_and_client_is_local(self):
        self.assertTrue(UC.is_local_owner(self.handler()))
        self.assertTrue(UC.is_local_owner(self.handler(host="localhost:8190")))
        self.assertTrue(UC.is_local_owner(self.handler(addr="::1", host="[::1]:8190")))

    def test_lan_address_is_not_local(self):
        self.assertFalse(UC.is_local_owner(self.handler(addr="192.168.1.50", host="192.168.1.20:8190")))
        # Forged Host from a LAN client is still refused.
        self.assertFalse(UC.is_local_owner(self.handler(addr="192.168.1.50", host="127.0.0.1:8190")))

    def test_tailscale_host_on_loopback_is_not_local(self):
        # Tailscale serve proxies to 127.0.0.1 with the tailnet Host name.
        self.assertFalse(UC.is_local_owner(self.handler(host="my-mac.tailnet.ts.net")))
        self.assertFalse(UC.is_local_owner(self.handler(
            extra={"X-Forwarded-For": "100.64.1.2"},
        )))

    def test_busy_reason_for_reply_and_tune(self):
        class App:
            _inflight = 1
            optimizer = None
            mgr = None
        self.assertEqual(UC.busy_reason(App())[0], "reply")

        class Opt:
            def snapshot(self):
                return {"running": True}

        class App2:
            _inflight = 0
            optimizer = Opt()
            mgr = None
        kind, msg = UC.busy_reason(App2())
        self.assertEqual(kind, "tune")
        self.assertIn("Auto-tune", msg)


class CliCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.repo = write_package(Path(self.tmp.name) / "repo")
        self.home.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_check_prints_newer_and_keep_model(self):
        buf = io.StringIO()
        code = UC.cli_check(self.repo, home=self.home, opener=opener_for(), file=buf)
        self.assertEqual(code, 1)
        text = buf.getvalue()
        self.assertIn("November 13 update is ready", text)
        self.assertIn("Your model stays loaded.", text)
        self.assertIn("What's new:", text)
        self.assertIn("Daily update check and Update in Settings", text)
        self.assertIn("Run caravan update to install it.", text)
        self.assertNotIn(NEW, text)  # no hash up front

    def test_check_prints_reload_when_agent_changes(self):
        buf = io.StringIO()
        opener = opener_for(files=["agent/mlx_worker.py"])
        code = UC.cli_check(self.repo, home=self.home, opener=opener, file=buf)
        self.assertEqual(code, 1)
        self.assertIn("Caravan will reload the model.", buf.getvalue())

    def test_check_up_to_date(self):
        buf = io.StringIO()
        code = UC.cli_check(self.repo, home=self.home, opener=opener_for(newer=False), file=buf)
        self.assertEqual(code, 0)
        self.assertIn(UC.UP_TO_DATE, buf.getvalue())

    def test_check_offline(self):
        buf = io.StringIO()
        code = UC.cli_check(
            self.repo, home=self.home,
            opener=FakeOpener(fail=OSError("down")), file=buf,
        )
        self.assertEqual(code, 2)
        self.assertIn("Could not check", buf.getvalue())

    def test_caravan_update_check_dispatches(self):
        with mock.patch.object(cli, "ROOT", self.repo), \
             mock.patch.object(UC, "cli_check", return_value=1) as check, \
             contextlib.redirect_stdout(io.StringIO()):
            # Import happens inside caravan.py; patch the symbol it will import
            with mock.patch.dict(sys.modules, {}):
                pass
            # The CLI imports caravan_update_check.cli_check at call time.
        with mock.patch.object(cli, "ROOT", self.repo):
            with mock.patch("caravan_update_check.cli_check", return_value=1) as fn:
                self.assertEqual(cli.main(["update", "--check"]), 1)
                fn.assert_called()
                self.assertEqual(Path(fn.call_args[0][0]), self.repo)

    def test_update_without_check_still_refuses_a_developer_checkout(self):
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(cli, "ROOT", Path(root)), \
             mock.patch.object(cli.urllib.request, "urlopen") as network, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["update"]), 2)
            network.assert_not_called()

    def test_update_check_on_source_checkout_does_not_install(self):
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(cli, "ROOT", Path(root)), \
             mock.patch.object(cli.urllib.request, "urlopen") as network, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["update", "--check"]), 2)
            network.assert_not_called()
            self.assertIn("source checkout", out.getvalue())


def _offline_app(app):
    app.nodes = lambda: {"nodes": []}
    app.configured_nodes = lambda: []
    return app


class UpdateApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        state = tempfile.TemporaryDirectory()
        cls.addClassCleanup(state.cleanup)
        mgr = WorkerManager(
            lead_port=8194, packer_peer="127.0.0.1:5560",
            packer_ssh="nobody@127.0.0.1",
            state_dir=Path(state.name),
            repo=ROOT,
        )
        cls.app = web_server.App(mgr)
        _offline_app(cls.app)
        cls.home = Path(state.name) / "home"
        cls.repo = write_package(Path(state.name) / "repo")
        cls.home.mkdir()
        cls.app.update_home = cls.home
        cls.app.update_repo = cls.repo
        cls.app.update_opener = opener_for()
        cls.started = []
        def _start(home, repo, **kwargs):
            cls.started.append((home, repo, kwargs))
            return {"phase": "updating", "message": UC.OPENING, "expected": NEW, "old": OLD}
        cls.app.update_start = _start
        cls.app.update_inspect = lambda: {}
        cls.app.update_ssh = lambda *a, **k: (_ for _ in ()).throw(OSError("no ssh in tests"))

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

    def _get(self, path, headers=None):
        req = Request(self.base + path, headers=headers or {})
        with urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())

    def _post(self, path, body, headers=None):
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        req = Request(
            self.base + path, data=json.dumps(body).encode(),
            headers=hdrs, method="POST",
        )
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_get_reports_a_newer_version_without_hashes(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        code, j = self._get("/api/update")
        self.assertEqual(code, 200)
        self.assertTrue(j["newer"])
        self.assertTrue(j["local"])
        self.assertTrue(j["can_apply"])
        self.assertEqual(j["keep_model_text"], "Your model stays loaded.")
        self.assertIn("November 13", j["message"])
        self.assertIn("Daily update check", " ".join(j["changes"]))
        blob = json.dumps(j)
        self.assertNotIn(NEW, blob)
        self.assertNotIn(OLD, blob)
        self.assertNotIn(SHA, blob)

    def test_apply_from_lan_host_is_forbidden(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        self.started.clear()
        code, j = self._post(
            "/api/update", {"action": "apply"},
            headers={"Host": "192.168.1.20:8190"},
        )
        self.assertEqual(code, 403)
        self.assertIn("on this Mac", j["error"])
        self.assertFalse(self.started)

    def test_apply_from_tailscale_host_is_forbidden(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        self.started.clear()
        code, j = self._post(
            "/api/update", {"action": "apply"},
            headers={"Host": "my-mac.tailnet.ts.net"},
        )
        self.assertEqual(code, 403)
        self.assertFalse(self.started)

    def test_apply_local_starts_the_update(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        self.started.clear()
        self.app._inflight = 0
        code, j = self._post("/api/update", {"action": "apply"})
        self.assertEqual(code, 200, j)
        self.assertEqual(j["progress"]["phase"], "updating")
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.started[0][2].get("expected"), NEW)

    def test_apply_while_chat_is_busy_is_conflict(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        self.started.clear()
        self.app._inflight = 1
        try:
            code, j = self._post("/api/update", {"action": "apply"})
            self.assertEqual(code, 409)
            self.assertIn("reply", j["error"])
            self.assertFalse(self.started)
        finally:
            self.app._inflight = 0

    def test_apply_while_autotune_is_busy_is_conflict(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        self.started.clear()

        class Opt:
            def snapshot(self):
                return {"running": True}
        prev = self.app.optimizer
        self.app.optimizer = Opt()
        try:
            code, j = self._post("/api/update", {"action": "apply"})
            self.assertEqual(code, 409)
            self.assertIn("Auto-tune", j["error"])
            self.assertFalse(self.started)
        finally:
            self.app.optimizer = prev

    def test_set_check_daily_and_check_now(self):
        code, j = self._post("/api/update", {"action": "set", "check_daily": False})
        self.assertEqual(code, 200, j)
        self.assertFalse(j["check_daily"])
        self.assertFalse(UC.load_prefs(self.home)["check_daily"])
        code, j = self._post("/api/update", {"action": "check"})
        self.assertEqual(code, 200, j)
        self.assertTrue(j["newer"])
        # Turn it back on so later tests stay on the default.
        self._post("/api/update", {"action": "set", "check_daily": True})

    def test_get_is_allowed_from_a_lan_host(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        code, j = self._get("/api/update", headers={"Host": "192.168.1.20:8190"})
        self.assertEqual(code, 200)
        # The local network gets no update view at all: nothing to render.
        self.assertEqual(j, {"show": False})
        code, j = self._post("/api/update", {"action": "check"}, headers={"Host": "192.168.1.20:8190"})
        self.assertEqual(code, 403)
        self.assertFalse(j["show"])


    def test_apply_from_verified_tailscale_is_allowed(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        self.started.clear()
        self.app.update_inspect = lambda: {
            "enabled": True,
            "funnel": False,
            "addresses": ["http://my-mac.tailnet.ts.net:8190"],
        }
        try:
            code, j = self._post(
                "/api/update", {"action": "apply"},
                headers={"Host": "my-mac.tailnet.ts.net"},
            )
            self.assertEqual(code, 200, j)
            self.assertTrue(self.started)
            self.assertTrue(j.get("via_tailscale") or j.get("can_apply"))
        finally:
            self.app.update_inspect = lambda: {}

    def test_apply_from_spoofed_tailscale_name_is_forbidden(self):
        UC.check(self.home, self.repo, force=True, opener=opener_for())
        self.started.clear()
        self.app.update_inspect = lambda: {
            "enabled": True,
            "funnel": False,
            "addresses": ["http://my-mac.tailnet.ts.net:8190"],
        }
        try:
            code, j = self._post(
                "/api/update", {"action": "apply"},
                headers={"Host": "not-mine.tailnet.ts.net"},
            )
            self.assertEqual(code, 403, j)
            self.assertFalse(self.started)
        finally:
            self.app.update_inspect = lambda: {}

    def test_retry_action_tries_one_mac(self):
        called = []

        def _retry(home, mac_id, **kwargs):
            called.append(mac_id)
            return {"id": mac_id, "label": "2nd Mac", "phase": "done", "help": [], "can_retry": False, "mine": False}

        self.app.update_retry = _retry
        try:
            code, j = self._post("/api/update", {"action": "retry", "mac": "mac-1"})
            self.assertEqual(code, 200, j)
            self.assertEqual(called, ["mac-1"])
        finally:
            self.app.update_retry = None

    def test_apply_when_only_a_peer_is_behind(self):
        result = {
            "newer": False,
            "installed": NEW,
            "available": NEW,
            "peers_behind": True,
            "macs": [{
                "id": "mac-1", "label": "2nd Mac", "phase": "behind",
                "behind": True, "help": ["Check that the 2nd Mac is on and awake."],
                "can_retry": True, "mine": False, "status": "on an older version",
                "message": "The 2nd Mac is on an older version.",
            }],
            "helper": True,
            "checked_at": 1,
        }
        UC.save_cache(self.home, result)
        self.started.clear()
        with mock.patch.object(UC, "check", return_value=result):
            code, j = self._post("/api/update", {"action": "apply"})
        self.assertEqual(code, 200, j)
        self.assertTrue(self.started)



class PageAndDocsTests(unittest.TestCase):
    def setUp(self):
        self.page = (ROOT / "proxy" / "web" / "index.html").read_text()
        self.day26 = (ROOT / "docs" / "DAY26.md").read_text()
        self.web = (ROOT / "docs" / "WEB.md").read_text()
        self.install = (ROOT / "INSTALL.md").read_text()

    def test_page_has_badge_and_settings_section(self):
        self.assertIn('id="updateHeaderBadge"', self.page)
        self.assertIn('id="updatesCard"', self.page)
        self.assertIn("Check for updates daily", self.page)
        self.assertIn("Check now", self.page)
        self.assertIn("Update now", self.page)
        self.assertIn("Update available", self.page)
        self.assertIn("Your model stays loaded", self.page)
        self.assertIn("Caravan will reload the model", self.page)
        self.assertIn("the page will be back in a few seconds", self.page.lower())
        self.assertIn("Try again", self.page)
        self.assertIn("renderUpdateMacs", self.page)
        # Check now sits in the Updates header row, next to the title.
        head = self.page.split('class="update-head"', 1)[1].split("</div>", 1)[0]
        self.assertIn(">Updates</h2>", head)
        self.assertIn('id="btnUpdateCheck"', head)
        self.assertEqual(self.page.count('id="btnUpdateCheck"'), 1)
        self.assertNotIn('"This Mac is on the " + j.current_label', self.page)
        self.assertIn("other Macs", self.page)
        # Campfire busy style reused for the Update button.
        self.assertIn('btnUpdateNow', self.page)
        self.assertIn("is-tuning", self.page)
        self.assertIn("caravan.update.pending", self.page)

    def test_badge_uses_tune_badge_style(self):
        self.assertIn('class="tune-badge update-badge"', self.page)
        self.assertIn("openUpdates", self.page)

    def test_docs_describe_the_daily_check_and_the_local_guard(self):
        for text in (self.day26, self.web, self.install):
            self.assertIn("Check for updates daily", text)
            self.assertIn("Update available", text)
            self.assertIn("Update now", text)
            self.assertIn("caravan update --check", text)
        self.assertIn("Your model stays loaded", self.day26)
        self.assertIn("Caravan will reload the model", self.day26)
        self.assertIn("2nd Mac", self.day26)
        self.assertIn("Try again", self.day26)
        self.assertIn("this Mac", self.day26)
        self.assertIn("Tailscale", self.day26)
        self.assertIn("local network", self.day26)
        for term in ("prf-hays", "16 GB", "16GB", "/home/brenden"):
            self.assertNotIn(term, self.day26)
            self.assertNotIn(term, self.web)


if __name__ == "__main__":
    unittest.main()
