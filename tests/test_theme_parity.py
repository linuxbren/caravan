"""Themes may change colours and backgrounds, never layout metrics."""
import re
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "proxy" / "web" / "index.html").read_text()
THEMES = ("amber", "green", "meadow", "campfire")


class ThemeParityTest(unittest.TestCase):
    def test_theme_variables_scoped_to_html(self):
        # A bare [data-theme="x"] block also matches the theme-switch buttons,
        # which carry data-theme too, so each label got its own font/size.
        bare = re.findall(r'^\s*(?::root,\s*)?\[data-theme="[a-z]+"\]\s*\{', HTML, re.M)
        self.assertEqual(bare, [])
        for t in THEMES:
            self.assertRegex(HTML, r'html\[data-theme="%s"\]\s*\{' % t)

    def test_themes_keep_shared_layout_font(self):
        self.assertNotIn("--mono: var(--sans)", HTML)
        for t in THEMES:
            for m in re.finditer(r'html\[data-theme="%s"\][^{]*\{([^}]*)\}' % t, HTML):
                if re.search(r'-(bg|credit)\b', m.group(0).split('{')[0]):
                    continue  # theme-only decoration, not a shared control
                body = m.group(1)
                for prop in ("letter-spacing", "text-transform", "padding", "font-size"):
                    self.assertNotRegex(body, r'(^|[;\s])%s\s*:' % prop, m.group(0)[:80])


if __name__ == "__main__":
    unittest.main()
