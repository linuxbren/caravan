"""Unit tests for agent/memory_guard.py — no mlx required."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

import memory_guard as MG  # noqa: E402


QWEN = {
    "head_dim": 128,
    "hidden_size": 2048,
    "num_attention_heads": 32,
    "num_key_value_heads": 4,
    "num_hidden_layers": 48,
}


class KvEstimateTest(unittest.TestCase):
    def test_elems_per_token(self):
        # 4 kv heads * 128 dim * 2 (K+V) = 1024
        self.assertEqual(MG.kv_elems_per_token(QWEN), 1024)

    def test_bytes_half_layers_f16(self):
        # 24 layers * 1024 elems * 2 bytes = 49152 B/tok
        b = MG.bytes_per_token_for_layers(QWEN, 24, kv_bits=16)
        self.assertEqual(b, 24 * 1024 * 2)

    def test_estimate_scales(self):
        g1 = MG.estimate_kv_gb(QWEN, 1000, 24, kv_bits=16)
        g2 = MG.estimate_kv_gb(QWEN, 2000, 24, kv_bits=16)
        self.assertAlmostEqual(g2, g1 * 2, places=6)


class TrimTest(unittest.TestCase):
    def test_drops_oldest_pair(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
        ]

        def count(ms):
            # 1 token per message for the fake
            return len(ms)

        out, n, dropped = MG.trim_messages_to_token_budget(msgs, budget_tokens=4, count_tokens=count)
        self.assertEqual(n, 2)  # dropped u1+a1
        self.assertEqual(out[0]["role"], "system")
        self.assertEqual(out[-1]["content"], "u3")
        self.assertLessEqual(len(out), 4)

    def test_keeps_final_user(self):
        msgs = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "ans"},
            {"role": "user", "content": "new"},
        ]
        out, n, dropped = MG.trim_messages_to_token_budget(
            msgs, budget_tokens=1, count_tokens=lambda ms: len(ms))
        self.assertEqual(out[-1]["content"], "new")
        self.assertGreaterEqual(n, 1)
        self.assertTrue(dropped)


class PlanTest(unittest.TestCase):
    def test_trims_when_headroom_low(self):
        msgs = [
            {"role": "user", "content": "turn1 " * 50},
            {"role": "assistant", "content": "ans1 " * 50},
            {"role": "user", "content": "turn2 " * 50},
            {"role": "assistant", "content": "ans2 " * 50},
            {"role": "user", "content": "newest"},
        ]

        def count(ms):
            return sum(len(m["content"].split()) for m in ms)

        # ~48 KiB/tok * 24 layers → 0.002 GB holds only ~40 tokens; force trim.
        with mock.patch.dict(os.environ, {"CARAVAN_MEMORY_FORCE_HEADROOM_GB": "0.002"}):
            r = MG.plan(
                msgs, cfg=QWEN, n_layers=24, max_tokens=8,
                count_tokens=count, kv_bits=16, safety_gb=0.0,
            )
        self.assertGreater(r["trimmed_turns"], 0)
        self.assertEqual(r["messages"][-1]["content"], "newest")
        self.assertLessEqual(r["prompt_tokens"], r["budget_tokens"] + 1)

    def test_error_when_impossible(self):
        msgs = [{"role": "user", "content": "x" * 100}]

        def count(ms):
            return 100000  # huge

        with mock.patch.dict(os.environ, {"CARAVAN_MEMORY_FORCE_HEADROOM_GB": "0.001"}):
            r = MG.plan(
                msgs, cfg=QWEN, n_layers=24, max_tokens=4096,
                count_tokens=count, kv_bits=16, safety_gb=0.0,
            )
        self.assertFalse(r["ok"])
        self.assertIsNotNone(r["error"])


if __name__ == "__main__":
    unittest.main()
