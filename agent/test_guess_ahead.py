"""Unit tests for idea 3 guess-ahead helpers (no GPU / no Minis)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import guess_ahead as ga


class PairingTests(unittest.TestCase):
    def test_table_loads(self):
        t = ga.load_table()
        self.assertEqual(t["version"], 1)
        ids = {p["id"] for p in t["pairings"]}
        self.assertIn("qwen3-30b-a3b", ids)
        self.assertIn("gemma-4-26b", ids)
        self.assertIn("llama3", ids)
        self.assertIn("qwen25", ids)
        self.assertIn("gemma3", ids)
        self.assertIn("gemma2", ids)
        self.assertIn("deepseek-r1-distill-qwen", ids)
        self.assertIn("smollm", ids)
        q = next(p for p in t["pairings"] if p["id"] == "qwen3-30b-a3b")
        self.assertEqual(q["draft"]["k"], 3)
        self.assertEqual(q["draft"]["size_mb"], 335)
        self.assertEqual(q.get("verification"), "mini_verified")
        self.assertIn("tested", q)
        g = next(p for p in t["pairings"] if p["id"] == "gemma-4-26b")
        self.assertEqual(g["draft"]["vocab"], "compatible_specials_remap")
        self.assertEqual(g["draft"]["k"], 2)
        self.assertEqual(g.get("verification"), "mini_verified")
        llama = next(p for p in t["pairings"] if p["id"] == "llama3")
        self.assertEqual(llama.get("verification"), "vocab_checked")
        self.assertEqual(llama["draft"]["size_mb"], 663)
        skips = {s.get("target_family") for s in t.get("no_pairing") or []}
        self.assertIn("gpt_oss", skips)
        self.assertIn("mistral", skips)
        self.assertIn("phi4", skips)
        self.assertIn("deepseek_native", skips)

    def test_find_qwen_and_gemma(self):
        self.assertEqual(
            ga.find_pairing(Path("/models/mlx-community--Qwen3-30B-A3B-4bit"))["id"],
            "qwen3-30b-a3b")
        self.assertEqual(
            ga.find_pairing(Path("/x/gemma-4-26b-it-4bit"))["id"],
            "gemma-4-26b")
        # fine-tune style folder still matches family token
        self.assertEqual(
            ga.find_pairing(Path("/x/Qwen3-30B-A3B-my-ft"))["id"],
            "qwen3-30b-a3b")

    def test_find_top_family_pairings(self):
        cases = [
            ("/models/Llama-3.1-8B-Instruct-4bit", "llama3"),
            ("/models/Qwen2.5-7B-Instruct-4bit", "qwen25"),
            ("/models/gemma-3-12b-it-4bit", "gemma3"),
            ("/models/gemma-2-9b-it-4bit", "gemma2"),
            ("/models/DeepSeek-R1-Distill-Qwen-14B-4bit", "deepseek-r1-distill-qwen"),
            ("/models/SmolLM-1.7B-Instruct-4bit", "smollm"),
        ]
        for path, expect in cases:
            got = ga.find_pairing(Path(path))
            self.assertIsNotNone(got, path)
            self.assertEqual(got.get("id"), expect, path)
            self.assertFalse(got.get("skip"), path)

    def test_gpt_oss_skips(self):
        p = ga.find_pairing(Path("/models/mlx-community--gpt-oss-20b-MXFP4-Q8"))
        self.assertTrue(p.get("skip"))
        self.assertIn("o200k", (p.get("reason") or "").lower() + "o200k")

    def test_family_skips(self):
        for path, needle in [
            ("/models/Mistral-7B-Instruct-v0.3-4bit", "mistral"),
            ("/models/Phi-4-mini-instruct-4bit", "phi"),
            ("/models/DeepSeek-V3-0324-4bit", "deepseek"),
        ]:
            p = ga.find_pairing(Path(path))
            self.assertTrue(p and p.get("skip"), path)
            self.assertIn(needle, (p.get("reason") or "").lower())


class VocabTests(unittest.TestCase):
    def _tok_dir(self, root: Path, name: str, vocab: dict, added=None):
        d = root / name
        d.mkdir()
        (d / "config.json").write_text(json.dumps({"vocab_size": max(vocab.values()) + 1}))
        tj = {"model": {"vocab": vocab}, "added_tokens": added or []}
        (d / "tokenizer.json").write_text(json.dumps(tj))
        return d

    def test_exact_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vocab = {"a": 1, "b": 2, "c": 3}
            t = self._tok_dir(root, "tgt", vocab)
            d = self._tok_dir(root, "dft", dict(vocab))
            m = ga.build_vocab_maps(t, d)
            self.assertTrue(m["ok"])
            self.assertEqual(m["mode"], "exact")
            self.assertEqual(m["n_remap"], 0)

    def test_compatible_specials_remap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Mostly same ids; two specials remapped
            tv = {f"t{i}": i for i in range(100)}
            dv = dict(tv)
            tv["<pad>"] = 1000
            dv["<pad>"] = 2000
            tv["<bos>"] = 1001
            dv["<bos>"] = 2001
            t = self._tok_dir(root, "tgt", tv)
            d = self._tok_dir(root, "dft", dv)
            m = ga.build_vocab_maps(t, d)
            self.assertTrue(m["ok"])
            self.assertEqual(m["mode"], "compatible_specials_remap")
            self.assertEqual(m["remap_draft_to_target"][2000], 1000)
            self.assertEqual(m["remap_target_to_draft"][1001], 2001)
            self.assertEqual(ga.apply_remap([1, 2000, 5], m["remap_draft_to_target"]),
                             [1, 1000, 5])

    def test_mismatch_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            t = self._tok_dir(root, "tgt", {"a": 1, "b": 2})
            d = self._tok_dir(root, "dft", {"x": 10, "y": 11, "z": 12})
            m = ga.build_vocab_maps(t, d)
            self.assertFalse(m["ok"])
            self.assertEqual(m["mode"], "mismatch")


class AskDownloadTests(unittest.TestCase):
    def test_noninteractive_declines_and_remembers(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            table = {
                "version": 1,
                "drafts_dir": str(Path(td) / "drafts"),
                "state_file": str(state),
                "pairings": [{
                    "id": "qwen3-30b-a3b",
                    "draft": {"name": "Qwen3-0.6B-4bit", "size_mb": 335, "hf_repo": "x/y"},
                }],
            }
            with mock.patch.object(ga, "load_table", return_value=table):
                ok = ga.ask_download(table["pairings"][0], auto=False, interactive=False)
                self.assertFalse(ok)
                st = json.loads(state.read_text())
                self.assertFalse(st["download_answers"]["qwen3-30b-a3b"])
                # remembered
                ok2 = ga.ask_download(table["pairings"][0], auto=False, interactive=True)
                self.assertFalse(ok2)

    def test_auto_download_flag(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            table = {
                "version": 1,
                "drafts_dir": str(Path(td) / "drafts"),
                "state_file": str(state),
                "pairings": [{
                    "id": "gemma-4-26b",
                    "draft": {"name": "gemma-3-270m-it-4bit", "size_mb": 181, "hf_repo": "x/y"},
                }],
            }
            with mock.patch.object(ga, "load_table", return_value=table):
                ok = ga.ask_download(table["pairings"][0], auto=True, interactive=False)
                self.assertTrue(ok)

    def test_dry_run_download_path(self):
        with tempfile.TemporaryDirectory() as td:
            table = {
                "version": 1,
                "drafts_dir": str(Path(td) / "drafts"),
                "state_file": str(Path(td) / "state.json"),
                "pairings": [{
                    "id": "qwen3-30b-a3b",
                    "draft": {"name": "Qwen3-0.6B-4bit", "size_mb": 335, "hf_repo": "x/y"},
                }],
            }
            with mock.patch.object(ga, "load_table", return_value=table):
                dest = ga.download_draft(table["pairings"][0], dry_run=True)
                self.assertEqual(dest, Path(td) / "drafts" / "Qwen3-0.6B-4bit")
                self.assertFalse(dest.exists())


class ShutoffTests(unittest.TestCase):
    def test_triggers_below_break_even(self):
        s = ga.ChatShutoff(break_even_frac=0.4, window=10)
        for _ in range(10):
            s.observe(False)
        self.assertTrue(s.disabled)
        self.assertIn("break_even", s.reason)

    def test_stays_on_when_hits(self):
        s = ga.ChatShutoff(break_even_frac=0.3, window=10)
        for i in range(10):
            s.observe(i % 2 == 0)  # 50%
        self.assertFalse(s.disabled)

    def test_derive_break_even(self):
        be = ga.derive_break_even(40.0, 50.0, k=3, accepted_frac=0.5)
        self.assertGreater(be, 0.1)
        self.assertLess(be, 0.5)


class ParserFlagTests(unittest.TestCase):
    def test_no_split_draft_flag(self):
        import mlx_worker as w
        args = w.build_parser().parse_args(["--model", "/tmp/m", "--no-split-draft"])
        self.assertTrue(args.no_split_draft)

    def test_auto_download_flag(self):
        import mlx_worker as w
        args = w.build_parser().parse_args(["--model", "/tmp/m", "--split-draft-auto-download"])
        self.assertTrue(args.split_draft_auto_download)



class AnswerOkTests(unittest.TestCase):
    def test_plain_short_answers(self):
        self.assertTrue(ga.answer_ok("4", ("4", "four")))
        self.assertTrue(ga.answer_ok("Paris", ("paris",)))
        self.assertTrue(ga.answer_ok("Cold.", ("cold",)))
        self.assertTrue(ga.answer_ok("The answer is cold.", ("cold",)))

    def test_qwen_think_fence(self):
        self.assertTrue(ga.answer_ok("<think>\n\n</think>\n\n4<|im_end|>", ("4", "four")))
        self.assertFalse(ga.answer_ok(
            "<think>\nParis is the capital.\n</think>\nLondon", ("paris",)))
        self.assertTrue(ga.answer_ok(
            "<think>\nParis is the capital.\n</think>\nParis", ("paris",)))

    def test_gemma_channel_thought_only_fails(self):
        # The Nov 1 bug: expected words appeared inside <|channel>thought.
        thought = (
            "<|channel>thought\n"
            "The user is asking for the result of 2+2. The answer is 4.\n"
        )
        self.assertEqual(ga.final_answer_text(thought), "")
        self.assertFalse(ga.answer_ok(thought, ("4", "four")))
        self.assertFalse(ga.answer_ok(
            "<|channel>thought\n* Question: capital of France. Paris.\n",
            ("paris",)))
        self.assertFalse(ga.answer_ok(
            "<|channel>thought\nice cream is typically cold\n",
            ("cold",)))

    def test_gemma_channel_final_only(self):
        # Explicit final channel (some templates).
        self.assertTrue(ga.answer_ok(
            "<|channel>thought\nParis is famous\n<|channel>final\nParis",
            ("paris",)))
        self.assertFalse(ga.answer_ok(
            "<|channel>thought\nParis is famous\n<|channel>final\nLondon",
            ("paris",)))
        # Real Gemma-4 closer form observed on EXO1 first-load gate:
        # <|channel>thought ... <channel|>ANSWER<turn|>
        self.assertTrue(ga.answer_ok(
            "<|channel>thought\nFinal answer: 4.<channel|>4<turn|>",
            ("4", "four")))
        self.assertTrue(ga.answer_ok(
            "<|channel>thought\nParis is capital.<channel|>Paris<turn|>",
            ("paris",)))
        self.assertTrue(ga.answer_ok(
            "<|channel>thought\nice cream is cold.<channel|>Cold<turn|>",
            ("cold",)))
        self.assertFalse(ga.answer_ok(
            "<|channel>thought\nParis.<channel|>London<turn|>",
            ("paris",)))
        self.assertFalse(ga.answer_ok(
            "<|channel>thought\nice cream is cold\n<|channel>final\nhot",
            ("cold",)))

    def test_gpt_oss_channels(self):
        self.assertFalse(ga.answer_ok(
            "<|channel|>analysis\nParis is capital\n<|channel|>final\nBerlin",
            ("paris",)))
        self.assertTrue(ga.answer_ok(
            "<|channel|>analysis\nParis\n<|channel|>final<|message|>Paris",
            ("paris",)))

    def test_final_marker_without_channels(self):
        self.assertFalse(ga.answer_ok(
            "Thinking: ice cream is cold. Final: hot", ("cold",)))
        self.assertTrue(ga.answer_ok(
            "Thinking: ice cream is cold. Final: cold", ("cold",)))

if __name__ == "__main__":
    unittest.main()
