import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from verify_block import cache_plan
from native_mtp import validate_pair, head_path

class VerifyBlockTests(unittest.TestCase):
    def test_rejection_each_boundary(self):
        for k in range(1, 9):
            for accepted in range(k):
                p = cache_plan(k, accepted)
                self.assertEqual(k + 1 - p["target_trim"], accepted + 1)
                self.assertEqual(k - p["draft_trim"], accepted + 1)
                self.assertFalse(p["replay_last_draft"])
    def test_all_accepted_replays_last_draft(self):
        for k in range(1, 9):
            self.assertEqual(cache_plan(k, k), dict(target_trim=0, draft_trim=0, replay_last_draft=True))
    def test_stops_inside_draft_always_rewind(self):
        for k in range(1, 9):
            for accepted in range(1, k+1):
                p = cache_plan(k, accepted, stopped_in_draft=True)
                self.assertEqual(k+1-p["target_trim"], accepted)
                self.assertEqual(k-p["draft_trim"], accepted)
                self.assertFalse(p["replay_last_draft"])
    def test_no_draft(self):
        self.assertEqual(cache_plan(0,0),dict(target_trim=0,draft_trim=0,replay_last_draft=False))
    def test_invalid(self):
        for args in [(-1,0),(2,3),(1,-1)]:
            with self.assertRaises(ValueError): cache_plan(*args)

class NativePairTests(unittest.TestCase):
    def test_matching_and_mismatch(self):
        c = dict(hidden_size=2560,vocab_size=248320,num_hidden_layers=32,intermediate_size=9216)
        h = dict(text_config=c,target_repo="Orvena/Orvena-4B-MLX-4bit")
        self.assertEqual(validate_pair(dict(model_type="qwen3_5",text_config=c),h),c)
        with self.assertRaises(ValueError):
            validate_pair(dict(model_type="qwen3",text_config=c),h)
        with self.assertRaises(ValueError):
            validate_pair(dict(model_type="qwen3_5",text_config={**c,"hidden_size":2048}),h)
    def test_absent_head(self):
        self.assertIsNone(head_path("/no/such/checkpoint"))
