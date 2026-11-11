"""The native acceptance harness must never select an existing real HOME."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import pairing_smoke as smoke

class ScratchSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.real=Path(self.tmp.name).resolve()
        self.patch=mock.patch.object(smoke.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=str(self.real)));self.patch.start()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_real_home_refused(self):
        with self.assertRaises(ValueError):smoke.scratch(self.real)
    def test_production_state_refused(self):
        with self.assertRaises(ValueError):smoke.scratch(self.real/'.caravan')
    def test_fresh_private_sibling_accepted(self):
        home=smoke.scratch(self.real/'.caravan-pairing-smoke-test')
        self.assertEqual(home.stat().st_mode&0o777,0o700)
        self.assertEqual((home/'.pairing-smoke-owned').stat().st_mode&0o777,0o600)
    def test_easy_install_shell_caches_accepted(self):
        home=self.real/'.caravan-pairing-smoke-test';home.mkdir()
        for name in ('.caravan','Library','.rustup'):(home/name).mkdir()
        self.assertEqual(smoke.scratch(home),home)
    def test_unrelated_data_refused(self):
        home=self.real/'.caravan-pairing-smoke-test';home.mkdir();(home/'my-file').write_text('keep')
        with self.assertRaises(ValueError):smoke.scratch(home)
        self.assertEqual((home/'my-file').read_text(),'keep')
        self.assertFalse((home/'.pairing-smoke-owned').exists())

if __name__=='__main__':unittest.main()
