"""Measured split outcomes must not advertise universal helper speedups."""
import unittest
from pathlib import Path
from proxy.web_settings import OPTIONS

class MeasuredLabels(unittest.TestCase):
    def test_split_settings_keep_the_negative_result(self):
        options={o['id']:o for o in OPTIONS}
        for name in ('guess_ahead','pipeline_chats'):
            self.assertIn('slower',options[name]['help'])
        self.assertIn('~70% more combined output',options['pipeline_chats']['help'])
        self.assertIn('no gain on one Mini',options['pipeline_chats']['help'])
        self.assertIn('~33% faster writing one reply on a split model',options['guess_ahead']['help'])

    def test_badge_is_tested_but_not_a_general_speed_claim(self):
        html=(Path(__file__).resolve().parents[1]/'proxy/web/index.html').read_text()
        self.assertIn('Qwen N2 tested, helper slower',html)
        self.assertNotIn('split block verify · awaiting live benchmark',html)

    def test_settings_help_is_plain_and_qualified(self):
        options = {o['id']: o for o in OPTIONS}
        for option in OPTIONS:
            self.assertNotRegex(option['help'], r'Day\s*\d|tok/s|→|Qwen|Orvena|overlap gate|rewindable')
        self.assertIn('matching helper', options['guess_ahead']['help'])
        self.assertIn('~44%', options['prompt_lookup']['help'])
        self.assertIn('slower on mixed chats', options['prompt_lookup']['help'])
        self.assertIn('no meaningful speed gain', options['fuse_kernels']['help'])
        self.assertIn('slow reading', options['kv_bits']['help'])
        self.assertIn('Split MLX models only', options['keepalive']['help'])
        self.assertIn('~50%', options['keepalive']['help'])
        html = (Path(__file__).resolve().parents[1] / 'proxy/web/index.html').read_text()
        self.assertIn('Up to ~46% faster writing replies in our tests', html)
        self.assertIn('needs a matching MTP head and one chat at a time', html)
        self.assertNotIn('Day17 Orvena4B', html)

    def test_no_restart_copy_matches_server_options(self):
        import json
        import re
        html = (Path(__file__).resolve().parents[1] / 'proxy/web/index.html').read_text()
        match = re.search(r'const SETTINGS_HELP_COPY = (\{.*?\});', html, re.S)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), {o['id']: o['help'] for o in OPTIONS})
        self.assertIn('SETTINGS_HELP_COPY[o.id] || o.help', html)
