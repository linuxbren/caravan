"""Day 33 ROADMAP #2: Auto-tune weighs first-token time with Guess-ahead.

A helper that also reads the prompt can delay the first word on a long
prompt by about 10%. These tests check that Auto-tune keeps that helper
only when write speed pays back the wait, that missing first-token data
falls back cleanly, and that GGUF and MLX Auto-tune share the verdict.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "proxy", "agent", "tests"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

import gguf_tune as T  # noqa: E402
import web_optimize as WO  # noqa: E402
from i18n_check import english_source  # noqa: E402


def specs(write, total, *, long_ttft=None, long_read=None, long_total=None,
          ttft=0.3, read=300.0, edit=None, long_prompt_tokens=None):
    s = {"write_tok_s": write, "short_write_tok_s": write, "total_s": total,
         "short_total_s": total, "read_tok_s": read, "ttft_s": ttft}
    if long_ttft is not None:
        s["long_ttft_s"] = long_ttft
    if long_read is not None:
        s["long_read_tok_s"] = long_read
    if long_total is not None:
        s["long_total_s"] = long_total
    if long_prompt_tokens is not None:
        s["long_prompt_tokens"] = long_prompt_tokens
    if edit is not None:
        s["edit_write_tok_s"] = edit
    return s


def _scores(combined, specs_dict=None, garbled=False, quality_fail=False):
    out = WO._Scores([combined])
    if specs_dict is not None:
        out.specs = specs_dict
    if garbled:
        out.garbled = True
    if quality_fail:
        out.quality_fail = True
    return out


class TinyWriteLossTest(unittest.TestCase):
    def test_tiny_write_boost_loses_to_slower_first_word(self):
        # +5% write, +10% long-prompt first word: the reply is slower.
        off = specs(22.0, 8.7, long_ttft=11.4)
        on = specs(23.1, 8.3, long_ttft=12.54)
        self.assertTrue(T.chat_score(on) > T.chat_score(off) * 1.03)
        v = T.spec_verdict(on, off)
        self.assertFalse(v["won"], v)
        self.assertIn("first word", v["why"])
        self.assertFalse(T.trial_won("guess_ahead", on, off))
        self.assertFalse(T.trial_won("prompt_lookup", on, off))

    def test_real_write_boost_pays_back_first_word_delay(self):
        off = specs(22.0, 8.7, long_ttft=11.4)
        on = specs(33.0, 5.8, long_ttft=12.54)  # +50% write, +10% TTFT
        v = T.spec_verdict(on, off)
        self.assertTrue(v["won"], v)
        self.assertTrue(T.trial_won("guess_ahead", on, off))

    def test_equal_write_with_slower_first_word_loses(self):
        off = specs(22.0, 8.7, long_ttft=11.4)
        on = specs(22.0, 8.7, long_ttft=12.54)
        v = T.spec_verdict(on, off)
        self.assertFalse(v["won"], v)
        self.assertIn("first word", v["why"])
        self.assertFalse(T.trial_won("guess_ahead", on, off))


class MissingTtftFallbackTest(unittest.TestCase):
    def test_missing_ttft_keeps_chat_only_verdict(self):
        off = specs(22.0, 8.7)
        on = specs(23.1, 8.3)  # +5% write, no long first-word evidence
        self.assertNotIn("long_ttft_s", T.as_specs(off))
        self.assertTrue(T.trial_won("guess_ahead", on, off))

    def test_zero_ttft_is_treated_as_missing(self):
        off = specs(22.0, 8.7, long_ttft=0)
        on = specs(23.1, 8.3, long_ttft=0)
        self.assertIsNone(T.long_reply_s(T.as_specs(on)))
        self.assertTrue(T.trial_won("guess_ahead", on, off))

    def test_old_saved_profile_without_ttft_fields_still_loads(self):
        saved = {"write_tok_s": 21.0, "total_s": 9.0, "ttft_s": 0.3,
                 "read_tok_s": 300.0, "short_write_tok_s": 21.0,
                 "short_total_s": 9.0}
        out = T.as_specs(saved)
        self.assertEqual(out["write_tok_s"], 21.0)
        self.assertNotIn("long_ttft_s", out)
        self.assertFalse(T.trial_won("guess_ahead", saved, saved))

    def test_as_specs_keeps_new_long_fields_and_drops_junk(self):
        out = T.as_specs({"write_tok_s": 1, "long_ttft_s": 11.4,
                          "long_total_s": 20.1, "long_prompt_tokens": 2048,
                          "junk": 9})
        self.assertEqual(out["long_ttft_s"], 11.4)
        self.assertEqual(out["long_total_s"], 20.1)
        self.assertEqual(out["long_prompt_tokens"], 2048.0)
        self.assertNotIn("junk", out)

    def test_one_sided_ttft_does_not_mix_with_a_read_estimate(self):
        off = specs(22.0, 8.7, long_read=180.0)  # estimate only
        on = specs(23.1, 8.3, long_ttft=12.54, long_read=180.0)
        t_c, t_i = T.long_reply_pair(T.as_specs(on), T.as_specs(off))
        # Both have long_read, so the pair uses the read estimate, not a
        # mixed measured-TTFT vs estimate comparison.
        self.assertIsNotNone(t_c)
        self.assertIsNotNone(t_i)
        self.assertAlmostEqual(t_i, 2048 / 180.0 + 192 / 22.0, places=4)

    def test_measured_totals_are_preferred_when_both_sides_have_them(self):
        off = specs(22.0, 8.7, long_ttft=11.4, long_total=20.0)
        on = specs(23.1, 8.3, long_ttft=12.54, long_total=21.0)
        t_c, t_i = T.long_reply_pair(T.as_specs(on), T.as_specs(off))
        self.assertEqual((t_c, t_i), (21.0, 20.0))
        self.assertFalse(T.trial_won("guess_ahead", on, off))


class MeasurementPathTest(unittest.TestCase):
    def test_ttft_from_caravan_usage(self):
        self.assertEqual(T.ttft_from_payload({
            "usage": {"caravan": {"ttft_s": 1.25}},
        }), 1.25)

    def test_ttft_from_llama_server_prompt_ms(self):
        self.assertEqual(T.ttft_from_payload({
            "timings": {"prompt_ms": 11400, "prompt_per_second": 180},
        }), 11.4)

    def test_ttft_from_first_token_ms(self):
        self.assertEqual(T.ttft_from_payload({
            "timings": {"first_token_ms": 2500},
        }), 2.5)
        self.assertEqual(T.ttft_from_payload({
            "usage": {"caravan": {"first_token_ms": 1800}},
        }), 1.8)

    def test_ttft_from_sse_first_chunk_elapsed(self):
        self.assertEqual(T.ttft_from_payload({}, first_chunk_s=0.42), 0.42)

    def test_missing_or_zero_ttft_returns_none(self):
        self.assertIsNone(T.ttft_from_payload({}))
        self.assertIsNone(T.ttft_from_payload({"usage": {"caravan": {"ttft_s": 0}}}))
        self.assertIsNone(T.ttft_from_payload({"timings": {"prompt_ms": 0}}))
        self.assertNotIn("ttft_s", T.specs_from_response({}))

    def test_measure_http_specs_records_long_prompt_ttft(self):
        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=0):
            prompt = json.loads(req.data.decode())["messages"][0]["content"]
            if prompt.startswith("LONG"):
                body = {
                    "timings": {
                        "predicted_per_second": 22.0,
                        "prompt_per_second": 180.0,
                        "prompt_ms": 11400,
                    },
                    "usage": {
                        "prompt_tokens": 2048,
                        "completion_tokens": 192,
                        "caravan": {"ttft_s": 11.4, "total_s": 20.13},
                    },
                    "choices": [{"message": {"content": "ok"}}],
                }
            else:
                body = {
                    "timings": {
                        "predicted_per_second": 22.0,
                        "prompt_per_second": 400.0,
                        "prompt_ms": 250,
                    },
                    "usage": {
                        "prompt_tokens": 80,
                        "completion_tokens": 192,
                        "caravan": {"ttft_s": 0.25, "total_s": 8.7},
                    },
                    "choices": [{"message": {"content": "ok"}}],
                }
            return R(json.dumps(body).encode())

        out = T.measure_http_specs(
            9000,
            prompts=["hi", "LONG prompt about a journey"],
            prompt_kinds=["short", "long"],
            urlopen=fake,
        )
        self.assertEqual(out["long_ttft_s"], 11.4)
        self.assertEqual(out["long_total_s"], 20.13)
        self.assertEqual(out["long_prompt_tokens"], 2048)
        self.assertEqual(out["long_read_tok_s"], 180.0)
        self.assertEqual(out["short_write_tok_s"], 22.0)
        self.assertEqual(out["short_total_s"], 8.7)

    def test_web_median_specs_records_long_ttft(self):
        opt = WO.Optimizer(mgr=SimpleNamespace())
        samples = [
            {"write_tok_s": 22.0, "ttft_s": 0.25, "total_s": 8.7,
             "read_tok_s": 400.0, "prompt_tokens": 80},
            {"write_tok_s": 22.0, "ttft_s": 11.4, "total_s": 20.13,
             "read_tok_s": 180.0, "prompt_tokens": 2048},
        ]
        out = opt._median_specs(samples, ["short", "long"])
        self.assertEqual(out["long_ttft_s"], 11.4)
        self.assertEqual(out["long_total_s"], 20.13)
        self.assertEqual(out["long_prompt_tokens"], 2048)
        self.assertEqual(out["long_read_tok_s"], 180.0)
        self.assertEqual(out["short_write_tok_s"], 22.0)

    def test_web_specs_from_reply_keeps_worker_rates(self):
        opt = WO.Optimizer(mgr=SimpleNamespace())
        out = opt._specs_from_reply({
            "ttft": 11.4,
            "completion_tokens": 192,
            "prompt_tokens": 2048,
            "total_s": 20.13,
            "prefill_s": 11.4,
            "write_tok_s": 22.0,
            "read_tok_s": 180.0,
        })
        self.assertEqual(out["ttft_s"], 11.4)
        self.assertEqual(out["write_tok_s"], 22.0)
        self.assertEqual(out["read_tok_s"], 180.0)


class MlxAutotuneHookTest(unittest.TestCase):
    def test_guess_ahead_uses_first_word_verdict(self):
        off = specs(22.0, 8.7, long_ttft=11.4)
        on = specs(23.1, 8.3, long_ttft=12.54)
        a = _scores(10.0, off)
        b = _scores(12.0, on)  # combined_score would prefer the helper
        def pick(inc, ch):
            return sum(ch) > sum(inc) * 1.03
        winner, lost, why = WO.decide_tune_winner(
            "guess_ahead", "off", "on", a, b, pick)
        self.assertEqual(winner, "off")
        self.assertEqual(lost, "on")
        self.assertIn("first word", why)

    def test_adaptive_lookup_uses_the_same_verdict(self):
        off = specs(22.0, 8.7, long_ttft=11.4)
        on = specs(33.0, 5.8, long_ttft=12.54)
        a = _scores(10.0, off)
        b = _scores(12.0, on)
        winner, lost, why = WO.decide_tune_winner(
            "adaptive_lookup", False, True, a, b, lambda inc, ch: True)
        self.assertEqual(winner, True)
        self.assertIn("chats", why)

    def test_other_knobs_keep_combined_score(self):
        off = specs(22.0, 8.7, long_ttft=11.4)
        on = specs(23.1, 8.3, long_ttft=12.54)
        a = _scores(10.0, off)
        b = _scores(12.0, on)
        winner, lost, why = WO.decide_tune_winner(
            "kv_bits", 16, 8, a, b, lambda inc, ch: True)
        self.assertEqual(winner, 8)
        self.assertIsNone(why)
        self.assertEqual(T.trial_won("ubatch", on, off), T.beats(on, off))
        self.assertFalse(WO._uses_spec_verdict("native_mtp"))
        self.assertFalse(WO._uses_spec_verdict("shared_prefix"))

    def test_garbled_challenger_still_loses_before_scoring(self):
        off = specs(22.0, 8.7, long_ttft=11.4)
        on = specs(33.0, 5.8, long_ttft=12.54)
        a = _scores(10.0, off)
        b = _scores(12.0, on, garbled=True)
        winner, lost, why = WO.decide_tune_winner(
            "guess_ahead", "off", "on", a, b, lambda inc, ch: True)
        self.assertEqual(winner, "off")
        self.assertIn("garbled", why)

    def test_missing_specs_falls_back_to_pick(self):
        a = _scores(10.0)
        b = _scores(12.0)
        winner, lost, why = WO.decide_tune_winner(
            "guess_ahead", "off", "on", a, b, lambda inc, ch: True)
        self.assertEqual(winner, "on")
        self.assertIsNone(why)


class Day28StillHoldsTest(unittest.TestCase):
    def test_llama_8b_helper_win_is_still_kept(self):
        off = specs(21.0, 9.0, long_read=420.0)
        on = specs(22.9, 8.2, long_read=378.0)
        self.assertTrue(T.trial_won("guess_ahead", on, off))

    def test_hard_long_read_drop_is_still_rejected(self):
        off = specs(19.0, 10.0, long_read=400.0)
        on = specs(30.0, 6.4, long_read=200.0)
        v = T.spec_verdict(on, off)
        self.assertFalse(v["won"])
        self.assertIn("guard", v["why"])


class LocaleAndWhyTest(unittest.TestCase):
    def test_five_locales_share_the_first_word_why_key(self):
        key = "server.gguf_tune.long_prompt_first_word_t_c_vs"
        placeholders = None
        for name in ("en.json", "es.json", "ru.json", "ja.json", "zh-Hans.json"):
            data = json.loads((ROOT / "locales" / name).read_text())
            self.assertIn(key, data, name)
            text = data[key]
            found = set()
            if "{t_c:.1f}" in text:
                found.add("t_c")
            if "{t_i:.1f}" in text:
                found.add("t_i")
            self.assertEqual(found, {"t_c", "t_i"}, name)
            if placeholders is None:
                placeholders = found
            else:
                self.assertEqual(found, placeholders, name)
        self.assertIn("long-prompt first word + reply", english_source(ROOT / "proxy/gguf_tune.py"))

    def test_why_string_is_plain_language(self):
        off = specs(22.0, 8.7, long_ttft=11.4)
        on = specs(23.1, 8.3, long_ttft=12.54)
        why = T.spec_verdict(on, off)["why"]
        self.assertRegex(why, r"first word")
        self.assertRegex(why, r"\d+\.\d+s vs \d+\.\d+s")


if __name__ == "__main__":
    unittest.main()
