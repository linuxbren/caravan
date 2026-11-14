"""caravan bench --from-averages: no empty bars, and the last bench run per pair."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))
import caravan_bench as B  # noqa: E402
import web_speed as S  # noqa: E402
from caravan_chart import render_chart  # noqa: E402

G_ROWS = [
    {"label": "Short prompts (5)", "specs": {"read_tok_s": 182, "write_tok_s": 22.2, "ttft_s": 0.28}},
    {"label": "Long prompts (~1k tok) (2)", "size": 1024, "specs": {"read_tok_s": 239, "write_tok_s": 21.5, "ttft_s": 5.3}},
]
M_ROWS = [
    {"label": "Short prompts (5)", "specs": {"read_tok_s": 300, "write_tok_s": 30.1, "ttft_s": 0.2}},
]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.store = self.dir / "speed.json"
        self.last = self.dir / "bench_last.json"

    def run_avg(self, **kw):
        return "\n".join(B.run_from_averages(
            "gguf/qwen", "mlx/qwen", gguf_name="Qwen (GGUF)", mlx_name="Qwen (MLX)",
            store=self.store, last_store=self.last, ascii=True, **kw,
        ))


class NoEmptyBars(Base):
    def test_missing_gguf_side_gets_a_plain_line_and_no_gguf_bars(self):
        S.record("mlx/qwen", {}, write_tok_s=28.0, ttft_s=0.25, prompt_tokens=100,
                 read_tok_s=220, completion_tokens=30, total_s=1.1, path=self.store)
        text = self.run_avg()
        self.assertIn("No saved numbers for the GGUF model yet - chat with it a bit, or run the bench.", text)
        self.assertNotIn("Qwen (GGUF)", text)
        self.assertFalse([l for l in text.splitlines() if "GGUF" in l and "No saved" not in l])
        self.assertIn("MLX", text)
        self.assertIn("220", text)
        self.assertIn("MLX: Saved chat average", text)

    def test_nothing_saved_prints_both_lines_and_no_chart(self):
        text = self.run_avg()
        self.assertIn("No saved numbers for the GGUF model yet", text)
        self.assertIn("No saved numbers for the MLX model yet", text)
        self.assertNotIn("tok/s", text)

    def test_chart_leaves_out_a_side_with_no_rows(self):
        out = render_chart([], M_ROWS, gguf_name="G", mlx_name="M", ascii=True)
        self.assertNotIn("GGUF", out)
        self.assertIn("MLX", out)
        both = render_chart(G_ROWS, M_ROWS, gguf_name="G", mlx_name="M", ascii=True)
        self.assertIn("GGUF", both)
        self.assertIn("MLX", both)


class LastBench(Base):
    def test_save_and_prefer_last_bench_over_chat_averages(self):
        S.record("gguf/qwen", {}, write_tok_s=10.0, ttft_s=1.0, prompt_tokens=100,
                 read_tok_s=111, completion_tokens=30, total_s=3.0, path=self.store)
        B.save_last_bench("gguf/qwen", "mlx/qwen", G_ROWS, M_ROWS, path=self.last, now=1789000000)
        text = self.run_avg()
        self.assertIn("GGUF: Last bench", text)
        self.assertIn("MLX: Last bench", text)
        self.assertIn("182", text)
        self.assertIn("239", text)
        self.assertNotIn("111", text)  # chat average not used when a bench run exists

    def test_one_side_falls_back_to_saved(self):
        S.record("mlx/qwen", {}, write_tok_s=28.0, ttft_s=0.25, prompt_tokens=100,
                 read_tok_s=220, completion_tokens=30, total_s=1.1, path=self.store)
        B.save_last_bench("gguf/qwen", "mlx/qwen", G_ROWS, [], path=self.last)
        text = self.run_avg()
        self.assertIn("GGUF: Last bench", text)
        self.assertIn("MLX: Saved chat average", text)
        self.assertNotIn("No saved numbers", text)

    def test_empty_side_keeps_its_previous_numbers(self):
        B.save_last_bench("gguf/qwen", "mlx/qwen", G_ROWS, M_ROWS, path=self.last)
        B.save_last_bench("gguf/qwen", "mlx/qwen", [], [{"label": "x", "skipped": True}], path=self.last)
        entry = B.load_last_bench("gguf/qwen", "mlx/qwen", path=self.last)
        self.assertEqual(len(entry["gguf_rows"]), 2)
        self.assertEqual(len(entry["mlx_rows"]), 1)
        self.assertEqual(B.load_last_bench("gguf/other", "mlx/qwen", path=self.last), {})

    def test_live_main_saves_the_result(self):
        result = {"gguf_rows": G_ROWS, "mlx_rows": M_ROWS, "lines": [], "notes": [], "error": None}
        with mock.patch.object(B, "LAST_BENCH_STORE", self.last), \
             mock.patch.object(B, "run_live", return_value=result), \
             mock.patch("sys.stdout", io.StringIO()):
            rc = B.main(["--gguf", "gguf/qwen", "--mlx", "mlx/qwen", "--yes", "--quiet"])
        self.assertEqual(rc, 0)
        entry = B.load_last_bench("gguf/qwen", "mlx/qwen", path=self.last)
        self.assertEqual(len(entry["gguf_rows"]), 2)

    def test_store_lives_with_the_chat_averages(self):
        self.assertIn(".caravan", str(B.SPEED_STORE))
        self.assertEqual(Path(B.SPEED_STORE).parent.name, ".caravan")

    def test_docs_mention_last_bench(self):
        text = (ROOT / "docs" / "BENCHMARKS.md").read_text()
        self.assertIn("Last bench", text)
        self.assertIn("No saved numbers", text)


if __name__ == "__main__":
    unittest.main()
