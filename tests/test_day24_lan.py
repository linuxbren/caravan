"""Day 24 opt-in local-network access: CLI, Settings, bind, install, uninstall."""
from __future__ import annotations

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
import caravan_lan as L
import caravan_uninstall as U
import service_config as SC
import web_server


def tmp_home():
    return tempfile.TemporaryDirectory()


def cfg(home):
    path = Path(home) / ".caravan" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class ConfigAndDefaultTests(unittest.TestCase):
    def test_missing_config_is_off(self):
        with tmp_home() as home:
            path = cfg(home)
            self.assertFalse(path.is_file())
            self.assertFalse(L.enabled_in_config(path))
            self.assertEqual(L.listen_host("127.0.0.1", path=path), "127.0.0.1")
            self.assertEqual(L.listen_host("0.0.0.0", path=path), "0.0.0.0")
            self.assertEqual(L.listen_host(None, path=path), "127.0.0.1")
            info = L.inspect(port=8190, home=home, path=path)
            self.assertFalse(info["enabled"])
            self.assertEqual(info["addresses"], [])
            self.assertEqual(info["bind"], "127.0.0.1")
            self.assertEqual(info["warning"], L.WARNING)
            self.assertEqual(L.status_line(info), L.OFF_MESSAGE)

    def test_enabled_reader_accepts_true_only(self):
        with tmp_home() as home:
            path = cfg(home)
            path.write_text('[lan]\nenabled = true\n')
            self.assertTrue(L.enabled_in_config(path))
            path.write_text('[lan]\nenabled = false\n')
            self.assertFalse(L.enabled_in_config(path))
            path.write_text('[lan]\nenabled = "true"\n')
            self.assertFalse(L.enabled_in_config(path))
            path.write_text('[defaults]\nself_tune = "auto"\n')
            self.assertFalse(L.enabled_in_config(path))
            path.write_text('[remote]\nenabled = true\n')
            self.assertFalse(L.enabled_in_config(path))

    def test_set_enabled_preserves_other_tables(self):
        with tmp_home() as home:
            path = cfg(home)
            path.write_text('[defaults]\nself_tune = "auto"\n\n# keep me\n[web.nodes.local]\nlabel = "My Mac"\n\n[remote]\nenabled = true\n')
            L.set_enabled(True, path)
            text = path.read_text()
            self.assertIn('self_tune = "auto"', text)
            self.assertIn('# keep me', text)
            self.assertIn('label = "My Mac"', text)
            self.assertIn('[remote]\nenabled = true', text)
            self.assertIn('[lan]\nenabled = true', text)
            L.set_enabled(False, path)
            text = path.read_text()
            self.assertIn('[lan]\nenabled = false', text)
            self.assertIn('[remote]\nenabled = true', text)
            self.assertFalse(L.enabled_in_config(path))

    def test_listen_host_follows_lan_choice(self):
        with tmp_home() as home, mock.patch.object(L, "config_path", return_value=cfg(home)):
            path = cfg(home)
            L.set_enabled(False, path)
            self.assertEqual(L.listen_host("127.0.0.1"), "127.0.0.1")
            self.assertEqual(L.listen_hosts("127.0.0.1"), ["127.0.0.1"])
            L.set_enabled(True, path)
            # Primary stays 127.0.0.1 so Tailscale serve keeps working.
            self.assertEqual(L.listen_host("127.0.0.1"), "127.0.0.1")
            self.assertEqual(L.listen_host("192.168.1.20"), "127.0.0.1")
            with mock.patch.object(L, "lan_ips", return_value=["192.168.1.20"]):
                self.assertEqual(L.listen_hosts("127.0.0.1"), ["127.0.0.1", "192.168.1.20"])
                self.assertNotIn("0.0.0.0", L.listen_hosts("127.0.0.1"))
                self.assertNotIn("0.0.0.0", L.listen_hosts("0.0.0.0"))

    def test_web_service_plan_stays_loopback_when_lan_off(self):
        plan = SC.make_plan(kind="web", repo=str(ROOT), python=sys.executable)
        self.assertEqual(plan["host"], "127.0.0.1")
        cmd = SC.render(plan)["ProgramArguments"]
        self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")

    def test_agent_service_config_is_untouched(self):
        # The listen change lives in the web process so an update keeps a loaded model.
        source = (ROOT / "agent" / "service_config.py").read_text()
        self.assertNotIn("[lan]", source)
        self.assertNotIn("caravan_lan", source)


