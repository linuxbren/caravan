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

    def test_split_and_empty(self):
        s = w._timing_line({"split": {"stages": 2}, "completion_tokens": 0})
        self.assertIn("timing (split)", s)
        self.assertIn("write 0 tok at 0.00 tok/s", s)


if __name__ == "__main__":
    unittest.main()
