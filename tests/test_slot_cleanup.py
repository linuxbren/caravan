"""Unit tests for proxy/slot_cleanup.py (+ its wiring into slot_pin_proxy).

    python3 -m unittest discover -s tests -v      # from the repo root

Everything runs against temp dirs -- never the real ~/.caravan.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))

import slot_cleanup  # noqa: E402

DAY = 86400.0
CLEAN_ENV = {k: "" for k in slot_cleanup.ENV_VARS.values()}


class SlotCleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.slots = root / "slots"
        self.slots.mkdir()
        self.archive = root / "slots-archive"
        self.state = root / "session_slots.json"
        self.config = root / "config.json"
        self.now = time.time()
        env = dict(CLEAN_ENV, CARAVAN_CONFIG=str(self.config))
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _slot(self, name, age_days, size=10):
        p = self.slots / name
        p.write_bytes(b"x" * size)
        t = self.now - age_days * DAY
        os.utime(p, (t, t))
        return p

    def _settings(self, **kw):
        base = {"slot_dir": str(self.slots), "state_file": str(self.state),
                "archive_dir": str(self.archive)}
        base.update(kw)
        return slot_cleanup.resolve_settings(base)

    def _write_state(self, assignments):
        self.state.write_text(json.dumps({"assignments": assignments, "next_slot": 3}))

    # --- settings precedence -------------------------------------------------
    def test_defaults(self):
        s = slot_cleanup.resolve_settings()
        self.assertEqual((s.mode, s.max_age_days, s.interval_hours), ("delete", 30.0, 6.0))
        self.assertTrue(str(s.archive_dir).endswith(".caravan/llama-server/slots-archive"))

    def test_precedence_flag_env_file(self):
        self.config.write_text(json.dumps({"slot_cleanup": {
            "mode": "archive", "max_age_days": 7, "interval_hours": 1}}))
        s = slot_cleanup.resolve_settings()
        self.assertEqual((s.mode, s.max_age_days, s.interval_hours), ("archive", 7.0, 1.0))
        with mock.patch.dict(os.environ, {"CARAVAN_SLOT_MAX_AGE_DAYS": "14",
                                          "CARAVAN_SLOT_CLEANUP": "off"}):
            s = slot_cleanup.resolve_settings()
            self.assertEqual((s.mode, s.max_age_days), ("off", 14.0))
            s = slot_cleanup.resolve_settings({"max_age_days": 3, "mode": "delete"})
            self.assertEqual((s.mode, s.max_age_days), ("delete", 3.0))

    def test_bad_settings(self):
        with self.assertRaises(ValueError):
            slot_cleanup.resolve_settings({"mode": "nuke"})
        with self.assertRaises(ValueError):
            slot_cleanup.resolve_settings({"max_age_days": 0})

    # --- behavior ------------------------------------------------------------
    def test_find_stale_only_old_bin_files(self):
        self._slot("old.bin", 40)
        self._slot("new.bin", 5)
        self._slot("old.txt", 40)
        (self.slots / "sub.bin").mkdir()
        link = self.slots / "link.bin"
        link.symlink_to(self._slot("target.dat", 40))
        os.utime(link, (self.now - 40 * DAY,) * 2, follow_symlinks=False)
        stale = slot_cleanup.find_stale(self.slots, 30, now=self.now)
        self.assertEqual([f.path.name for f in stale], ["old.bin"])

    def test_dry_run_changes_nothing(self):
        a = self._slot("aaaa.bin", 40, size=100)
        b = self._slot("bbbb.bin", 31, size=50)
        self._slot("cccc.bin", 1)
        self._write_state({"aaaa": 0, "cccc": 1})
        before = self.state.read_text()
        r = slot_cleanup.cleanup(self._settings(mode="archive"), dry_run=True, now=self.now)
        self.assertEqual(sorted(f.path.name for f in r.candidates), ["aaaa.bin", "bbbb.bin"])
        self.assertEqual(sum(f.size for f in r.candidates), 150)
        self.assertEqual(r.removed, [])
        self.assertTrue(a.exists() and b.exists())
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.state.read_text(), before)

    def test_delete_mode_and_state_prune(self):
        self._slot("aaaa.bin", 40, size=100)
        keep = self._slot("cccc.bin", 1)
        self._write_state({"aaaa": 0, "cccc": 1, "dddd": 2})
        r = slot_cleanup.cleanup(self._settings(), now=self.now)
        self.assertEqual([f.path.name for f in r.removed], ["aaaa.bin"])
        self.assertEqual(r.bytes_removed, 100)
        self.assertEqual(r.dropped_assignments, ["aaaa"])
        self.assertFalse((self.slots / "aaaa.bin").exists())
        self.assertTrue(keep.exists())
        data = json.loads(self.state.read_text())
        self.assertEqual(data["assignments"], {"cccc": 1, "dddd": 2})
        self.assertEqual(data["next_slot"], 3)
        self.assertFalse(list(self.state.parent.glob("*.tmp")))

    def test_archive_mode_moves_and_handles_name_clash(self):
        self._slot("aaaa.bin", 40, size=7)
        self.archive.mkdir()
        (self.archive / "aaaa.bin").write_bytes(b"older archived copy")
        r = slot_cleanup.cleanup(self._settings(mode="archive"), now=self.now)
        self.assertEqual(len(r.removed), 1)
        self.assertFalse((self.slots / "aaaa.bin").exists())
        archived = sorted(p.name for p in self.archive.iterdir())
        self.assertEqual(len(archived), 2)
        self.assertIn("aaaa.bin", archived)

    def test_archive_dir_same_as_slot_dir_rejected(self):
        self._slot("aaaa.bin", 40)
        with self.assertRaises(ValueError):
            slot_cleanup.cleanup(self._settings(mode="archive", archive_dir=str(self.slots)),
                                 now=self.now)

    def test_off_mode_noop(self):
        p = self._slot("aaaa.bin", 400)
        r = slot_cleanup.cleanup(self._settings(mode="off"), now=self.now)
        self.assertEqual(r.removed, [])
        self.assertTrue(p.exists())

    def test_file_refreshed_under_gate_is_spared(self):
        p = self._slot("aaaa.bin", 40)

        @contextlib.contextmanager
        def gate():
            # Simulates a save landing between the scan and the removal.
            os.utime(p, (self.now, self.now))
            yield

        r = slot_cleanup.cleanup(self._settings(), gate=gate, now=self.now)
        self.assertEqual(r.removed, [])
        self.assertTrue(p.exists())

    def test_cli_dry_run_output(self):
        self._slot("aaaa.bin", 40, size=1000)
        self._slot("bbbb.bin", 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = slot_cleanup.main(["--slot-dir", str(self.slots), "--state-file", str(self.state),
                                    "--max-age-days", "30", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("DRY RUN: 1 file(s)", out.getvalue())
        self.assertIn("total 1000 bytes", out.getvalue())
        self.assertTrue((self.slots / "aaaa.bin").exists())


class ProxyWiringTest(unittest.TestCase):
    """slot_pin_proxy's gate/forget hooks: cleanup waits for the FIFO gate
    and drops assignments from the live in-memory map."""

    def test_proxy_cleanup_waits_for_gate_and_forgets(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            slots = d / "slots"
            slots.mkdir()
            state = d / "session_slots.json"
            state.write_text(json.dumps({"assignments": {"aaaa": 0, "bbbb": 1}, "next_slot": 2}))
            old = slots / "aaaa.bin"
            old.write_bytes(b"x")
            t = time.time() - 40 * DAY
            os.utime(old, (t, t))
            env = dict(CLEAN_ENV, CARAVAN_PROXY_STATE_FILE=str(state),
                       CARAVAN_SLOT_SAVE_DIR=str(slots), CARAVAN_CONFIG=str(d / "none.json"),
                       CARAVAN_SLOT_CLEANUP_INTERVAL_HOURS="0")
            with mock.patch.dict(os.environ, env):
                sys.modules.pop("slot_pin_proxy", None)
                with contextlib.redirect_stderr(io.StringIO()):
                    import slot_pin_proxy as spp
                    spp._warm_this_run.add("aaaa")
                    # A request is "in flight": hold the FIFO gate.
                    ticket, _, _ = spp.completion_fifo.acquire()
                    thread = spp.start_slot_cleanup()
                    time.sleep(0.3)
                    self.assertTrue(old.exists(), "cleanup must wait for the gate")
                    spp.completion_fifo.release(ticket)
                    thread.join(timeout=5)
                self.assertFalse(old.exists())
                self.assertEqual(json.loads(state.read_text())["assignments"], {"bbbb": 1})
                self.assertNotIn("aaaa", spp._warm_this_run)
                sys.modules.pop("slot_pin_proxy", None)


if __name__ == "__main__":
    unittest.main()
