"""Unit tests for ROADMAP #17 fuse_kernels helpers (no Metal required)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

import fuse_kernels as FK  # noqa: E402


class ResolveModeTest(unittest.TestCase):
    def test_cli_off_variants(self):
        for v in ("off", "0", "false", "no"):
            self.assertEqual(FK.resolve_mode(v), "off")

    def test_cli_all_variants(self):
        for v in ("all", "1", "true", "yes", "on"):
            self.assertEqual(FK.resolve_mode(v), "all")

    def test_cli_named_modes(self):
        self.assertEqual(FK.resolve_mode("force-fused"), "force-fused")
        self.assertEqual(FK.resolve_mode("metal-swiglu"), "metal-swiglu")

    def test_cli_wins_over_env(self):
        with mock.patch.dict(os.environ, {FK.FUSE_ENV: "all"}):
            self.assertEqual(FK.resolve_mode("off"), "off")

    def test_env_when_cli_none(self):
        with mock.patch.dict(os.environ, {FK.FUSE_ENV: "force-fused"}):
            self.assertEqual(FK.resolve_mode(None), "force-fused")
        with mock.patch.dict(os.environ, {FK.FUSE_ENV: "1"}):
            self.assertEqual(FK.resolve_mode(None), "all")
        with mock.patch.dict(os.environ, {FK.FUSE_ENV: ""}):
            self.assertEqual(FK.resolve_mode(None), "off")

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            FK.resolve_mode("banana")


class ApplyOffTest(unittest.TestCase):
    def test_off_applies_nothing(self):
        logs = []
        applied = FK.apply_fuse_kernels("off", log=logs.append)
        self.assertEqual(applied, [])
        self.assertTrue(any("off" in x for x in logs))


if __name__ == "__main__":
    unittest.main()
