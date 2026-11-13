"""Day 26 Voice design notes exist and stay listening-first."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


class VoiceDesignNotes(unittest.TestCase):
    def test_notes_exist_and_are_design_only(self):
        text = _flat(ROOT / "docs" / "VOICE.md")
        self.assertIn("listening first", text)
        self.assertIn("nothing here is running", text)
        self.assertIn("microphone", text)
        self.assertIn("ask caravan", text)
        self.assertIn("does not unload the chat model", text)
        self.assertIn("will not download a listen model on its own", text)
        self.assertIn("spoken replies wait", text)
        self.assertIn("1st mac", text)
        # no shipped worker
        worker = ROOT / "agent" / "speech_worker.py"
        self.assertFalse(worker.exists())

    def test_day26_points_at_the_notes(self):
        text = _flat(ROOT / "docs" / "DAY26.md")
        self.assertIn("voice.md", text)
        self.assertIn("no listening code is shipped", text)


if __name__ == "__main__":
    unittest.main()
