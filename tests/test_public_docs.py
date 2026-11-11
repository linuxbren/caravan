"""Public guides should stand alone without the original private test setup."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUIDES = ['README.md', 'INSTALL.md'] + [f'docs/{name}.md' for name in (
    'ARCHITECTURE', 'CONFIGURATION', 'DEVELOPMENT', 'FILES', 'INTEGRATING',
    'METHODOLOGY', 'MLX', 'MLX-SPLIT', 'MODEL_PICKER', 'OPTIMIZE-NOW',
    'PACKAGING', 'RELEASES', 'REMOTE-ACCESS', 'ROADMAP', 'SECURITY', 'SERVICES', 'WEB')]


class PublicDocsTest(unittest.TestCase):
    def test_current_guides_do_not_assume_private_names(self):
        pattern = r'(?i)\b(?:omarchy|exo1|exo2|brenden|riley|talaria|omasizer|hermes)\b'
        for filename in GUIDES:
            self.assertIsNone(re.search(pattern, (ROOT/filename).read_text()), filename)

    def test_current_guides_have_no_personal_network_or_paths(self):
        pattern = r'(?i)/Users/(?!YOUR_)[^ /`]+|/home/brenden|prf-hays|(?<!\d)(?:192\.168|169\.254|100\.68)\.\d+\.\d+'
        for filename in GUIDES:
            self.assertIsNone(re.search(pattern, (ROOT/filename).read_text()), filename)

    def test_no_hardware_memory_size_recommendations(self):
        for filename in GUIDES:
            self.assertIsNone(re.search(r'\b(?:16|24|32|64|128)\s*(?:GB|GiB)\b', (ROOT/filename).read_text()), filename)

    def test_index_and_log_explain_old_names(self):
        for filename in ('docs/README.md', 'docs/LOG.md'):
            text = (ROOT/filename).read_text()
            for term in ('development node', '1st node', '2nd node', 'Omarchy', 'EXO1', 'EXO2'):
                self.assertIn(term, text, (filename, term))

    def test_naming_rule_is_in_daily_checklist(self):
        self.assertIn('Apply the public naming rule daily', (ROOT/'docs/RELEASES.md').read_text())

    def test_visible_startup_messages_use_roles_not_lab_names(self):
        text = (ROOT/'proxy/web_workers.py').read_text()
        for old in ('starting packer on EXO2', 'starting lead on EXO1', 'model folder missing on EXO1'):
            self.assertNotIn(old, text)
        self.assertIn('starting lead on the 1st node', text)


if __name__ == '__main__': unittest.main()
