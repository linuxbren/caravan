"""Measured split outcomes must not advertise universal helper speedups."""
import unittest
from pathlib import Path
from proxy.web_settings import OPTIONS

class MeasuredLabels(unittest.TestCase):
    def test_split_settings_keep_the_negative_result(self):
        options={o['id']:o for o in OPTIONS}
        for name in ('guess_ahead','pipeline_chats'):
            self.assertIn('49.77',options[name]['help'])
            self.assertIn('slower',options[name]['help'])
        self.assertIn('41.54→70.49',options['pipeline_chats']['help'])
        self.assertIn('41.54→52.11',options['guess_ahead']['help'])

    def test_badge_is_tested_but_not_a_general_speed_claim(self):
        html=(Path(__file__).resolve().parents[1]/'proxy/web/index.html').read_text()
        self.assertIn('Qwen N2 tested, helper slower',html)
        self.assertNotIn('split block verify · awaiting live benchmark',html)
