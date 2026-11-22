"""Day 31: no code path falls back to the old ~/cv3 dev checkout.

Topology showed this Mac's code folder as ~/cv3 on both Macs, because a
node without `repo` in config.toml got that default. Installs keep their
code in ~/.caravan/src/caravan, and ~/cv3 no longer exists on either Mac.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))

import web_nodes as N  # noqa: E402

CFG = {"_raw": {"web": {"nodes": {
    "local": {"label": "My Mac", "role": "lead", "host": "local"},
    "paired_x": {"label": "Mac 2", "role": "packer", "host": "h", "ssh": "h"},
    "paired_y": {"label": "Mac 3", "role": "packer", "host": "k", "ssh": "k",
                 "repo": "/Users/me/.caravan/src/caravan"},
}}}}


class RepoDefault(unittest.TestCase):
    def test_this_mac_shows_the_code_it_runs_from(self):
        local = N.nodes_from_config(CFG)[0]
        self.assertEqual(local["repo"], N.LOCAL_REPO)
        self.assertEqual(Path(N.LOCAL_REPO), ROOT.resolve())

    def test_other_mac_without_repo_uses_the_install_folder(self):
        node = N.nodes_from_config(CFG)[1]
        self.assertEqual(node["repo"], "~/.caravan/src/caravan")
        self.assertEqual(N.DEFAULT_REPO, "~/.caravan/src/caravan")

    def test_saved_repo_is_kept(self):
        self.assertEqual(N.nodes_from_config(CFG)[2]["repo"], "/Users/me/.caravan/src/caravan")

    def test_stats_command_default(self):
        self.assertIn("~/.caravan/src/caravan", N.remote_stats_command())
        self.assertNotIn("cv3", N.remote_stats_command())

    def test_legacy_default_nodes(self):
        for n in N.DEFAULT_NODES:
            self.assertNotIn("cv3", str(n))

    def test_no_code_falls_back_to_cv3(self):
        hits = []
        for folder in ("proxy", "agent", "tools", "scripts"):
            for f in (ROOT / folder).rglob("*"):
                if f.is_file() and f.suffix in (".py", ".sh", ".js", ".html") and "__pycache__" not in f.parts:
                    if "~/cv3" in f.read_text(errors="ignore"):
                        hits.append(str(f.relative_to(ROOT)))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