class AddressTests(unittest.TestCase):
    def test_status_uses_http_ip_and_port(self):
        with tmp_home() as home, mock.patch.object(L, "lan_ips", return_value=["192.168.1.20"]):
            path = cfg(home)
            info = L.turn_on(port=8190, home=home, path=path)
            self.assertEqual(info["addresses"], ["http://192.168.1.20:8190"])
            line = L.status_line(info)
            self.assertEqual(line, "Open on the local network at http://192.168.1.20:8190")
            self.assertRegex(line, r"http://\d+\.\d+\.\d+\.\d+:8190")
            self.assertNotIn(".local", line)
            self.assertIn(L.WARNING, info["warning"])
            self.assertIn(L.WARNING, info["message"])

    def test_multiple_addresses_joined(self):
        with tmp_home() as home, mock.patch.object(L, "lan_ips", return_value=["192.168.1.20", "10.0.0.4"]):
            info = L.turn_on(port=8190, home=home, path=cfg(home))
            self.assertEqual(info["addresses"], ["http://192.168.1.20:8190", "http://10.0.0.4:8190"])
            self.assertIn("http://192.168.1.20:8190 and http://10.0.0.4:8190", L.status_line(info))

    def test_ok_ipv4_filters_loopback_and_hostnames(self):
        self.assertFalse(L._ok_ipv4("127.0.0.1"))
        self.assertFalse(L._ok_ipv4("0.0.0.0"))
        self.assertFalse(L._ok_ipv4("mymac.local"))
        self.assertFalse(L._ok_ipv4("::1"))
        self.assertTrue(L._ok_ipv4("192.168.1.20"))
        self.assertTrue(L._ok_ipv4("10.0.0.4"))
        self.assertTrue(L._ok_ipv4("172.16.1.1"))
        self.assertFalse(L._ok_ipv4("100.68.62.20"))  # Tailscale / CGNAT
        self.assertFalse(L._ok_ipv4("169.254.110.94"))  # link-local / Thunderbolt
        self.assertFalse(L._ok_ipv4("8.8.8.8"))

    def test_lan_ips_skips_loopback(self):
        with mock.patch.object(L, "_ips_from_interfaces", return_value=[]), \
             mock.patch.object(L.socket, "socket") as sock_cls, \
             mock.patch.object(L.socket, "gethostname", return_value="MyMac"), \
             mock.patch.object(L.socket, "getaddrinfo", return_value=[
                 (None, None, None, None, ("127.0.0.1", 0)),
                 (None, None, None, None, ("192.168.1.20", 0)),
             ]):
            sock = mock.MagicMock()
            sock.getsockname.return_value = ("127.0.0.1", 0)
            sock_cls.return_value = sock
            ips = L.lan_ips()
        self.assertEqual(ips, ["192.168.1.20"])
        self.assertNotIn("127.0.0.1", ips)
        self.assertNotIn("MyMac", ips)


    def test_lan_ips_skips_tailscale_and_link_local(self):
        with mock.patch.object(L, "_ips_from_interfaces", return_value=["192.168.1.79", "100.68.62.20", "169.254.110.94"]), \
             mock.patch.object(L.socket, "socket") as sock_cls, \
             mock.patch.object(L.socket, "gethostname", return_value="MyMac"), \
             mock.patch.object(L.socket, "getaddrinfo", return_value=[
                 (None, None, None, None, ("100.68.62.20", 0)),
                 (None, None, None, None, ("169.254.110.94", 0)),
                 (None, None, None, None, ("192.168.1.79", 0)),
             ]):
            sock = mock.MagicMock()
            sock.getsockname.return_value = ("100.68.62.20", 0)  # default route is Tailscale
            sock_cls.return_value = sock
            ips = L.lan_ips()
        self.assertEqual(ips, ["192.168.1.79"])
        self.assertNotIn("100.68.62.20", ips)
        self.assertNotIn("169.254.110.94", ips)

    def test_inspect_on_without_address_has_no_placeholder(self):
        with tmp_home() as home, mock.patch.object(L, "lan_ips", return_value=[]):
            info = L.turn_on(port=8190, home=home, path=cfg(home))
            self.assertTrue(info["enabled"])
            self.assertEqual(info["addresses"], [])
            self.assertNotIn("<lan-ip>", info["message"])
            self.assertNotIn("<port>", info["message"])
            self.assertIn("could not be found", info["message"])

    def test_both_access_paths_share_loopback(self):
        """Tailscale serve forwards to 127.0.0.1; LAN adds private addresses."""
        with tmp_home() as home, mock.patch.object(L, "config_path", return_value=cfg(home)), \
             mock.patch.object(L, "lan_ips", return_value=["192.168.1.79"]):
            L.set_enabled(True, cfg(home))
            hosts = L.listen_hosts("127.0.0.1")
            self.assertIn("127.0.0.1", hosts)
            self.assertIn("192.168.1.79", hosts)
            self.assertNotIn("0.0.0.0", hosts)
            info = L.inspect(port=8190, home=home, path=cfg(home))
            self.assertEqual(info["addresses"], ["http://192.168.1.79:8190"])
            self.assertEqual(info["bind"], "127.0.0.1")
            self.assertEqual(info["binds"], ["127.0.0.1", "192.168.1.79"])


