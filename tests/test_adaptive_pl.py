"""Day 12 idea 2: adaptive prompt-lookup gate."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

import adaptive_pl as AP  # noqa: E402


class PromptTailOverlap(unittest.TestCase):
    def test_echo_prompt_high_overlap(self):
        # Simulate "repeat this paragraph" — tail copies earlier text
        base = list(range(100, 164))  # 64 tokens
        prompt = base + [1, 2, 3] + base  # echo
        o = AP.prompt_tail_overlap(prompt, window=64)
        self.assertGreaterEqual(o, 0.5)

    def test_unique_prompt_low_overlap(self):
        prompt = list(range(200))
        o = AP.prompt_tail_overlap(prompt, window=64)
        self.assertLess(o, 0.15)

    def test_short_prompt(self):
        self.assertEqual(AP.prompt_tail_overlap([1, 2, 3]), 0.0)


class AdaptivePLGate(unittest.TestCase):
    def test_force_on_from_overlap(self):
        g = AP.AdaptivePLGate(overlap_on=0.50)
        base = list(range(100, 164))
        g.begin_request(base + base)
        self.assertTrue(g._force_on)
        self.assertTrue(g.should_try_pl())

    def test_cold_start_tries_once_pl_only(self):
        g = AP.AdaptivePLGate()
        g.begin_request(list(range(50)))  # unique, low overlap
        self.assertFalse(g._force_on)
        self.assertTrue(g.should_try_pl(has_draft=False))  # probe when no draft

    def test_cold_start_skips_when_draft_present(self):
        g = AP.AdaptivePLGate()
        g.begin_request(list(range(50)))
        self.assertFalse(g._force_on)
        self.assertFalse(g.should_try_pl(has_draft=True))

    def test_begin_request_clears_poison(self):
        g = AP.AdaptivePLGate(accept_off=0.25, window=8)
        g.begin_request(list(range(50)))
        for _ in range(8):
            g.observe_pl_round(proposed=4, accepted=0)
        self.assertFalse(g.should_try_pl(has_draft=False))
        # New request must not inherit the poison.
        g.begin_request(list(range(50)))
        self.assertTrue(g.should_try_pl(has_draft=False))
        self.assertFalse(g.should_try_pl(has_draft=True))

    def test_note_context_flips_force_on_mid_turn(self):
        g = AP.AdaptivePLGate(overlap_on=0.50)
        base = list(range(100, 164))
        g.begin_request(base + [1, 2, 3])  # no echo yet
        self.assertFalse(g._force_on)
        self.assertFalse(g.should_try_pl(has_draft=True))
        # Mid-generation: first copy appears, then echo grows into tail.
        g.note_context(base + [1, 2, 3] + base)
        self.assertTrue(g._force_on)
        self.assertTrue(g.should_try_pl(has_draft=True))

    def test_low_accept_disables(self):
        g = AP.AdaptivePLGate(accept_off=0.25, accept_on=0.5, window=8)
        g.begin_request(list(range(50)))
        for _ in range(8):
            g.observe_pl_round(proposed=4, accepted=0)
        self.assertFalse(g.should_try_pl(has_draft=False))

    def test_high_accept_enables(self):
        g = AP.AdaptivePLGate(accept_off=0.25, accept_on=0.5, window=8)
        g.begin_request(list(range(50)))
        for _ in range(8):
            g.observe_pl_round(proposed=4, accepted=3)
        self.assertTrue(g.should_try_pl(has_draft=False))
        self.assertTrue(g.should_try_pl(has_draft=True))
        self.assertGreaterEqual(g.recent_accept_rate(), 0.5)

    def test_low_accept_overrides_force_on(self):
        g = AP.AdaptivePLGate(overlap_on=0.50, accept_off=0.25, window=8)
        base = list(range(100, 164))
        g.begin_request(base + base)
        self.assertTrue(g._force_on)
        for _ in range(8):
            g.observe_pl_round(proposed=4, accepted=0)
        self.assertFalse(g.should_try_pl(has_draft=True))

    def test_high_overlap_recovers_from_template_suffix_miss(self):
        g = AP.AdaptivePLGate(window=4)
        base = list(range(100, 164))
        g.begin_request(base + base)
        g.observe_pl_round(proposed=4, accepted=0)
        self.assertTrue(g.should_try_pl())
        g.observe_pl_round(proposed=4, accepted=4)
        self.assertTrue(g.should_try_pl())
        for _ in range(4):g.observe_pl_round(proposed=4, accepted=0)
        self.assertFalse(g.should_try_pl())

    def test_low_overlap_still_stops_after_one_bad_probe(self):
        g = AP.AdaptivePLGate(window=4)
        g.begin_request(list(range(100)))
        g.observe_pl_round(proposed=4, accepted=0)
        self.assertFalse(g.should_try_pl())

    def test_snapshot(self):
        g = AP.AdaptivePLGate()
        g.begin_request(list(range(10)))
        s = g.snapshot()
        self.assertIn("overlap", s)
        self.assertIn("force_on", s)


if __name__ == "__main__":
    unittest.main()


class TokenAcceptanceReadout(unittest.TestCase):
    def test_token_rate_is_not_round_success_fraction_and_resets_per_request(self):
        from adaptive_pl import AdaptivePLGate
        g=AdaptivePLGate();g.begin_request([1,2,3,4,5,6])
        g.observe_pl_round(4,3);g.observe_pl_round(8,1)
        s=g.snapshot();self.assertEqual(s["proposed_tokens"],12);self.assertEqual(s["accepted_tokens"],4);self.assertAlmostEqual(s["token_acceptance_rate"],.3333)
        self.assertNotEqual(s["recent_accept_rate"],s["token_acceptance_rate"])
        g.begin_request([1,2,3]);self.assertEqual(g.snapshot()["accepted_tokens"],0);self.assertIsNone(g.snapshot()["token_acceptance_rate"])
