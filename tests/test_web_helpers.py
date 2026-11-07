import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import web_helpers as H


class HelperConsentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        table = H.G.load_table()
        table['drafts_dir'] = self.tmp.name + '/drafts'
        table['state_file'] = self.tmp.name + '/state.json'
        self.table = table
        self.patcher = patch.object(H.G, 'load_table', return_value=table)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.snap = {'model_id':'mlx-community/Qwen3-30B-A3B-4bit', 'split':True, 'settings':{'guess_ahead':'on'}}

    def test_noninteractive_does_not_answer(self):
        self.assertFalse(H.G.ask_download(self.table['pairings'][0], auto=False, interactive=False))
        self.assertEqual(H.G.load_state()['download_answers'], {})

    def test_offer_real_size_and_decline(self):
        self.assertEqual(H.offer(self.snap)['size_mb'], 335)
        H.answer('qwen3-30b-a3b', False)
        self.assertTrue(H.offer(self.snap)['declined'])
        H.answer('qwen3-30b-a3b', True)
        self.assertFalse(H.offer(self.snap)['declined'])

    def test_legacy_silent_decline_does_not_hide_offer(self):
        H.G.save_state({'download_answers': {'qwen3-30b-a3b': False}})
        self.assertFalse(H.offer(self.snap)['declined'])

    def test_off_single_unknown_and_installed(self):
        self.assertIsNone(H.offer({**self.snap, 'split':False}))
        self.assertIsNone(H.offer({**self.snap, 'settings':{'guess_ahead':'off'}}))
        self.assertIsNone(H.offer({**self.snap, 'model_id':'gpt-oss'}))
        p = H.G.drafts_dir() / 'Qwen3-0.6B-4bit'
        p.mkdir(parents=True); (p / 'config.json').write_text('{}')
        self.assertIsNone(H.offer(self.snap))

    def test_inventory_and_delete_guard(self):
        p = H.G.drafts_dir() / 'Qwen3-0.6B-4bit'
        p.mkdir(parents=True); (p / 'config.json').write_text('{}')
        key = 'draft:Qwen3-0.6B-4bit'
        self.assertIn('Qwen3-30B-A3B', H.inventory()[key]['pairs'])
        self.assertFalse(H.delete_helper(key, self.snap['model_id'])['ok'])
        self.assertTrue(p.exists())
        self.assertFalse(H.delete_helper('draft:../../etc')['ok'])
        self.assertTrue(H.delete_helper(key)['ok'])

    def test_unknown_answer_rejected(self):
        with self.assertRaises(ValueError): H.answer('unknown', True)
