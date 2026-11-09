import unittest
from agent import mlx_worker as w


class TimingLineTest(unittest.TestCase):
    def test_single(self):
        s = w._timing_line({"prompt_tokens": 1000, "cached_tokens": 800, "completion_tokens": 101,
                            "prefill_s": 0.5, "ttft_s": 0.5, "total_s": 10.5})
        self.assertIn("timing (single)", s)
        self.assertIn("read 1000 tok (800 cached) at 400.0 tok/s", s)
        self.assertIn("write 101 tok at 10.00 tok/s", s)
        self.assertIn("first token 0.50 s, total 10.50 s", s)

    def assert_native_ui(self, info):
        from web_timing import reply_stats
        rates = w._timing_rates(info)
        usage = dict(info, caravan=dict(info, **rates))
        stats = reply_stats(usage)
        self.assertEqual(stats["read_tok_s"], rates["read_tok_s"])
        self.assertEqual(stats["write_tok_s"], rates["write_tok_s"])
        self.assertIn(f"at {stats['write_tok_s']:.2f} tok/s", w._timing_line(info))
        return stats

    def test_native_ui_short_reboot_reply(self):
        stats = self.assert_native_ui(dict(prompt_tokens=26,cached_tokens=0,completion_tokens=6,prefill_s=.521,ttft_s=.801,total_s=1.722))
        self.assertEqual(stats["write_tok_s"],5.43)

    def test_native_ui_cached_read_is_only_new_tokens(self):
        stats = self.assert_native_ui(dict(prompt_tokens=1000,cached_tokens=800,completion_tokens=101,prefill_s=.5,ttft_s=.5,total_s=10.5))
        self.assertEqual(stats["read_tok_s"],400)

    def test_native_ui_one_token_has_no_decode_interval(self):
        stats = self.assert_native_ui(dict(prompt_tokens=10,completion_tokens=1,prefill_s=.5,ttft_s=.7,total_s=.9))
        self.assertEqual(stats["write_tok_s"],0)

    def test_split_and_empty(self):
        s = w._timing_line({"split": {"stages": 2}, "completion_tokens": 0})
        self.assertIn("timing (split)", s)
        self.assertIn("write 0 tok at 0.00 tok/s", s)


if __name__ == "__main__":
    unittest.main()
