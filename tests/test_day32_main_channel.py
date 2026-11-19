"""Day 32: Caravan lives on main. Install and update read main; older
installs keep working because the old branch names are fast-forwarded."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import caravan_update_check as UC  # noqa: E402

OLD = ("caravan-v3-mlx-split", "clean-install-fixes")
RAW = "https://raw.githubusercontent.com/linuxbren/caravan/"


class UpdateAndInstallPointAtMain(unittest.TestCase):
    def test_update_check_reads_the_pin_from_main(self):
        self.assertEqual(UC.CHANNEL_BRANCH, "main")
        self.assertEqual(UC.MANIFEST_URL, RAW + "main/packaging-version")
        self.assertEqual(UC.INSTALL_URL, RAW + "main/install")

    def test_caravan_update_fetches_the_install_script_from_main(self):
        src = (ROOT / "tools" / "caravan.py").read_text()
        self.assertIn("INSTALL_URL", src)
        for old in OLD:
            self.assertNotIn(old, src)

    def test_curl_installer_reads_the_pin_from_main(self):
        src = (ROOT / "install").read_text()
        urls = re.findall(r"https://raw\.githubusercontent\.com/linuxbren/caravan/([^/]+)/", src)
        self.assertTrue(urls)
        self.assertEqual(set(urls), {"main"})

    def test_source_installer_defaults_to_main(self):
        src = (ROOT / "scripts" / "install.sh").read_text()
        self.assertRegex(src, r"(?m)^REF=main$")

    def test_install_lines_in_readme_and_install_guide_use_main(self):
        line = "curl -fsSL " + RAW + "main/install | bash"
        for name in ("README.md", "INSTALL.md"):
            text = (ROOT / name).read_text()
            self.assertIn(line, text, name)
            for old in OLD:
                self.assertNotIn(old, text, name)

    def test_no_live_code_or_current_guide_names_an_old_branch(self):
        allowed = {
            "tools/caravan_update_check.py",  # LEGACY_CHANNEL_BRANCHES, documented
            "scripts/install.sh",             # accepts old-branch checkouts
            "docs/RELEASES.md",               # transition fast-forward step
            "docs/DEVELOPMENT.md",            # how to move an old checkout
            "tests/test_day32_main_channel.py",
        }
        paths = ["install", "README.md", "INSTALL.md"]
        for folder in ("tools", "proxy", "agent", "scripts", "runtime", "tests"):
            paths += [str(p.relative_to(ROOT)) for p in (ROOT / folder).rglob("*")
                      if p.is_file() and p.suffix in (".py", ".sh", ".html", ".js", ".json", ".toml", "")
                      and "__pycache__" not in p.parts]
        for name in ("RELEASES", "DEVELOPMENT", "INSTALL", "ARCHITECTURE", "CONFIGURATION",
                     "MLX", "MLX-SPLIT", "FILES", "PACKAGING", "SERVICES", "WEB", "PAIRING", "README"):
            p = ROOT / "docs" / f"{name}.md"
            if p.exists():
                paths.append(str(p.relative_to(ROOT)))
        hits = []
        for rel in paths:
            if rel in allowed:
                continue
            try:
                text = (ROOT / rel).read_text(errors="ignore")
            except (IsADirectoryError, OSError):
                continue
            hits += [f"{rel}: {old}" for old in OLD if old in text]
        self.assertEqual(hits, [])

    def test_legacy_branches_listed_for_the_transition(self):
        self.assertEqual(tuple(UC.LEGACY_CHANNEL_BRANCHES), OLD)
        steps = (ROOT / "docs" / "RELEASES.md").read_text()
        self.assertIn("main:caravan-v3-mlx-split", steps)
        self.assertIn("main:clean-install-fixes", steps)


class OldBranchCheckoutsKeepUpdating(unittest.TestCase):
    def script(self, home, *args):
        return subprocess.run(["bash", str(ROOT / "scripts/install.sh"), *args],
                              env=dict(os.environ, HOME=str(home)),
                              text=True, capture_output=True, timeout=10)

    def _repo(self, root, branch):
        folder = Path(root) / "repo"
        subprocess.run(["git", "init", "-q", str(folder)], check=True)
        subprocess.run(["git", "-C", str(folder), "symbolic-ref", "HEAD", f"refs/heads/{branch}"], check=True)
        subprocess.run(["git", "-C", str(folder), "remote", "add", "origin",
                        "https://github.com/linuxbren/caravan.git"], check=True)
        return folder

    def test_old_branch_checkout_is_accepted_and_kept(self):
        for branch in OLD:
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as root:
                folder = self._repo(root, branch)
                r = self.script(root, "--dry-run", "--python", sys.executable, "--repo", str(folder))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("old branch name " + branch, r.stdout)
                self.assertIn("leaving its code unchanged", r.stdout)

    def test_old_branch_update_pulls_that_branch_without_switching(self):
        with tempfile.TemporaryDirectory() as root:
            folder = self._repo(root, OLD[0])
            r = self.script(root, "--dry-run", "--update", "--python", sys.executable, "--repo", str(folder))
            self.assertIn("pull --ff-only origin " + OLD[0], r.stdout)
            self.assertNotIn("switch", r.stdout)

    def test_explicit_ref_still_refuses_a_different_branch(self):
        with tempfile.TemporaryDirectory() as root:
            folder = self._repo(root, OLD[0])
            r = self.script(root, "--dry-run", "--python", sys.executable, "--repo", str(folder), "--ref", "main")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("not main", r.stderr)


if __name__ == "__main__":
    unittest.main()
