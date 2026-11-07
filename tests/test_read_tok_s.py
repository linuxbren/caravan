import unittest
import web_timing


class ReadTokS(unittest.TestCase):
    def test_prefill_preferred(self):
        s = web_timing.reply_stats({"prompt_tokens": 400, "completion_tokens": 50,
                                    "caravan": {"prefill_s": 1.0, "ttft_s": 2.0, "total_s": 3.0}})
        self.assertEqual(s["read_tok_s"], 400.0)

    def test_falls_back_to_ttft(self):
        s = web_timing.reply_stats({"prompt_tokens": 400, "completion_tokens": 50,
                                    "caravan": {"ttft_s": 2.0, "total_s": 3.0}})
        self.assertEqual(s["read_tok_s"], 200.0)


if __name__ == "__main__":
    unittest.main()
