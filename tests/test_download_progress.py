"""Truthful download progress: hook → disk → nettop, stall, starting…"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
import download_progress as DP  # noqa: E402


class ProgressTest(unittest.TestCase):
    def test_starting_until_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            snap = DP.combine_progress(
                dest=td, repo_id="org/model", total_bytes=10_000_000_000, pid=None,
            )
            self.assertEqual(snap["source"], "starting")
            self.assertIn("starting", snap["msg"])
            self.assertEqual(snap["pct"], 0)

    def test_disk_progress(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.safetensors").write_bytes(b"x" * 2_000_000)
            snap = DP.combine_progress(
                dest=td, repo_id="org/model", total_bytes=10_000_000, pid=None,
            )
            self.assertEqual(snap["source"], "disk")
            self.assertGreater(snap["have_bytes"], 0)
            self.assertGreater(snap["pct"], 0)

    def test_hook_beats_disk(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.safetensors").write_bytes(b"x" * 1000)
            hook = DP.progress_path_for("org/model")
            hook.write_text(json.dumps({"have_bytes": 5_000_000, "total_bytes": 10_000_000}) + "\n")
            try:
                snap = DP.combine_progress(
                    dest=td, repo_id="org/model", total_bytes=10_000_000, pid=None,
                )
                self.assertEqual(snap["source"], "hook")
                self.assertEqual(snap["have_bytes"], 5_000_000)
            finally:
                hook.unlink(missing_ok=True)

    def test_nettop_when_incomplete_stuck(self):
        with tempfile.TemporaryDirectory() as td:
            # disk empty; fake nettop growth
            with mock.patch.object(DP, "nettop_bytes_in", side_effect=[1000, 4_000_000]):
                with mock.patch.object(DP, "find_fetch_pids", return_value=[123]):
                    s1 = DP.combine_progress(
                        dest=td, repo_id="org/m", total_bytes=10_000_000, pid=123,
                    )
                    self.assertIn(s1["source"], ("starting", "nettop"))
                    s2 = DP.combine_progress(
                        dest=td, repo_id="org/m", total_bytes=10_000_000, pid=123, prev=s1,
                    )
                    self.assertEqual(s2["source"], "nettop")
                    self.assertGreater(s2["have_bytes"], 0)
                    self.assertNotIn("starting", s2["msg"])

    def test_stall_warning(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.safetensors").write_bytes(b"x" * 2_000_000)
            prev = DP.combine_progress(
                dest=td, repo_id="org/m", total_bytes=10_000_000,
            )
            prev["last_byte_t"] = time.time() - 45
            prev["t"] = time.time() - 45
            with mock.patch.object(DP, "STALL_SECS", 30):
                snap = DP.combine_progress(
                    dest=td, repo_id="org/m", total_bytes=10_000_000, prev=prev,
                )
            self.assertTrue(snap["stalled"])
            self.assertIn("stalled", snap["msg"])


if __name__ == "__main__":
    unittest.main()
