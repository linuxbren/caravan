"""Opt-in Tailscale remote access: CLI, installer prompt, API, uninstall, doctor."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for folder in ("agent", "proxy", "tools"):
    sys.path.insert(0, str(ROOT / folder))

import caravan as cli
import caravan_doctor as doctor
import caravan_remote as R
import caravan_uninstall as U
import service_config as SC
import web_server


class FakeTailscale:
    def __init__(self, *, logged_in=True, state="Running", ip="100.64.0.10",
                 dns="mymac.example.ts.net", serves=None, funnels=None,
                 missing=False, serve_error=None, status_error=False):
        self.logged_in = logged_in
        self.state = state
        self.ip = ip
        self.dns = dns
        self.serves = dict(serves or {})
        self.funnels = set(funnels or [])
        self.missing = missing
        self.serve_error = serve_error
        self.status_error = status_error
        self.calls = []

    def __call__(self, argv, capture_output=True, text=True, timeout=15, env=None):
        self.calls.append(list(argv))
        if self.missing:
            raise FileNotFoundError("tailscale")
        cmd = list(argv[1:])
        if cmd[:2] == ["status", "--json"]:
            if self.status_error:
                return SimpleNamespace(returncode=1, stdout="", stderr="failed")
            if not self.logged_in:
                return SimpleNamespace(returncode=1, stdout="", stderr="Logged out.")
            body = {"BackendState": self.state,
                    "Self": {"DNSName": self.dns + ".", "TailscaleIPs": [self.ip, "fd7a:115c::10"]}}
            if self.state == "Stopped":
                body["Self"]["TailscaleIPs"] = []
            return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")
        if cmd[:2] == ["serve", "status"]:
            tcp = {}
            for port, forward in self.serves.items():
                if forward is True:
                    tcp[str(port)] = {"HTTPS": True}
                else:
                    tcp[str(port)] = {"TCPForward": forward}
            funnel = {f"mymac.example.ts.net:{p}": True for p in self.funnels}
            return SimpleNamespace(returncode=0,
                                   stdout=json.dumps({"TCP": tcp, "AllowFunnel": funnel}),
                                   stderr="")
        if cmd and cmd[0] == "serve" and "off" in cmd:
            port = None
            for item in cmd:
                if item.startswith("--tcp="):
                    port = int(item.split("=", 1)[1])
                elif item == "--tcp":
                    port = int(cmd[cmd.index(item) + 1])
            if port is not None:
                self.serves.pop(port, None)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd and cmd[0] == "serve" and "--bg" in cmd:
            if self.serve_error:
                return SimpleNamespace(returncode=1, stdout="", stderr=self.serve_error)
            port, target = None, None
            i = 1
            while i < len(cmd):
                if cmd[i] == "--tcp" and i + 1 < len(cmd):
                    port = int(cmd[i + 1]); i += 2; continue
                if cmd[i].startswith("--tcp="):
                    port = int(cmd[i].split("=", 1)[1]); i += 1; continue
                if cmd[i].startswith("tcp://") or (":" in cmd[i] and not cmd[i].startswith("--")):
                    target = cmd[i]
                i += 1
            self.serves[port] = target.replace("tcp://", "") if target else f"127.0.0.1:{port}"
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected " + " ".join(cmd))


def tmp_home():
    return tempfile.TemporaryDirectory()


def cfg(home):
    path = Path(home) / ".caravan" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class BinaryFinderTests(unittest.TestCase):
    def test_prefers_app_bundle_then_homebrew_then_path(self):
        order = []
        def exists(path):
            order.append(path)
            return path == "/opt/homebrew/bin/tailscale"
        def usable(path, mode):
            return path == "/opt/homebrew/bin/tailscale"
        self.assertEqual(R.find_binary(which=lambda n: "/usr/bin/tailscale", exists=exists, usable=usable),
                         "/opt/homebrew/bin/tailscale")
        self.assertIn("/Applications/Tailscale.app/Contents/MacOS/Tailscale", order)
        self.assertIn("/opt/homebrew/bin/tailscale", order)
        self.assertIn("/usr/local/bin/tailscale", R.BINARIES)
        self.assertTrue(order.index("/Applications/Tailscale.app/Contents/MacOS/Tailscale") < order.index("/opt/homebrew/bin/tailscale"))

    def test_path_fallback_and_missing(self):
        self.assertEqual(R.find_binary(which=lambda n: "/bin/tailscale" if n == "tailscale" else None,
                                       exists=lambda p: False, usable=lambda p, m: False),
                         "/bin/tailscale")
        self.assertIsNone(R.find_binary(which=lambda n: None, exists=lambda p: False, usable=lambda p, m: False))


class ConfigWriteTests(unittest.TestCase):
    def test_preserves_existing_tables_and_comments(self):
        with tmp_home() as home:
            path = cfg(home)
            path.write_text('[defaults]\nself_tune = "auto"\n\n# keep me\n[web.nodes.local]\nlabel = "My Mac"\n')
            R.set_enabled(True, path)
            text = path.read_text()
            self.assertIn('self_tune = "auto"', text)
            self.assertIn('# keep me', text)
            self.assertIn('label = "My Mac"', text)
            self.assertIn('[remote]\nenabled = true', text)
            R.set_enabled(False, path)
            self.assertIn('enabled = false', path.read_text())
            self.assertIn('self_tune = "auto"', path.read_text())
            self.assertTrue(R.enabled_in_config(path) is False)

    def test_enabled_reader_accepts_true_only(self):
        with tmp_home() as home:
            path = cfg(home)
            path.write_text('[remote]\nenabled = true\n')
            self.assertTrue(R.enabled_in_config(path))
            path.write_text('[remote]\nenabled = false\n')
            self.assertFalse(R.enabled_in_config(path))
            path.write_text('[defaults]\nself_tune = "auto"\n')
            self.assertFalse(R.enabled_in_config(path))


class CliRemoteTests(unittest.TestCase):
    def run_cli(self, args, ts, home, port=8190):
        path = cfg(home)
        if not path.exists():
            path.write_text('[defaults]\nself_tune = "auto"\n')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = R.main(["--port", str(port), "--home", home, *args] if False else None)
        return code, buf.getvalue()

    def invoke(self, action, ts, home, port=8190):
        path = cfg(home)
        buf = io.StringIO()
        kw = dict(port=port, home=home, path=path, binary="/usr/bin/tailscale", runner=ts)
        if action == "on":
            info = R.turn_on(**kw)
        elif action == "off":
            info = R.turn_off(**kw)
        else:
            info = R.inspect(**kw)
        print(R.status_line(info), file=buf)
        return 0, buf.getvalue(), info

    def test_on_records_config_and_prints_addresses(self):
        with tmp_home() as home:
            ts = FakeTailscale()
            code, out, info = self.invoke("on", ts, home)
            self.assertEqual(code, 0)
            self.assertTrue(info["enabled"])
            self.assertIn("http://100.64.0.10:8190", out)
            self.assertIn("http://mymac.example.ts.net:8190", out)
            self.assertTrue(R.enabled_in_config(cfg(home)))
            serve_cmds = [c for c in ts.calls if len(c) > 1 and c[1] == "serve" and "--bg" in c]
            self.assertEqual(len(serve_cmds), 1)
            self.assertEqual(serve_cmds[0][1:], ["serve", "--bg", "--tcp", "8190", "tcp://127.0.0.1:8190"])
            self.assertNotIn("--funnel", serve_cmds[0])
            self.assertNotIn("0.0.0.0", " ".join(serve_cmds[0]))

    def test_on_is_idempotent_when_already_serving(self):
        with tmp_home() as home:
            ts = FakeTailscale(serves={8190: "127.0.0.1:8190"})
            code, out, info = self.invoke("on", ts, home)
            self.assertEqual(code, 0)
            self.assertTrue(info["enabled"])
            self.assertFalse(any("--bg" in c for c in ts.calls))
            self.assertTrue(R.enabled_in_config(cfg(home)))

    def test_handmade_serve_is_adopted_by_status(self):
        with tmp_home() as home:
            ts = FakeTailscale(serves={8190: "tcp://127.0.0.1:8190"})
            path = cfg(home)
            path.write_text('[defaults]\nself_tune = "auto"\n')
            self.assertFalse(R.enabled_in_config(path))
            code, out, info = self.invoke("status", ts, home)
            self.assertEqual(code, 0)
            self.assertTrue(info["enabled"])
            self.assertIn("Open from other devices is on:", out)
            self.assertIn("http://100.64.0.10:8190", out)
            self.assertIn("http://mymac.example.ts.net:8190", out)
            self.assertTrue(R.enabled_in_config(path))
            self.assertEqual(out.count("\n"), 1)

    def test_localhost_forward_is_recognized(self):
        with tmp_home() as home:
            ts = FakeTailscale(serves={8190: "localhost:8190"})
            _, _, info = self.invoke("status", ts, home)
            self.assertTrue(info["enabled"])

    def test_off_removes_only_caravan_port(self):
        with tmp_home() as home:
            ts = FakeTailscale(serves={8190: "127.0.0.1:8190", 443: True, 9999: "127.0.0.1:9999"})
            _, out, info = self.invoke("off", ts, home)
            self.assertFalse(info["enabled"])
            self.assertIn("is off", out)
            self.assertNotIn(8190, ts.serves)
            self.assertIn(443, ts.serves)
            self.assertIn(9999, ts.serves)
            off_cmds = [c for c in ts.calls if "off" in c]
            self.assertEqual(len(off_cmds), 1)
            self.assertIn("--tcp=8190", off_cmds[0])
            self.assertNotIn("reset", " ".join(off_cmds[0]))
            self.assertFalse(any("--tcp=443" in c or "--tcp=9999" in c for c in ts.calls))
            self.assertFalse(R.enabled_in_config(cfg(home)))

    def test_off_does_not_touch_unrelated_forward_on_same_port(self):
        with tmp_home() as home:
            ts = FakeTailscale(serves={8190: "127.0.0.1:3000"})
            _, _, info = self.invoke("off", ts, home)
            self.assertFalse(info["enabled"])
            self.assertEqual(ts.serves[8190], "127.0.0.1:3000")
            self.assertFalse(any("off" in c for c in ts.calls))

    def test_status_when_off_is_one_line(self):
        with tmp_home() as home:
            ts = FakeTailscale()
            _, out, info = self.invoke("status", ts, home)
            self.assertFalse(info["enabled"])
            self.assertEqual(out.strip(), "Open from other devices is off.")
            self.assertEqual(out.count("\n"), 1)

    def test_missing_tailscale_plain_words(self):
        with tmp_home() as home:
            info = R.inspect(port=8190, home=home, path=cfg(home), binary=None, adopt=False)
            # force missing binary
            with mock.patch.object(R, "find_binary", return_value=None):
                info = R.inspect(port=8190, home=home, path=cfg(home), binary=None, adopt=False)
            self.assertFalse(info["available"])
            self.assertIn("not installed", info["message"])
            self.assertIn("Install the Tailscale app", info["message"])
            self.assertEqual(R.status_line(info), info["message"])

    def test_logged_out_plain_words(self):
        with tmp_home() as home:
            ts = FakeTailscale(logged_in=False)
            _, out, info = self.invoke("status", ts, home)
            self.assertFalse(info["available"])
            self.assertIn("not signed in", out)
            self.assertIn("Open Tailscale", out)

    def test_stopped_plain_words(self):
        with tmp_home() as home:
            ts = FakeTailscale(state="Stopped", logged_in=True)
            _, out, info = self.invoke("status", ts, home)
            self.assertFalse(info["available"])
            self.assertIn("not running", out)

    def test_on_without_tailscale_raises_plain_error(self):
        with tmp_home() as home:
            with mock.patch.object(R, "find_binary", return_value=None):
                with self.assertRaises(R.RemoteError) as ctx:
                    R.turn_on(port=8190, home=home, path=cfg(home), binary=None)
            self.assertIn("not installed", str(ctx.exception))

    def test_funnel_is_not_adopted(self):
        with tmp_home() as home:
            ts = FakeTailscale(serves={8190: "127.0.0.1:8190"}, funnels={8190})
            _, out, info = self.invoke("status", ts, home)
            self.assertFalse(info["enabled"])
            self.assertIn("more widely", info["message"])

    def test_caravan_cli_dispatches_remote(self):
        seen = []
        def fake(argv):
            seen.append(list(argv))
            print("Open from other devices is off.")
            return 0
        buf = io.StringIO()
        with mock.patch.object(R, "main", side_effect=fake), contextlib.redirect_stdout(buf):
            code = cli.main(["remote", "status"])
        self.assertEqual(code, 0)
        self.assertEqual(seen, [["status"]])
        self.assertIn("Open from other devices is off.", buf.getvalue())
        seen.clear()
        with mock.patch.object(R, "main", side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["remote"]), 0)
        self.assertEqual(seen, [[]])

    def test_help_lists_remote(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stdout(buf):
            cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("remote", buf.getvalue())


class InstallerPromptTests(unittest.TestCase):
    def test_no_tty_skips_silently(self):
        ts = FakeTailscale()
        with tmp_home() as home, io.StringIO() as out:
            result = R.maybe_prompt(port=8190, home=home, path=cfg(home), ask=False,
                                    outfile=out, binary="/usr/bin/tailscale", runner=ts)
            self.assertEqual(result, "skipped")
            self.assertEqual(out.getvalue(), "")
            self.assertFalse(any("--bg" in c for c in ts.calls))

    def test_missing_tailscale_skips_silently(self):
        with tmp_home() as home, io.StringIO() as out:
            with mock.patch.object(R, "find_binary", return_value=None):
                result = R.maybe_prompt(port=8190, home=home, path=cfg(home), ask=True,
                                        outfile=out, infile=io.StringIO("y\n"), binary=None)
            self.assertEqual(result, "skipped")
            self.assertEqual(out.getvalue(), "")

    def test_logged_out_skips_silently(self):
        ts = FakeTailscale(logged_in=False)
        with tmp_home() as home, io.StringIO() as out:
            result = R.maybe_prompt(port=8190, home=home, path=cfg(home), ask=True,
                                    outfile=out, infile=io.StringIO("y\n"),
                                    binary="/usr/bin/tailscale", runner=ts)
            self.assertEqual(result, "skipped")
            self.assertEqual(out.getvalue(), "")
            self.assertFalse(any("--bg" in c for c in ts.calls))

    def test_default_no_does_not_enable(self):
        ts = FakeTailscale()
        with tmp_home() as home, io.StringIO() as out:
            result = R.maybe_prompt(port=8190, home=home, path=cfg(home), ask=True,
                                    outfile=out, infile=io.StringIO("\n"),
                                    binary="/usr/bin/tailscale", runner=ts)
            self.assertEqual(result, "no")
            self.assertIn(R.QUESTION, out.getvalue())
            self.assertFalse(any("--bg" in c for c in ts.calls))
            self.assertFalse(R.enabled_in_config(cfg(home)))

    def test_n_does_not_enable(self):
        ts = FakeTailscale()
        with tmp_home() as home, io.StringIO() as out:
            result = R.maybe_prompt(port=8190, home=home, path=cfg(home), ask=True,
                                    outfile=out, infile=io.StringIO("n\n"),
                                    binary="/usr/bin/tailscale", runner=ts)
            self.assertEqual(result, "no")
            self.assertFalse(any("--bg" in c for c in ts.calls))

    def test_yes_turns_on_and_prints_addresses(self):
        ts = FakeTailscale()
        with tmp_home() as home, io.StringIO() as out:
            result = R.maybe_prompt(port=8190, home=home, path=cfg(home), ask=True,
                                    outfile=out, infile=io.StringIO("y\n"),
                                    binary="/usr/bin/tailscale", runner=ts)
            self.assertEqual(result, "on")
            self.assertIn(R.QUESTION, out.getvalue())
            self.assertIn("http://100.64.0.10:8190", out.getvalue())
            self.assertTrue(any("--bg" in c for c in ts.calls))
            self.assertTrue(R.enabled_in_config(cfg(home)))

    def test_already_on_does_not_reask(self):
        ts = FakeTailscale(serves={8190: "127.0.0.1:8190"})
        with tmp_home() as home, io.StringIO() as out:
            result = R.maybe_prompt(port=8190, home=home, path=cfg(home), ask=True,
                                    outfile=out, infile=io.StringIO("n\n"),
                                    binary="/usr/bin/tailscale", runner=ts)
            self.assertEqual(result, "already-on")
            self.assertNotIn(R.QUESTION, out.getvalue())

    def test_can_ask_false_when_tty_missing(self):
        self.assertFalse(R.can_ask("/no/such/tty/device"))

    def test_can_ask_true_for_rw_file(self):
        with tempfile.NamedTemporaryFile() as f:
            self.assertTrue(R.can_ask(f.name))

    def test_question_text_is_exact(self):
        self.assertEqual(R.QUESTION, "Open Caravan from your other devices over Tailscale? (y/N) ")

    def test_install_sh_asks_only_on_fresh_non_update(self):
        text = (ROOT / "scripts/install.sh").read_text()
        self.assertIn('caravan_remote.py" maybe-prompt --port', text)
        self.assertIn('caravan_lan.py" maybe-prompt --port', text)
        self.assertIn('FRESH_CONFIG" = 1 ] && [ "$UPDATE" = 0 ]', text)
        self.assertIn("Would ask whether to open Caravan from your other devices over Tailscale.", text)
        self.assertIn("Would ask whether to open Caravan on your local network.", text)
        # Tailscale and local-network questions only, both fresh-install only.
        self.assertEqual(text.count("Would ask whether"), 2)

    def test_install_scripts_have_no_other_read_prompts(self):
        # The only user question is maybe-prompt; install shells themselves don't read answers.
        for name in ("install", "scripts/install.sh"):
            text = (ROOT / name).read_text()
            self.assertNotIn("read -r", text.replace("read -r REF SHA", ""))
            self.assertNotIn("read -p", text)


class UninstallRemoteTests(unittest.TestCase):
    def test_uninstall_turns_remote_off_after_confirm(self):
        called = []
        import caravan_service as service
        with tmp_home() as d, mock.patch.object(service, "check_platform"), mock.patch.object(U, "workers", return_value={}):
            home = Path(d)
            (home / ".caravan").mkdir()
            run = mock.Mock(return_value=SimpleNamespace(returncode=0))
            result = U.uninstall(home, yes=True, run=run, remote_off=lambda: called.append("off"))
            self.assertEqual(called, ["off"])
            self.assertIn("removed", result)

    def test_cancelled_uninstall_does_not_turn_off(self):
        called = []
        import caravan_service as service
        with tmp_home() as d, mock.patch.object(service, "check_platform"):
            home = Path(d)
            (home / ".caravan").mkdir()
            run = mock.Mock()
            result = U.uninstall(home, confirm=lambda p: "n", run=run, remote_off=lambda: called.append("off"))
            self.assertEqual(called, [])
            self.assertIn("Cancelled", result)
            self.assertTrue((home / ".caravan").exists())

    def test_missing_tailscale_does_not_block_uninstall(self):
        import caravan_service as service
        with tmp_home() as d, mock.patch.object(service, "check_platform"), mock.patch.object(U, "workers", return_value={}):
            home = Path(d)
            (home / ".caravan").mkdir()
            (home / ".caravan" / "keep").write_text("x")
            with mock.patch.object(R, "find_binary", return_value=None):
                result = U.uninstall(home, yes=True, run=mock.Mock(return_value=SimpleNamespace(returncode=0)))
            self.assertIn("removed", result)
            self.assertFalse((home / ".caravan").exists())


class DoctorRemoteTests(unittest.TestCase):
    def test_doctor_reports_off_and_on(self):
        with tmp_home() as home:
            ts = FakeTailscale()
            line = R.doctor_line(port=8190, home=home, path=cfg(home), binary="/usr/bin/tailscale", runner=ts)
            self.assertEqual(line, "Open from other devices is off.")
            ts.serves[8190] = "127.0.0.1:8190"
            line = R.doctor_line(port=8190, home=home, path=cfg(home), binary="/usr/bin/tailscale", runner=ts)
            self.assertIn("is on at http://100.64.0.10:8190", line)
            self.assertIn("http://mymac.example.ts.net:8190", line)

    def test_doctor_checks_include_remote_line(self):
        with tmp_home() as home, mock.patch.object(R, "doctor_line", return_value="Open from other devices is off."):
            # Patch where doctor looks it up — it imports inside the function.
            with mock.patch.dict(sys.modules, {}):
                pass
            rows = doctor.checks(home=home)
            # Real doctor_line will run (Linux, no tailscale) and add an INFO.
            self.assertTrue(any("Open from other devices" in msg for _, msg in rows))
            self.assertTrue(all(level != "ERROR" or "Open from other devices" not in msg for level, msg in rows))


class ApiRemoteTests(unittest.TestCase):
    def handler(self):
        app = SimpleNamespace()
        cls = web_server.make_handler(app)
        h = cls.__new__(cls)
        h.server = SimpleNamespace(server_port=8190)
        captured = []
        def _json(code, obj):
            captured.append((code, obj))
            return (code, obj)
        h._json = _json
        return h, captured

    def test_get_and_post(self):
        with tmp_home() as home:
            ts = FakeTailscale()
            path = cfg(home)
            h, captured = self.handler()
            with mock.patch.object(R, "find_binary", return_value="/usr/bin/tailscale"), \
                 mock.patch.object(R, "config_path", return_value=path), \
                 mock.patch.object(R, "web_port", return_value=8190), \
                 mock.patch.object(R.subprocess, "run", ts):
                # GET off
                h._api_remote()
                code, body = captured[-1]
                self.assertEqual(code, 200)
                self.assertFalse(body["enabled"])
                self.assertTrue(body["available"])
                # POST on
                h._api_remote(post=True, body={"enabled": True})
                code, body = captured[-1]
                self.assertEqual(code, 200)
                self.assertTrue(body["enabled"])
                self.assertIn("http://100.64.0.10:8190", body["addresses"])
                self.assertTrue(any("--bg" in c for c in ts.calls))
                # POST off
                h._api_remote(post=True, body={"enabled": False})
                code, body = captured[-1]
                self.assertEqual(code, 200)
                self.assertFalse(body["enabled"])
                self.assertNotIn(8190, ts.serves)

    def test_post_without_tailscale_is_400(self):
        h, captured = self.handler()
        with mock.patch.object(R, "find_binary", return_value=None), \
             mock.patch.object(R, "web_port", return_value=8190), \
             tempfile.TemporaryDirectory() as d, \
             mock.patch.object(R, "config_path", return_value=Path(d) / "c.toml"):
            h._api_remote(post=True, body={"enabled": True})
        code, body = captured[-1]
        self.assertEqual(code, 400)
        self.assertIn("not installed", body["error"])


class UiAndBindTests(unittest.TestCase):
    def test_settings_switch_and_copy(self):
        html = (ROOT / "proxy/web/index.html").read_text()
        self.assertIn("Open from my other devices", html)
        self.assertIn('id="remoteAccessCard"', html)
        self.assertIn('id="remoteAccessSwitch"', html)
        self.assertIn('data-remote="on"', html)
        self.assertIn('data-remote="off"', html)
        self.assertIn('/api/remote', html)
        self.assertIn("refreshRemoteAccess", html)
        self.assertIn("renderRemoteAccess", html)
        self.assertIn("Only devices on your Tailscale network", html)
        # Addresses are assigned as text, not concatenated into innerHTML.
        self.assertIn("a.textContent = addr", html)
        self.assertNotIn("remoteAccessStatus\").innerHTML", html)

    def test_web_service_stays_on_loopback(self):
        plan = SC.make_plan(kind="web", repo=str(ROOT), python=sys.executable)
        self.assertEqual(plan["host"], "127.0.0.1")
        cmd = SC.render(plan)["ProgramArguments"]
        self.assertIn("--host", cmd)
        self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")
        source = (ROOT / "tools/caravan_remote.py").read_text()
        self.assertNotIn('"0.0.0.0"', source)
        self.assertNotIn("'0.0.0.0'", source)
        self.assertNotIn("--funnel", source)
        self.assertIn("tcp://127.0.0.1:", source)
        self.assertIn('serve", f"--tcp={port}", "off"', source)

    def test_inline_javascript_parses(self):
        import re, shutil, subprocess
        if not shutil.which("node"):
            self.skipTest("node not installed")
        text = (ROOT / "proxy/web/index.html").read_text()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "inline.js"
            p.write_text("\n".join(re.findall(r"<script>(.*?)</script>", text, re.S)))
            result = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


class RealRunnerCliModeTest(unittest.TestCase):
    def test_real_runner_forces_cli_mode(self):
        import subprocess as sp
        seen = {}

        def fake(argv, **kw):
            seen.update(kw)
            return sp.CompletedProcess(argv, 0, "{}", "")

        with mock.patch.object(R.subprocess, "run", fake):
            R.run_tailscale(["version"], binary="/usr/bin/tailscale")
        self.assertEqual(seen["env"]["TAILSCALE_BE_CLI"], "1")


if __name__ == "__main__":
    unittest.main()