class CliLanTests(unittest.TestCase):
    def test_on_off_status_and_dispatch(self):
        with tmp_home() as home, \
             mock.patch.object(L, "lan_ips", return_value=["192.168.1.20"]), \
             mock.patch.object(L, "notify_running_web", return_value=None) as notify, \
             mock.patch.object(L, "web_port", return_value=8190), \
             mock.patch.object(L, "config_path", side_effect=lambda h=None: cfg(home if h is None else h)):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(L.main(["--home", home, "status"]), 0)
            self.assertEqual(buf.getvalue().strip(), "Open on the local network is off.")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(L.main(["--home", home, "on"]), 0)
            self.assertIn("http://192.168.1.20:8190", buf.getvalue())
            self.assertTrue(L.enabled_in_config(cfg(home)))
            notify.assert_called()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(L.main(["--home", home, "status"]), 0)
            self.assertEqual(buf.getvalue().strip(), "Open on the local network at http://192.168.1.20:8190")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(L.main(["--home", home, "off"]), 0)
            self.assertIn("is off", buf.getvalue())
            self.assertFalse(L.enabled_in_config(cfg(home)))

    def test_on_prints_restart_message_when_page_rebinding(self):
        with tmp_home() as home, \
             mock.patch.object(L, "lan_ips", return_value=["10.0.0.4"]), \
             mock.patch.object(L, "notify_running_web", return_value={
                 "restarting": True, "keeps_model": True, "message": L.RESTART_MESSAGE,
             }), \
             mock.patch.object(L, "web_port", return_value=8190), \
             mock.patch.object(L, "config_path", side_effect=lambda h=None: cfg(home if h is None else h)):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(L.main(["--home", home, "on"]), 0)
            out = buf.getvalue()
            self.assertIn("http://10.0.0.4:8190", out)
            self.assertIn("The page will be back in a few seconds. The model stays loaded.", out)

    def test_caravan_cli_dispatches_lan(self):
        seen = []
        def fake(argv):
            seen.append(list(argv))
            print("Open on the local network is off.")
            return 0
        buf = io.StringIO()
        with mock.patch.object(L, "main", side_effect=fake), contextlib.redirect_stdout(buf):
            code = cli.main(["lan", "status"])
        self.assertEqual(code, 0)
        self.assertEqual(seen, [["status"]])
        self.assertIn("Open on the local network is off.", buf.getvalue())
        seen.clear()
        with mock.patch.object(L, "main", side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["lan"]), 0)
        self.assertEqual(seen, [[]])

    def test_help_lists_lan(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stdout(buf):
            cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("lan", buf.getvalue())
        self.assertIn("remote", buf.getvalue())


class InstallerPromptTests(unittest.TestCase):
    def test_question_text_is_exact(self):
        self.assertEqual(L.QUESTION, "Open Caravan on your local network? (y/N) ")
        self.assertEqual(L.WARNING, "Anyone on the same network can use Caravan, and there is no login.")

    def test_default_is_no(self):
        with tmp_home() as home:
            path = cfg(home)
            out = io.StringIO()
            for answer, expect in (("\n", "no"), ("n\n", "no"), ("N\n", "no"), ("maybe\n", "no")):
                result = L.maybe_prompt(port=8190, home=home, path=path, ask=True,
                                        infile=io.StringIO(answer), outfile=out)
                self.assertEqual(result, expect, answer)
                self.assertFalse(L.enabled_in_config(path))
            self.assertIn(L.WARNING, out.getvalue())
            self.assertIn(L.QUESTION, out.getvalue())

    def test_yes_turns_on(self):
        with tmp_home() as home, mock.patch.object(L, "lan_ips", return_value=["192.168.1.20"]):
            path = cfg(home)
            out = io.StringIO()
            result = L.maybe_prompt(port=8190, home=home, path=path, ask=True,
                                    infile=io.StringIO("y\n"), outfile=out)
            self.assertEqual(result, "on")
            self.assertTrue(L.enabled_in_config(path))
            self.assertIn("http://192.168.1.20:8190", out.getvalue())
            self.assertIn(L.WARNING, out.getvalue())

    def test_no_tty_skips_silently(self):
        with tmp_home() as home:
            path = cfg(home)
            out = io.StringIO()
            result = L.maybe_prompt(port=8190, home=home, path=path, ask=False, outfile=out)
            self.assertEqual(result, "skipped")
            self.assertFalse(L.enabled_in_config(path))
            self.assertEqual(out.getvalue(), "")

    def test_install_sh_asks_only_on_fresh_non_update(self):
        text = (ROOT / "scripts/install.sh").read_text()
        self.assertIn('caravan_lan.py" maybe-prompt --port', text)
        self.assertIn('FRESH_CONFIG" = 1 ] && [ "$UPDATE" = 0 ]', text)
        self.assertIn("Would ask whether to open Caravan on your local network.", text)
        # After the Tailscale question, still inside the same fresh-install gate.
        tail = text.index('caravan_remote.py" maybe-prompt --port')
        lan = text.index('caravan_lan.py" maybe-prompt --port')
        self.assertLess(tail, lan)
        # Shell itself does not read the answer.
        self.assertNotIn("read -p", text)


class UninstallLanTests(unittest.TestCase):
    def test_uninstall_turns_lan_off_after_confirm(self):
        called = []
        import caravan_service as service
        with tmp_home() as d, mock.patch.object(service, "check_platform"), mock.patch.object(U, "workers", return_value={}):
            home = Path(d)
            (home / ".caravan").mkdir()
            run = mock.Mock(return_value=SimpleNamespace(returncode=0))
            result = U.uninstall(home, yes=True, run=run,
                                 remote_off=lambda: called.append("remote"),
                                 lan_off=lambda: called.append("lan"))
            self.assertEqual(called, ["remote", "lan"])
            self.assertIn("removed", result)

    def test_cancelled_uninstall_does_not_turn_off(self):
        called = []
        import caravan_service as service
        with tmp_home() as d, mock.patch.object(service, "check_platform"):
            home = Path(d)
            (home / ".caravan").mkdir()
            result = U.uninstall(home, confirm=lambda p: "n", run=mock.Mock(),
                                 remote_off=lambda: called.append("remote"),
                                 lan_off=lambda: called.append("lan"))
            self.assertEqual(called, [])
            self.assertIn("Cancelled", result)
            self.assertTrue((home / ".caravan").exists())

    def test_real_turn_off_clears_config(self):
        import caravan_service as service
        with tmp_home() as d, mock.patch.object(service, "check_platform"), mock.patch.object(U, "workers", return_value={}):
            home = Path(d)
            path = cfg(home)
            L.set_enabled(True, path)
            self.assertTrue(L.enabled_in_config(path))
            U.uninstall(home, yes=True, run=mock.Mock(return_value=SimpleNamespace(returncode=0)),
                        remote_off=lambda: None)
            # ~/.caravan is removed; leftover enabled must already be false if the file lingered.
            self.assertFalse((home / ".caravan").exists())


class DoctorLanTests(unittest.TestCase):
    def test_doctor_reports_off_and_on(self):
        with tmp_home() as home, mock.patch.object(L, "lan_ips", return_value=["192.168.1.20"]):
            path = cfg(home)
            line = L.doctor_line(port=8190, home=home, path=path)
            self.assertEqual(line, "Open on the local network is off.")
            L.set_enabled(True, path)
            line = L.doctor_line(port=8190, home=home, path=path)
            self.assertIn("is on at http://192.168.1.20:8190", line)
            self.assertIn(L.WARNING, line)

    def test_doctor_checks_include_lan_line(self):
        with tmp_home() as home:
            rows = doctor.checks(home=home)
            self.assertTrue(any("Open on the local network" in msg for _, msg in rows))


class ApiLanTests(unittest.TestCase):
    def handler(self, rebind=None, bind_host="127.0.0.1", cli_host="127.0.0.1"):
        app = SimpleNamespace(rebind_listen=rebind, bind_host=bind_host, cli_host=cli_host)
        # make_handler closes over module-level? It uses `app` from main. We
        # need the handler's methods that refer to `app` — make_handler(app)
        # captures the passed app.
        cls = web_server.make_handler(app)
        h = cls.__new__(cls)
        h.server = SimpleNamespace(server_port=8190)
        captured = []
        def _json(code, obj):
            captured.append((code, obj))
            return (code, obj)
        h._json = _json
        return h, captured, app

    def test_get_and_post_schedule_rebind_without_stopping_workers(self):
        with tmp_home() as home, mock.patch.object(L, "lan_ips", return_value=["192.168.1.20"]), \
             mock.patch.object(L, "config_path", return_value=cfg(home)), \
             mock.patch.object(L, "web_port", return_value=8190):
            rebinds = []
            h, captured, app = self.handler(rebind=lambda wanted: rebinds.append(wanted))
            h._api_lan()
            code, body = captured[-1]
            self.assertEqual(code, 200)
            self.assertFalse(body["enabled"])
            self.assertEqual(body["warning"], L.WARNING)
            h._api_lan(post=True, body={"enabled": True})
            code, body = captured[-1]
            self.assertEqual(code, 200)
            self.assertTrue(body["enabled"])
            self.assertEqual(body["addresses"], ["http://192.168.1.20:8190"])
            # In-process: 127.0.0.1 stays up, addresses are returned now,
            # the page does not reload, Tailscale is uninterrupted.
            self.assertFalse(body.get("restarting"))
            self.assertTrue(body.get("keeps_model"))
            self.assertIn("http://192.168.1.20:8190", body["message"])
            self.assertEqual(rebinds, [["127.0.0.1", "192.168.1.20"]])
            # Turning off drops the LAN socket and keeps 127.0.0.1.
            app.bind_host = "127.0.0.1"
            app.bind_hosts = ["127.0.0.1", "192.168.1.20"]
            rebinds.clear()
            h._api_lan(post=True, body={"enabled": False})
            code, body = captured[-1]
            self.assertFalse(body["enabled"])
            self.assertFalse(body.get("restarting"))
            self.assertEqual(rebinds, [["127.0.0.1"]])
            self.assertEqual(body["addresses"], [])

    def test_post_rejects_bad_body(self):
        with tmp_home() as home, mock.patch.object(L, "config_path", return_value=cfg(home)):
            h, captured, _ = self.handler()
            h._api_lan(post=True, body={"foo": 1})
            code, body = captured[-1]
            self.assertEqual(code, 400)
            self.assertIn("enabled", body["error"])

    def test_api_source_does_not_stop_workers(self):
        source = (ROOT / "proxy" / "web_server.py").read_text()
        # The LAN handler must not stop a loaded model.
        start = source.index("def _api_lan")
        end = source.index("def _api_picker_placement")
        block = source[start:end]
        self.assertNotIn("mgr.stop", block)
        self.assertIn("CARAVAN_WEB_KEEP_WORKERS", block)
        self.assertIn("The page will be back in a few seconds. The model stays loaded.",
                      (ROOT / "tools" / "caravan_lan.py").read_text())


class UiTests(unittest.TestCase):
    def test_settings_switch_and_warning(self):
        html = (ROOT / "proxy/web/index.html").read_text()
        self.assertIn("Open on my local network", html)
        self.assertIn('id="lanAccessCard"', html)
        self.assertIn('id="lanAccessSwitch"', html)
        self.assertIn('id="lanAccessWarning"', html)
        self.assertIn("Anyone on the same network can use Caravan, and there is no login.", html)
        self.assertIn('data-lan="on"', html)
        self.assertIn('data-lan="off"', html)
        self.assertIn("/api/lan", html)
        self.assertIn("refreshLanAccess", html)
        self.assertIn("renderLanAccess", html)
        # Clickable links are built the same way as the Tailscale ones.
        self.assertIn('const a = document.createElement("a");', html)
        lan_fn = html[html.index("function renderLanAccess"):html.index("async function refreshLanAccess")]
        self.assertIn('a.href = addr;', lan_fn)
        self.assertIn('a.textContent = addr;', lan_fn)
        self.assertIn('a.target = "_blank";', lan_fn)
        # Sits next to the Tailscale option.
        self.assertLess(html.index('id="remoteAccessCard"'), html.index('id="lanAccessCard"'))
        self.assertLess(html.index('id="lanAccessCard"'), html.index('id="topoBarsCard"'))
        # Addresses are assigned as text, not concatenated into innerHTML.
        self.assertNotIn('lanAccessStatus").innerHTML', html)
        self.assertIn("The page will be back in a few seconds. The model stays loaded.", html)

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


class DocsLanTests(unittest.TestCase):
    def test_docs_use_placeholder_not_hostnames_or_jargon_in_user_facing(self):
        files = [
            ROOT / "docs" / "WEB.md",
            ROOT / "docs" / "REMOTE-ACCESS.md",
            ROOT / "INSTALL.md",
            ROOT / "docs" / "SECURITY.md",
            ROOT / "docs" / "DAY24.md",
            ROOT / "docs" / "release-notes" / "day24.md",
        ]
        import re
        def flat(s):
            return re.sub(r"\s+", " ", s)
        for path in files:
            text = path.read_text()
            self.assertIn("Anyone on the same network can use Caravan, and there is no login.", flat(text), path.name)
            self.assertIn("http://<lan-ip>:<port>", text, path.name)
            self.assertNotIn("mymac.local", text)
            self.assertNotIn("192.168.", text)
            self.assertNotIn("10.0.0.", text)

    def test_warning_copy_appears_in_module(self):
        self.assertIn("there is no login", L.WARNING)
        self.assertIn("same network", L.WARNING)


if __name__ == "__main__":
    unittest.main()
