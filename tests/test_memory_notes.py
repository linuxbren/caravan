"""Archive + BM25 recall + archive-awareness note for memory_notes.py."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
import memory_notes as MN  # noqa: E402


class ArchiveRecallTest(unittest.TestCase):
    def test_append_and_recall(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            turns = [
                {"role": "user", "content": "The red fox named Ember found a silver key under oak leaves."},
                {"role": "assistant", "content": "Ember tucked the silver key into her den."},
            ]
            info = MN.append_turns(root, "sess1", turns, model="Qwen")
            self.assertTrue(Path(info["path"]).is_file())
            text = Path(info["path"]).read_text()
            self.assertIn("## turn 1", text)
            self.assertIn("Ember", text)
            self.assertIn("session: sess1", text)
            snips = MN.bm25_recall(root, "sess1", "What about the silver key?", top_k=2)
            self.assertTrue(snips)
            self.assertTrue(any("key" in s["text"].lower() for s in snips))
            note = MN.format_recall_note(snips, archived_turns=2)
            self.assertIn("Note: 2 earlier turns", note)
            self.assertIn("Relevant bits from those notes:", note)
            self.assertIn("key", note.lower())

    def test_append_increments_turns(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            MN.append_turns(root, "s", [{"role": "user", "content": "one"}], model="m")
            info = MN.append_turns(root, "s", [{"role": "user", "content": "two"}], model="m")
            self.assertEqual(info["turn_from"], 2)
            self.assertEqual(MN.count_archived_turns(root, "s"), 2)

    def test_awareness_note_without_snippets(self):
        note = MN.format_recall_note([], archived_turns=7)
        self.assertIn("Note: 7 earlier turns", note)
        self.assertIn("don't have it in view", note)
        self.assertNotIn("Relevant bits", note)
        self.assertEqual(MN.format_recall_note([], archived_turns=0), "")

    def test_merged_note_and_guard_detect(self):
        snips = [{"turn": 1, "role": "user", "text": "codeword REDWOOD", "score": 1.0}]
        note = MN.format_recall_note(snips, archived_turns=4)
        self.assertTrue(note.startswith("Note: 4 earlier turns"))
        self.assertIn("Relevant bits from those notes:", note)
        self.assertIn("REDWOOD", note)
        self.assertTrue(MN.is_memory_guard_note(note))
        self.assertTrue(MN.is_memory_guard_note("Earlier in this conversation (from notes):\n- x"))
        self.assertFalse(MN.is_memory_guard_note("You are a helpful assistant."))


if __name__ == "__main__":
    unittest.main()
