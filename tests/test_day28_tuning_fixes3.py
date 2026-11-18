"""Day 28 tuning fix 3: a Guess-ahead helper win on a GGUF split is kept when a
whole long-prompt reply is not slower, and Self-tuning and Auto-tune agree."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "proxy", "agent"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
import gguf_tune as T  # noqa: E402
import gguf_self_tune as ST  # noqa: E402


def specs(write, total, long_read=None):
    s = {"write_tok_s": write, "short_write_tok_s": write, "total_s": total,
         "short_total_s": total, "read_tok_s": 300.0, "ttft_s": 0.3}
    if long_read is not None:
        s["long_read_tok_s"] = long_read
    return s


class LongReplyGuardTest(unittest.TestCase):
    def test_split_llama8b_helper_win_is_kept(self):
        # Round 2 on 2 Macs: write 19.29 -> 22.69, long read 310 -> 260 (-16%).
        off = specs(19.29, 9.95, long_read=310.0)
        on = specs(22.69, 8.46, long_read=260.0)
        v = T.spec_verdict(on, off)
        self.assertTrue(v["won"], v)
        self.assertTrue(T.trial_won("guess_ahead", on, off))

    def test_big_read_drop_is_always_rejected(self):
        off = specs(19.0, 10.0, long_read=400.0)
        on = specs(30.0, 6.4, long_read=200.0)      # -50%
        v = T.spec_verdict(on, off)
        self.assertFalse(v["won"])
        self.assertIn("guard", v["why"])

    def test_moderate_drop_with_slower_long_reply_is_rejected(self):
        off = specs(20.0, 9.6, long_read=420.0)
        on = specs(20.8, 9.2, long_read=330.0)      # -21% read, write +4%
        v = T.spec_verdict(on, off)
        self.assertFalse(v["won"])
        self.assertIn("long reply", v["why"])

    def test_qwen30b_helper_that_writes_slower_still_loses(self):
        off = specs(34.0, 5.6, long_read=606.0)
        on = specs(22.1, 8.7, long_read=493.0)
        self.assertFalse(T.trial_won("guess_ahead", on, off))

    def test_self_tune_and_auto_tune_use_the_same_verdict(self):
        import inspect
        src = inspect.getsource(ST)
        self.assertIn("T.trial_won(name, chal, base)", src)

    def test_noise_level_difference_is_not_a_win(self):
        off = specs(34.5, 5.5, long_read=600.0)
        on = specs(33.5, 5.7, long_read=598.0)
        self.assertFalse(T.trial_won("guess_ahead", on, off))
        self.assertFalse(T.trial_won("prompt_lookup", on, off))


if __name__ == "__main__":
    unittest.main()
