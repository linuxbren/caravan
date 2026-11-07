from __future__ import annotations

import re
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "proxy" / "web" / "index.html").read_text()


class LoadNowPrompt(unittest.TestCase):
    def test_dialog_has_both_choices(self):
        self.assertIn('id="loadNowDialog"', HTML)
        self.assertIn(">Load now<", HTML)
        self.assertIn(">Not now<", HTML)

    def test_no_silent_autoload_after_download(self):
        body = HTML[HTML.index("async function pollJob("):]
        body = body[: body.index('if (j.status === "error"')]
        load = body.index("/api/models/load")
        self.assertLess(body.index("await askLoadNow("), load)

    def test_dialog_is_themed(self):
        # Base dialog style uses theme vars; Meadow and Nebula add glass.
        self.assertRegex(HTML, r"\n  dialog \{\s*background: var\(--bg2\)")
        for t in ("meadow", "nebula"):
            self.assertRegex(HTML, r'html\[data-theme="%s"\] dialog' % t)


if __name__ == "__main__":
    unittest.main()
