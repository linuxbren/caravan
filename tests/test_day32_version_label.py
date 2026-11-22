"""Day 32 part A: the installed version next to the Settings title.

The number comes from the VERSION file that ships in the installed source
and the build from the installed pin (.caravan-package); the status comes
from the daily update check. `caravan --version`, `caravan status` and
`caravan doctor` show the same version.
"""
import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))

import caravan_version as CV  # noqa: E402

PIN = "4b48b85e83860cf2e8c35f7fb719e647dc20ea5d"


def fake_install(version="0.9.4", ref=PIN, git=False):
    d = Path(tempfile.mkdtemp())
    if version is not None:
        (d / "VERSION").write_text(version + "\n")
    if ref is not None:
        (d / ".caravan-package").write_text(ref + "\n")
    if git:
        (d / ".git").mkdir()
    return d


class VersionSource(unittest.TestCase):
    def test_package_install_reads_version_and_pin(self):
        i = CV.info(fake_install())
        self.assertEqual(i, {"version": "0.9.4", "label": "v0.9.4", "ref": PIN,
                             "short": "4b48b85", "packaged": True})
        self.assertEqual(CV.text(fake_install()), "Caravan v0.9.4 (4b48b85)")

    def test_missing_or_bad_version_is_unknown_not_guessed(self):
        self.assertEqual(CV.info(fake_install(version=None))["label"], "")
        self.assertEqual(CV.info(fake_install(version="latest"))["label"], "")
        self.assertEqual(CV.text(fake_install(version=None, ref=None)), "Caravan (version unknown)")

    def test_bad_pin_is_ignored(self):
        i = CV.info(fake_install(ref="not-a-sha"))
        self.assertIsNone(i["ref"])
        self.assertEqual(i["label"], "v0.9.4")

    def test_repo_version_file_matches_the_newest_release_docs(self):
        v = (ROOT / "VERSION").read_text().strip()
        self.assertRegex(v, r"^\d+\.\d+\.\d+$")
        top = (ROOT / "CHANGELOG.md").read_text().split("\n## ")[0]
        self.assertIn(f"(v{v})", top.splitlines()[0])
        self.assertEqual(CV.release(ROOT), v)

    def test_not_hardcoded_in_the_page_or_server(self):
        html = (ROOT / "proxy/web/index.html").read_text()
        server = (ROOT / "proxy/web_server.py").read_text()
        v = (ROOT / "VERSION").read_text().strip()
        self.assertNotIn("v" + v, html)
        self.assertNotIn('"' + v + '"', server)


class StatusApi(unittest.TestCase):
    def test_status_payload_carries_installed_version(self):
        import web_server as WS
        d = fake_install(version="1.2.3")
        (d / "tools").mkdir()
        got = WS._installed_version(d)
        self.assertEqual(got["label"], "v1.2.3")
        self.assertEqual(got["short"], PIN[:7])
        src = (ROOT / "proxy/web_server.py").read_text()
        body = src[src.index("def _api_status"):src.index("def _api_speed_average")]
        self.assertIn('"version": _installed_version()', body)


class PageLabel(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "proxy/web/index.html").read_text()

    def test_label_sits_next_to_settings_title(self):
        head = self.html[self.html.index('id="settingsDrawer"'):]
        head = head[:head.index("</div>", head.index("btnCloseSettings"))]
        self.assertRegex(head, r'<h2>Settings</h2><span class="ver-label" id="settingsVersion" hidden></span>')

    def test_styles_use_theme_colors_and_fonts(self):
        css = re.search(r"\.ver-label \{([^}]*)\}", self.html).group(1)
        self.assertIn("var(--mono)", css)
        self.assertIn("var(--muted)", css)

    def test_state_rules(self):
        js = self.html[self.html.index("function versionState"):self.html.index("function paintVersionLabel")]
        for needle in ('u.show === false', 'u.packaged === false', 'u.newer || u.peers_behind',
                       'return "update"', 'u.checked_at && !u.offline', 'return "ok"'):
            self.assertIn(needle, js)
        paint = self.html[self.html.index("function paintVersionLabel"):self.html.index("function paintUpdateBadge")]
        self.assertIn('"up to date"', paint)
        self.assertIn('"update available"', paint)
        self.assertIn('$("btnUpdateNow")', paint)
        self.assertIn('$("updatesCard")', paint)
        self.assertIn("v.label", paint)

    def test_fed_from_status_and_update_check(self):
        self.assertIn("_verInfo = (j && j.version) || null;", self.html)
        render = self.html[self.html.index("function renderUpdate(j)"):]
        self.assertIn("_verUpd = j || null;", render[:400])

    def test_state_logic_runs_in_node_when_available(self):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        js = self.html[self.html.index("function versionState"):self.html.index("function paintVersionLabel")]
        prog = js + """
const cases = [[null, ""], [{show:false, newer:true}, ""], [{packaged:false, checked_at:1}, ""],
  [{newer:true}, "update"], [{peers_behind:true, checked_at:1}, "update"],
  [{checked_at:1}, "ok"], [{checked_at:1, offline:true}, ""], [{}, ""]];
for (const [u, want] of cases) { if (versionState(u) !== want) { console.log("FAIL", JSON.stringify(u)); process.exit(1); } }
console.log("ok");
"""
        out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.stdout.strip(), "ok", out.stdout + out.stderr)


class Cli(unittest.TestCase):
    def test_version_flag(self):
        import caravan as CLI
        for flag in ("--version", "version", "-V"):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(CLI.main([flag]), 0)
            self.assertTrue(out.getvalue().startswith("Caravan v" + CV.release(ROOT)), out.getvalue())

    def test_doctor_lists_version(self):
        import caravan_doctor as D
        with mock.patch.object(D, "checks", wraps=D.checks):
            src = (ROOT / "tools/caravan_doctor.py").read_text()
        self.assertIn('"Installed: " + caravan_version.text()', src)


if __name__ == "__main__":
    unittest.main()
