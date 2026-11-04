"""Unit tests for ROADMAP #13(b) learn-from-real-chats (Day 10)."""
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import tuned_settings as T


class TunedSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tuned-settings.json"
        self.model = Path(self.tmp.name) / "Meta-Llama-3.1-8B-Instruct-4bit"
        self.model.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_keys(self):
        self.assertEqual(T.hardware_label(spanned=True), "spanned")
        self.assertEqual(T.hardware_label(spanned=False), "single")
        self.assertTrue(T.entry_key(self.model, spanned=True).endswith(":spanned"))

    def test_normalized_tps_positive(self):
        t = T.normalized_tps(completion_tokens=64, total_s=2.0, prefill_s=0.5)
        self.assertGreater(t, 10.0)
        short = T.normalized_tps(completion_tokens=4, total_s=0.2, prefill_s=0.05)
        long = T.normalized_tps(completion_tokens=64, total_s=2.0, prefill_s=0.5)
        # Short replies are dampened relative to raw rate.
        self.assertLess(short, long * 2)

    def test_neighbors(self):
        self.assertEqual(set(T.neighbors("pipeline_chats", 2)), {1})
        self.assertEqual(T.neighbors("guess_ahead", True), [False])
        self.assertEqual(T.neighbors("shared_prefix", False), [True])
        self.assertEqual(T.neighbors("shared_prefix", True), [False])
        nbs = T.neighbors("packer_layers", 16, n_layers=32)
        self.assertIn(14, nbs)
        self.assertIn(18, nbs)
        self.assertNotIn(16, nbs)
        # Clamp at edges
        nbs1 = T.neighbors("packer_layers", 1, n_layers=32)
        self.assertTrue(all(k >= 1 for k in nbs1))
        nbs_hi = T.neighbors("packer_layers", 31, n_layers=32)
        self.assertTrue(all(k <= 31 for k in nbs_hi))

    def test_resolve_startup_day9_when_empty(self):
        r = T.resolve_startup(
            model_dir=self.model, spanned=True,
            day9_packer_layers=16, day9_pipeline_chats=2, day9_guess_ahead=True,
            explicit={}, path=self.path)
        self.assertEqual(r["packer_layers"], 16)
        self.assertEqual(r["pipeline_chats"], 2)
        self.assertTrue(r["guess_ahead"])
        self.assertFalse(r["shared_prefix"])
        self.assertTrue(any("Day 9" in x or "no saved" in x for x in r["reasons"]))
        T.save_store(r["store"], self.path)

    def test_resolve_startup_uses_saved_winner(self):
        st = T.load_store(self.path)
        e = T.ensure_entry(st, T.entry_key(self.model, spanned=True),
                           model=T.model_stem(self.model), hardware="spanned")
        e["winner"] = {"packer_layers": 18, "pipeline_chats": 1, "guess_ahead": False,
                       "shared_prefix": True}
        T.save_store(st, self.path)
        r = T.resolve_startup(
            model_dir=self.model, spanned=True,
            day9_packer_layers=16, day9_pipeline_chats=2, day9_guess_ahead=True,
            explicit={}, path=self.path)
        self.assertEqual(r["packer_layers"], 18)
        self.assertEqual(r["pipeline_chats"], 1)
        self.assertFalse(r["guess_ahead"])
        self.assertTrue(r["shared_prefix"])
        self.assertTrue(any("learned" in x for x in r["reasons"]))
        self.assertTrue(any("shared-prefix" in x for x in r["reasons"]))

    def test_flags_win(self):
        st = T.load_store(self.path)
        e = T.ensure_entry(st, T.entry_key(self.model, spanned=True),
                           model=T.model_stem(self.model), hardware="spanned")
        e["winner"] = {"packer_layers": 18, "pipeline_chats": 1}
        T.save_store(st, self.path)
        r = T.resolve_startup(
            model_dir=self.model, spanned=True,
            day9_packer_layers=16, day9_pipeline_chats=2, day9_guess_ahead=True,
            explicit={"packer_layers": 20, "pipeline_chats": 2, "shared_prefix": True},
            path=self.path)
        self.assertEqual(r["packer_layers"], 20)
        self.assertEqual(r["pipeline_chats"], 2)
        self.assertTrue(r["shared_prefix"])
        self.assertTrue(any("flag" in x for x in r["reasons"]))
        self.assertTrue(any("flag shared-prefix" in x for x in r["reasons"]))

    def test_pending_reload_tried_once(self):
        st = T.load_store(self.path)
        key = T.entry_key(self.model, spanned=True)
        e = T.ensure_entry(st, key, model=T.model_stem(self.model), hardware="spanned")
        e["winner"] = {"packer_layers": 16}
        e["pending_reload"] = {"packer_layers": 18}
        T.save_store(st, self.path)
        r = T.resolve_startup(
            model_dir=self.model, spanned=True,
            day9_packer_layers=16, day9_pipeline_chats=2, day9_guess_ahead=None,
            explicit={}, path=self.path, n_layers=32)
        self.assertEqual(r["packer_layers"], 18)
        self.assertTrue(any("queued" in x or "try split" in x for x in r["reasons"]))
        # Pending cleared in the returned entry
        self.assertNotIn("packer_layers", r["entry"].get("pending_reload") or {})
        T.save_store(r["store"], self.path)
        r2 = T.resolve_startup(
            model_dir=self.model, spanned=True,
            day9_packer_layers=16, day9_pipeline_chats=2, day9_guess_ahead=None,
            explicit={}, path=self.path, n_layers=32)
        # Back to saved winner 16 (pending consumed); winner still 16
        self.assertEqual(r2["packer_layers"], 16)

    def test_pipeline_probe_promotes_after_enough_samples(self):
        st = {"version": 1, "models": {}}
        e = T.ensure_entry(st, "m:spanned", model="m", hardware="spanned")
        e["winner"] = {"pipeline_chats": 1}
        for _ in range(3):
            T.record_pipeline_probe(e, n_chats=1, aggregate_tps=18.0)
        out = None
        for _ in range(3):
            out = T.record_pipeline_probe(e, n_chats=2, aggregate_tps=30.0)
        self.assertEqual(e["winner"]["pipeline_chats"], 2)
        self.assertTrue(any(p[0] == "pipeline_chats" for p in out["promotions"]))

    def test_pipeline_probe_needs_both_sides(self):
        st = {"version": 1, "models": {}}
        e = T.ensure_entry(st, "m:spanned", model="m", hardware="spanned")
        e["winner"] = {"pipeline_chats": 2}
        # One fast probe at 1 must NOT steal the Day 9 winner yet.
        out = T.record_pipeline_probe(e, n_chats=1, aggregate_tps=40.0)
        self.assertEqual(e["winner"]["pipeline_chats"], 2)
        self.assertTrue(out["keep_reasons"])

    def test_pipeline_probe_keeps_when_challenger_worse(self):
        st = {"version": 1, "models": {}}
        e = T.ensure_entry(st, "m:spanned", model="m", hardware="spanned")
        e["winner"] = {"pipeline_chats": 2}
        for _ in range(3):
            T.record_pipeline_probe(e, n_chats=2, aggregate_tps=30.0)
        out = None
        for _ in range(3):
            out = T.record_pipeline_probe(e, n_chats=1, aggregate_tps=18.0)
        self.assertEqual(e["winner"]["pipeline_chats"], 2)
        self.assertTrue(out["keep_reasons"] or not out["promotions"] or
                        all(p[1] != 1 for p in out["promotions"]))

    def test_observe_reply_skips_pipeline_by_default(self):
        st = {"version": 1, "models": {}}
        e = T.ensure_entry(st, "m:spanned", model="m", hardware="spanned")
        e["winner"] = {"pipeline_chats": 2, "guess_ahead": True}
        T.observe_reply(e, settings_used={"pipeline_chats": 1, "guess_ahead": True},
                        completion_tokens=32, total_s=1.5, prefill_s=0.3)
        # Single-chat observe must not sample pipeline_chats=1
        self.assertEqual(T.samples_of(e, "pipeline_chats", 1), 0)
        self.assertGreaterEqual(T.samples_of(e, "guess_ahead", True), 1)

    def test_exploration_defers_packer_layers(self):
        st = {"version": 1, "models": {}}
        e = T.ensure_entry(st, "m:spanned", model="m", hardware="spanned")
        e["winner"] = {"pipeline_chats": 2, "packer_layers": 16}
        e["reply_n"] = 3  # next observe will be 4 → explore due
        # Saturate live setting samples so it falls through to packer queue.
        for v in (1, 2):
            for _ in range(T.MIN_SAMPLES):
                T.record_sample(e, "pipeline_chats", v, 20.0)
        for v in (True, False):
            for _ in range(T.MIN_SAMPLES):
                T.record_sample(e, "guess_ahead", v, 20.0)
        out = T.observe_reply(
            e,
            settings_used={"pipeline_chats": 2, "guess_ahead": True, "packer_layers": 16},
            completion_tokens=32, total_s=1.5, prefill_s=0.3,
            n_layers=32)
        # Either live re-check or deferred packer queue
        if out["explore"] and out["explore"].get("name") == "packer_layers":
            self.assertTrue(out["explore"].get("deferred"))
            self.assertEqual(e["pending_reload"].get("packer_layers"),
                             out["explore"]["value"])

    def test_roundtrip_save_load(self):
        st = T.load_store(self.path)
        e = T.ensure_entry(st, T.entry_key(self.model, spanned=False),
                           model=T.model_stem(self.model), hardware="single")
        e["winner"] = {"pipeline_chats": 1}
        T.record_sample(e, "pipeline_chats", 1, 12.5)
        T.save_store(st, self.path)
        st2 = T.load_store(self.path)
        e2 = st2["models"][T.entry_key(self.model, spanned=False)]
        self.assertEqual(e2["winner"]["pipeline_chats"], 1)
        self.assertEqual(e2["hardware"], "single")

    def test_exploration_waits_for_pipeline_incumbent_samples(self):
        st = {"version": 1, "models": {}}
        e = T.ensure_entry(st, "m:spanned", model="m", hardware="spanned")
        e["winner"] = {"pipeline_chats": 2, "guess_ahead": True}
        e["reply_n"] = 3
        # No pipeline probes yet — must NOT explore away from 2.
        for _ in range(T.MIN_SAMPLES):
            T.record_sample(e, "guess_ahead", True, 20.0)
        out = T.observe_reply(
            e,
            settings_used={"pipeline_chats": 2, "guess_ahead": True},
            completion_tokens=32, total_s=1.5, prefill_s=0.3)
        if out["explore"]:
            self.assertNotEqual(out["explore"].get("name"), "pipeline_chats")
        # After enough probes on 2, exploring 1 is allowed and carries trial_replies.
        for _ in range(T.MIN_SAMPLES):
            T.record_pipeline_probe(e, n_chats=2, aggregate_tps=28.0)
        e["reply_n"] = 6  # observe → 7; pick_exploration uses 8 (due)
        out2 = T.observe_reply(
            e,
            settings_used={"pipeline_chats": 2, "guess_ahead": True},
            completion_tokens=32, total_s=1.5, prefill_s=0.3)
        self.assertIsNotNone(out2["explore"])
        self.assertEqual(out2["explore"]["name"], "pipeline_chats")
        self.assertEqual(out2["explore"]["value"], 1)
        self.assertEqual(out2["explore"].get("trial_replies"), T.MIN_SAMPLES * 2)

    def test_observe_reply_ignores_pipeline_promote(self):
        st = {"version": 1, "models": {}}
        e = T.ensure_entry(st, "m:spanned", model="m", hardware="spanned")
        e["winner"] = {"pipeline_chats": 2}
        # Even with fake samples on 1, observe_reply must not switch pipeline.
        for _ in range(5):
            T.record_sample(e, "pipeline_chats", 1, 99.0)
        out = T.observe_reply(
            e, settings_used={"pipeline_chats": 1, "guess_ahead": False},
            completion_tokens=32, total_s=1.5, prefill_s=0.3)
        self.assertEqual(e["winner"]["pipeline_chats"], 2)
        self.assertFalse(any(p[0] == "pipeline_chats" for p in out["promotions"]))



