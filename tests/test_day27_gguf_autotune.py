"""Day 27: GGUF Auto-tune tries Guess-ahead only with a helper on disk."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))

import gguf_split as G  # noqa: E402
import gguf_tune as GT  # noqa: E402

HTML = (ROOT / "proxy/web/index.html").read_text()


def _touch(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(b"GGUF")
        f.truncate(size)
    return path


class Schedule(unittest.TestCase):
    def test_no_helper_no_step(self):
        names = [i["name"] for i in G.gguf_schedule({}, [])]
        self.assertNotIn("guess_ahead", names)
        self.assertEqual(names[-1], "prompt_lookup")
        names = [i["name"] for i in G.gguf_schedule({}, [], draft_path="/nope.gguf")]
        self.assertNotIn("guess_ahead", names)

    def test_helper_on_disk_adds_last_step(self):
        with tempfile.TemporaryDirectory() as td:
            d = _touch(Path(td) / "Qwen2.5-0.5B.gguf", 80_000_000)
            items = G.gguf_schedule({}, [], draft_path=str(d))
            self.assertEqual(items[-1]["name"], "guess_ahead")
            self.assertEqual((items[-1]["incumbent"], items[-1]["challenger"]), ("off", "on"))
            self.assertIsNone(items[-1]["skip"])
            self.assertEqual(items[-1]["draft_path"], str(d.resolve()))

    def test_gates(self):
        with tempfile.TemporaryDirectory() as td:
            d = str(_touch(Path(td) / "Qwen2.5-0.5B.gguf", 80_000_000))
            self.assertEqual(G.gguf_schedule({}, [], n_slots=2, draft_path=d)[-1]["skip"], "two chats")
            self.assertEqual(G.gguf_schedule({}, [], pinned={"guess_ahead"}, draft_path=d)[-1]["skip"], "pinned")
            self.assertEqual(G.gguf_schedule({}, ["guess_ahead=on"], draft_path=d)[-1]["skip"], "already lost")


class Tuner(unittest.TestCase):
    def _run(self, on_speed):
        with tempfile.TemporaryDirectory() as td:
            draft = str(_touch(Path(td) / "Qwen2.5-0.5B.gguf", 80_000_000))
            tunes = []

            def restart(t):
                tunes.append(dict(t))

            def measure():
                t = tunes[-1]
                w = on_speed if t.get("guess_ahead") == "on" else 20.0
                return {"write_tok_s": w, "read_tok_s": 200.0, "total_s": 10.0 * 20.0 / w}
            store = Path(td) / "tuned.json"
            tuner = GT.GgufTuner(Path(td) / "Qwen2.5-7B.gguf", 1, restart=restart,
                                 measure=measure, store_path=store, log=lambda m: None,
                                 schedule_kw={"draft_path": draft})
            res = tuner.run()
            return res, tunes, draft

    def test_keeps_helper_only_when_faster(self):
        res, tunes, draft = self._run(on_speed=30.0)
        self.assertEqual(res["best"]["guess_ahead"], "on")
        self.assertEqual(res["best"]["draft_path"], str(Path(draft).resolve()))
        self.assertEqual(tunes[-1]["guess_ahead"], "on")

    def test_rejects_a_slower_helper(self):
        res, tunes, _ = self._run(on_speed=18.0)
        self.assertEqual(res["best"]["guess_ahead"], "off")
        self.assertNotIn("draft_path", res["best"])
        self.assertNotIn("draft_path", tunes[-1])
        # The "off" arm never carries a helper path.
        self.assertTrue(all("draft_path" not in t for t in tunes if t.get("guess_ahead") == "off"))

    def test_rejects_within_margin(self):
        res, _, _ = self._run(on_speed=20.3)
        self.assertEqual(res["best"]["guess_ahead"], "off")


class Chip(unittest.TestCase):
    def test_gguf_prompt_lookup_chip_says_on(self):
        self.assertIn('a.backend === "llama" ? (a.prompt_lookup.enabled ? "on" : "off")', HTML)


if __name__ == "__main__":
    unittest.main()
