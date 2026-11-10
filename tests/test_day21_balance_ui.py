"""Production Balance DOM handlers and pure N-Mini view helpers (Node required)."""
import json
import sys
import shutil
import subprocess
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'), 'Node is needed for production JS contract tests')
class BalanceUiTests(unittest.TestCase):
    def test_reload_settings_backend_contract(self):
        sys.path.insert(0, str(ROOT/'proxy'))
        import web_settings
        for active in ({'self_tune': False, 'guess_ahead': False, 'shared_start': False,
                        'keepalive': True, 'prompt_lookup': {'enabled': False},
                        'fuse_kernels': 'off', 'kv_bits': 16, 'pipeline_chats': 1},
                       {'self_tune': True, 'guess_ahead': True, 'shared_start': True,
                        'keepalive': False, 'prompt_lookup': {'enabled': True, 'adaptive': True},
                        'fuse_kernels': 'on', 'kv_bits': 8, 'pipeline_chats': 1}):
            script = "const v=require('./proxy/web/balance_view.js');console.log(JSON.stringify(v.reloadSettings("+json.dumps({'active': active})+")));"
            p = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(p.returncode, 0, p.stderr)
            settings = json.loads(p.stdout)
            normalized = web_settings.normalize(settings)
            self.assertEqual(normalized['kv_bits'], str(active['kv_bits']))
            web_settings.to_args(normalized)

    def run_case(self, name):
        p = subprocess.run(['node', str(ROOT/'tests/js/balance_harness.js'), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

for case in ('n_boundaries', 'invalid_boundary', 'cards_unknown', 'valid_plan', 'summaries',
             'default_auto', 'adjust_n', 'back_auto', 'slider_pending', 'stale_response',
             'no_change', 'reload_immediate_lock', 'reload_stale_ready', 'reload_steps', 'reload_done',
             'reload_mismatch', 'reload_error', 'reload_network_loss', 'external_reload', 'external_unload', 'reload_settings', 'gguf_matches',
             'error_disables', 'gguf_no_capacity', 'gguf_adjust', 'apply_exact', 'unsafe_plan'):
    setattr(BalanceUiTests, 'test_'+case, lambda self, name=case: self.run_case(name))
