"""Day 31 follow-up (v0.9.2): the app says "context", not "window".

Brenden: "Let's just keep it consistent." The video's scene 3 quotes the
1-Mac-vs-split line, so that exact string is pinned here. Internal ids and
keys (chat_window, window_note, window_ctx) stay the same so saved
settings keep working.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tests"))

import caravan_prompts as CP  # noqa: E402
import gguf_split as G  # noqa: E402
import web_picker as P  # noqa: E402
import web_settings as WS  # noqa: E402
from test_day31_context_fit import LLAMA8, MTWO, place  # noqa: E402

SCENE3 = "Fits on 1 Mac with a 64K context. Split across 2 Macs for the full 128K context."


class Scene3String(unittest.TestCase):
    def test_gguf_summary_is_exact(self):
        self.assertEqual(place(13.0)["summary"], SCENE3)

    def test_mlx_reason_is_exact(self):
        self.assertEqual(P.fit_check(weights_gb=4.5, nodes=MTWO, cfg=LLAMA8)["reason"], SCENE3)


class SettingsRow(unittest.TestCase):
    def test_label_is_context_and_key_unchanged(self):
        row = next(o for o in WS.OPTIONS if o["id"] == "chat_window")
        self.assertEqual(row["label"], "Context")
        self.assertNotIn("window", row["help"].lower())
        self.assertEqual(WS.normalize({"chat_window": "65536"})["chat_window"], "65536")

    def test_page_help_copy_says_context(self):
        html = (ROOT / "proxy/web/index.html").read_text()
        for line in re.findall(r'"chat_window": "([^"]*)"', html):
            self.assertNotIn("window", line.lower())
            self.assertIn("context", line)
        self.assertNotIn("`chat window ", html)

    def test_user_facing_lines_say_context(self):
        self.assertEqual(G.WINDOW_SKIP, "needs a shorter context")
        self.assertIn("context is 8192", CP.skip_reason(8192, 8192))
        self.assertNotIn("window", CP.skip_reason(8192, 8192))


if __name__ == "__main__":
    unittest.main()