class SharedPrefixLearnTest(unittest.TestCase):
    """Day 13: shared-prefix on/off learned from TTFT on shared system prompts."""

    def setUp(self):
        self.entry = T.ensure_entry(
            {"version": 1, "models": {}}, "m:spanned", model="m", hardware="spanned")
        self.entry["winner"] = {"shared_prefix": False}

    def test_score_inverse_ttft(self):
        self.assertGreater(T.shared_prefix_score(1.0), T.shared_prefix_score(2.0))

    def test_eligible(self):
        self.assertTrue(T.shared_prefix_eligible(prompt_tokens=600, how="cold"))
        self.assertTrue(T.shared_prefix_eligible(
            prompt_tokens=600, how="shared-prefix-hit-memory"))
        self.assertFalse(T.shared_prefix_eligible(prompt_tokens=100, how="cold"))
        self.assertFalse(T.shared_prefix_eligible(prompt_tokens=600, how="hit-memory"))

    def test_store_not_counted_as_on_mean(self):
        out = T.record_shared_prefix_probe(
            self.entry, enabled=True, ttft_s=20.0, how="cold", prompt_tokens=2048)
        self.assertTrue(out["recorded"])
        self.assertEqual(out["kind"], "store")
        self.assertEqual(T.samples_of(self.entry, "shared_prefix", True), 0)
        self.assertEqual(self.entry["stats"]["shared_prefix:on_store"]["n"], 1)

    def test_promotes_on_when_hits_beat_cold(self):
        # 3 cold-off at ~10s TTFT, 1 store, 3 hits at ~2s → on wins.
        for _ in range(3):
            T.record_shared_prefix_probe(
                self.entry, enabled=False, ttft_s=10.0, how="cold", prompt_tokens=2048)
        T.record_shared_prefix_probe(
            self.entry, enabled=True, ttft_s=22.0, how="cold", prompt_tokens=2048)
        out = None
        for _ in range(3):
            out = T.record_shared_prefix_probe(
                self.entry, enabled=True, ttft_s=2.0,
                how="shared-prefix-hit-memory", prompt_tokens=2048)
        self.assertTrue(self.entry["winner"]["shared_prefix"])
        self.assertTrue(any(p[0] == "shared_prefix" and p[1] is True
                            for p in out["promotions"]))

    def test_keeps_off_when_no_hits(self):
        # Old Gemma shape: on never hits, only store/cold — stay off.
        for _ in range(3):
            T.record_shared_prefix_probe(
                self.entry, enabled=False, ttft_s=11.0, how="cold", prompt_tokens=2048)
        for _ in range(5):
            out = T.record_shared_prefix_probe(
                self.entry, enabled=True, ttft_s=12.0, how="cold", prompt_tokens=2048)
        self.assertFalse(self.entry["winner"]["shared_prefix"])
        self.assertEqual(T.samples_of(self.entry, "shared_prefix", True), 0)

    def test_keeps_off_when_hits_not_better(self):
        for _ in range(3):
            T.record_shared_prefix_probe(
                self.entry, enabled=False, ttft_s=5.0, how="cold", prompt_tokens=2048)
        T.record_shared_prefix_probe(
            self.entry, enabled=True, ttft_s=8.0, how="cold", prompt_tokens=2048)
        out = None
        for _ in range(3):
            out = T.record_shared_prefix_probe(
                self.entry, enabled=True, ttft_s=6.0,
                how="shared-prefix-hit-memory", prompt_tokens=2048)
        self.assertFalse(self.entry["winner"]["shared_prefix"])
        self.assertTrue(out["keep_reasons"] or not out["promotions"])

    def test_flag_skips_via_explicit_in_observe_path(self):
        # resolve_startup with explicit shared_prefix pins the value.
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "t.json"
        model = Path(tmp.name) / "Model-X"
        model.mkdir()
        r = T.resolve_startup(
            model_dir=model, spanned=True,
            day9_packer_layers=16, day9_pipeline_chats=2, day9_guess_ahead=None,
            explicit={"shared_prefix": True}, path=path)
        self.assertTrue(r["shared_prefix"])
        self.assertTrue(any("flag shared-prefix: on" in x for x in r["reasons"]))
        tmp.cleanup()

    def test_explore_waits_for_off_samples_then_tries_on(self):
        e = self.entry
        e["winner"] = {"shared_prefix": False, "pipeline_chats": 2, "guess_ahead": True}
        e["reply_n"] = 0
        # Saturate other live settings so shared_prefix is the interesting one.
        for v in (True, False):
            for _ in range(T.MIN_SAMPLES):
                T.record_sample(e, "guess_ahead", v, 20.0)
        for v in (1, 2):
            for _ in range(T.MIN_SAMPLES):
                T.record_sample(e, "pipeline_chats", v, 20.0)
        # No off TTFT samples yet → should not explore shared_prefix on.
        out = T.pick_exploration(
            e, {"shared_prefix": False, "pipeline_chats": 2, "guess_ahead": True,
                "packer_layers": 16},
            explicit={"pipeline_chats": 2, "guess_ahead": True})
        if out and out.get("name") == "shared_prefix":
            self.fail("explored shared_prefix before off samples")
        # After enough cold-off samples, early explore should try on.
        for _ in range(T.MIN_SAMPLES):
            T.record_shared_prefix_probe(
                e, enabled=False, ttft_s=10.0, how="cold", prompt_tokens=2048)
        out2 = T.pick_exploration(
            e, {"shared_prefix": False, "pipeline_chats": 2, "guess_ahead": True,
                "packer_layers": 16},
            explicit={"pipeline_chats": 2, "guess_ahead": True})
        self.assertIsNotNone(out2)
        self.assertEqual(out2["name"], "shared_prefix")
        self.assertTrue(out2["value"])
        self.assertEqual(out2["trial_replies"], T.SHARED_PREFIX_TRIAL_REPLIES)



if __name__ == "__main__":
    unittest.main()
