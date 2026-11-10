"""Production Balance DOM handlers and pure N-Mini view helpers (Node required)."""
import shutil
import subprocess
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'), 'Node is needed for production JS contract tests')
class BalanceUiTests(unittest.TestCase):
    def run_case(self, name):
        p = subprocess.run(['node', str(ROOT/'tests/js/balance_harness.js'), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

for case in ('n_boundaries', 'invalid_boundary', 'cards_unknown', 'valid_plan', 'summaries',
             'default_auto', 'adjust_n', 'back_auto', 'slider_pending', 'stale_response',
             'no_change', 'reload_immediate_lock', 'reload_stale_ready', 'reload_steps', 'reload_done',
             'reload_mismatch', 'reload_error', 'reload_network_loss', 'external_reload', 'external_unload', 'reload_settings', 'gguf_matches',
             'error_disables', 'gguf_no_capacity', 'gguf_adjust', 'apply_exact', 'unsafe_plan'):
    setattr(BalanceUiTests, 'test_'+case, lambda self, name=case: self.run_case(name))
