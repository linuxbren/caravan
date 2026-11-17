"""Day 28 tuning fixes: Guess-ahead / Prompt lookup scoring, persistence,
helper memory and first-reply checks, failed trials, Balance helper offer
and caravan bench --speedups --only (found by the Day 28 tuning check)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "proxy", "agent"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
import gguf_split as G  # noqa: E402
import gguf_tune as T  # noqa: E402
import gguf_self_tune as ST  # noqa: E402
import web_restore  # noqa: E402
import web_workers as W  # noqa: E402


def specs(write, total, long_read=None, edit=None, read=300.0):
    s = {"write_tok_s": write, "short_write_tok_s": write, "total_s": total,
         "short_total_s": total, "read_tok_s": read, "ttft_s": 0.3}
    if long_read is not None:
        s["long_read_tok_s"] = long_read
    if edit is not None:
        s["edit_write_tok_s"] = edit
    return s


class SpecScoringTest(unittest.TestCase):
    def test_llama_8b_helper_win_is_kept_despite_long_read_dip(self):
        # Day 28 Llama 8B: +9% write, faster replies, long read -10%.
        off = specs(21.0, 9.0, long_read=420.0)
        on = specs(22.9, 8.2, long_read=378.0)
        self.assertFalse(T.beats(on, off))          # the old score lost it
        self.assertTrue(T.trial_won("guess_ahead", on, off))

    def test_long_read_guard_rejects_big_drop(self):
        off = specs(21.0, 9.0, long_read=420.0)
        on = specs(25.0, 7.5, long_read=300.0)      # -29% long read
        v = T.spec_verdict(on, off)
        self.assertFalse(v["won"])
        self.assertIn("guard", v["why"])

    def test_code_edit_win_with_flat_chat(self):
        off = specs(21.0, 9.0, edit=21.0)
        on = specs(20.9, 9.05, edit=28.0)           # chats flat, edits +33%
        self.assertTrue(T.trial_won("prompt_lookup", on, off))

    def test_code_edit_win_does_not_hide_slower_chats(self):
        off = specs(21.0, 9.0, edit=21.0)
        on = specs(19.5, 9.8, edit=28.0)            # chats -7%
        self.assertFalse(T.trial_won("prompt_lookup", on, off))

    def test_other_options_keep_combined_score(self):
        a, b = specs(20.0, 10.0), specs(20.2, 9.95)
        self.assertEqual(T.trial_won("ubatch", b, a), T.beats(b, a))

    def test_as_specs_keeps_kind_medians(self):
        out = T.as_specs({"write_tok_s": 1, "short_write_tok_s": 2, "short_total_s": 3,
                          "edit_write_tok_s": 4, "junk": 5})
        self.assertEqual(out, {"write_tok_s": 1.0, "short_write_tok_s": 2.0,
                               "short_total_s": 3.0, "edit_write_tok_s": 4.0})


class BestTuneRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.store = self.d / "gguf-tuned.json"
        self.model = self.d / "model.gguf"
        self.model.write_bytes(b"x")
        self.draft = self.d / "helper.gguf"
        self.draft.write_bytes(b"x")

    def tearDown(self):
        self.td.cleanup()

    def save(self, best):
        T.save_store({T.entry_key(self.model, 1): {"best": best, "losses": [], "trials": []}},
                     self.store)

    def test_helper_and_lookup_wins_come_back(self):
        self.save({"flash_attn": "on", "guess_ahead": "on", "draft_path": str(self.draft),
                   "prompt_lookup": "on"})
        t = T.best_tune(self.model, 1, self.store)
        self.assertEqual(t["guess_ahead"], "on")
        self.assertEqual(t["draft_path"], str(self.draft))
        self.assertEqual(t["prompt_lookup"], "on")

    def test_missing_helper_falls_back_to_off(self):
        self.save({"guess_ahead": "on", "draft_path": str(self.d / "gone.gguf")})
        with mock.patch.object(G, "find_gguf_draft", return_value=None):
            t = T.best_tune(self.model, 1, self.store)
        self.assertEqual(t["guess_ahead"], "off")
        self.assertNotIn("draft_path", t)

    def test_moved_helper_is_found_again(self):
        self.save({"guess_ahead": "on", "draft_path": str(self.d / "gone.gguf")})
        with mock.patch.object(G, "find_gguf_draft", return_value={"path": str(self.draft)}):
            t = T.best_tune(self.model, 1, self.store)
        self.assertEqual(t["draft_path"], str(self.draft))

    def test_bad_values_are_dropped(self):
        self.save({"guess_ahead": "maybe", "prompt_lookup": 7})
        self.assertEqual(T.best_tune(self.model, 1, self.store), {})

    def test_record_helper_failure_turns_auto_off(self):
        self.save({"guess_ahead": "on", "draft_path": str(self.draft)})
        T.record_helper_failure(self.model, 1, "out of memory", self.store)
        e = T.load_store(self.store)[T.entry_key(self.model, 1)]
        self.assertEqual(e["best"]["guess_ahead"], "off")
        self.assertIn("guess_ahead=on", e["losses"])
        self.assertIn("out of memory", e["helper_failed"]["reason"])

    def test_restart_and_update_restore_keeps_helper(self):
        # web_server Balance restore and web_restore both use this filter.
        saved = {"flash_attn": "on", "ubatch": 512, "guess_ahead": "on",
                 "draft_path": str(self.draft), "prompt_lookup": "on",
                 "helper_failed": True, "junk": 1}
        t = web_restore.restorable_gguf_tune(saved, str(self.model))
        self.assertEqual(t, {"flash_attn": "on", "ubatch": 512, "guess_ahead": "on",
                             "draft_path": str(self.draft), "prompt_lookup": "on"})

    def test_restore_without_helper_file_is_off(self):
        saved = {"guess_ahead": "on", "draft_path": str(self.d / "gone.gguf")}
        with mock.patch.object(G, "find_gguf_draft", return_value=None):
            t = web_restore.restorable_gguf_tune(saved, str(self.model))
        self.assertEqual(t, {"guess_ahead": "off"})

    def test_web_server_balance_restore_uses_the_filter(self):
        src = (Path(__file__).resolve().parents[1] / "proxy" / "web_server.py").read_text()
        self.assertIn('restorable_gguf_tune(body["gguf_tune"]', src)
        self.assertNotIn('in ("flash_attn","ubatch","cache_type","slot_save","ctx","n_slots")', src)


class TunerFailureTest(unittest.TestCase):
    def run_tuner(self, restart, measure, *, fresh=False, losses=None):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d) / "t.json"
            model = Path(d) / "m.gguf"
            if losses is not None:
                T.save_store({T.entry_key(model, 1): {"best": {}, "losses": list(losses),
                                                      "trials": []}}, store)
            tuner = T.GgufTuner(model, 1, restart=restart, measure=measure,
                                store_path=store, log=lambda m: None, fresh=fresh)
            res = tuner.run()
            return res, T.load_store(store)[T.entry_key(model, 1)]

    def test_failed_trial_is_a_loss_and_the_run_continues(self):
        loads = []

        def restart(tune):
            loads.append(dict(tune))
            if tune.get("ubatch") and tune["ubatch"] != G.GGUF_DEFAULT_UBATCH:
                raise RuntimeError("out of memory")
        res, e = self.run_tuner(restart, lambda: specs(20.0, 10.0))
        self.assertEqual(res["status"], "done")
        failed = [t for t in res["tried"] if t.get("failed")]
        self.assertTrue(failed and failed[0]["name"] == "ubatch")
        self.assertFalse(failed[0]["won"])
        self.assertGreater(len(res["tried"]), 1)          # kept going
        self.assertTrue(any(l.startswith("ubatch=") for l in e["losses"]))
        self.assertEqual(loads[-1], res["best"])          # winner left running

    def test_fresh_clears_old_losses(self):
        _, e = self.run_tuner(lambda t: None, lambda: specs(20.0, 10.0), fresh=True,
                              losses=["flash_attn=off", "prompt_lookup=on"])
        names = [t["name"] for t in e["trials"]]
        self.assertIn("flash_attn", names)
        self.assertIn("prompt_lookup", names)

    def test_not_fresh_skips_old_losses(self):
        _, e = self.run_tuner(lambda t: None, lambda: specs(20.0, 10.0),
                              losses=["flash_attn=off", "prompt_lookup=on"])
        names = [t["name"] for t in e["trials"]]
        self.assertNotIn("prompt_lookup", names)

    def test_score_keeps_chat_and_edit_medians(self):
        tuner = T.GgufTuner("m.gguf", 1, restart=lambda t: None,
                            measure=lambda: specs(20.0, 10.0, edit=30.0), log=lambda m: None)
        out = tuner._score({})
        self.assertEqual(out["short_write_tok_s"], 20.0)
        self.assertEqual(out["edit_write_tok_s"], 30.0)


class HelperMemoryAndFlagsTest(unittest.TestCase):
    def test_helper_flags_use_q8_cache_and_gpu(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf") as f:
            f.write(b"x")
            f.flush()
            out = G._speculative_args({"guess_ahead": "on", "draft_path": f.name})
            self.assertIn("draft-simple", out[out.index("--spec-type") + 1])
            self.assertEqual(out[out.index("-ctkd") + 1], "q8_0")
            self.assertEqual(out[out.index("-ctvd") + 1], "q8_0")
            self.assertEqual(out[out.index("--spec-draft-ngl") + 1], "999")
            self.assertNotIn("--spec-draft-device", out)
            split = G._speculative_args({"guess_ahead": "on", "draft_path": f.name}, split=True)
            self.assertEqual(split[split.index("--spec-draft-device") + 1], "MTL0")
            no_fa = G._speculative_args({"guess_ahead": "on", "draft_path": f.name},
                                        flash_attn="off")
            self.assertEqual(no_fa[no_fa.index("-ctvd") + 1], "f16")

    def test_missing_helper_gives_no_flags(self):
        self.assertEqual(G._speculative_args({"guess_ahead": "on", "draft_path": "/nope.gguf"}), [])

    def test_helper_overhead_counts_weights_and_cache(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf") as f:
            f.write(b"\0" * (2 * 1024 * 1024))
            f.flush()
            def boom(_):
                raise ValueError("no metadata")
            self.assertAlmostEqual(G.helper_overhead_mib(f.name, 8192, meta_fn=boom), 2 + 1024.0)
        self.assertEqual(G.helper_overhead_mib("/nope.gguf", 8192), 0.0)

    def test_window_that_leaves_no_room_drops_the_helper(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf") as f:
            f.write(b"x")
            f.flush()
            tune = {"guess_ahead": "on", "draft_path": f.name, "ctx": 32768}
            with mock.patch.object(G, "ctx_fits_known", return_value=False):
                launch = G.resolve_launch("/m.gguf", tune=tune)
                self.assertFalse(launch["helper_fits"])
            with mock.patch.object(G, "ctx_fits_known", return_value=None):
                self.assertTrue(G.resolve_launch("/m.gguf", tune=tune)["helper_fits"])

    def test_extra_memory_shrinks_auto_window(self):
        calls = []

        def est(model_path, ctx, **kw):
            calls.append(kw.get("extra_mib_fn"))
            return (None, None)
        with mock.patch.object(G, "ctx_estimate", side_effect=est):
            G.ctx_fits_known("/m.gguf", 8192, extra_mib_fn=lambda c: 1.0)
        self.assertTrue(calls and callable(calls[0]))


class FirstReplyProbeTest(unittest.TestCase):
    def load(self, probe_results, *, strict=False, tune=None):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "llama-server").write_text("")
            model = d / "m.gguf"
            model.write_bytes(b"x")
            draft = d / "h.gguf"
            draft.write_bytes(b"x")
            m = W.WorkerManager.__new__(W.WorkerManager)
            m.lead_port = 18195
            m.state_dir = d
            m._set = lambda **kw: None
            notes = []
            m._note = notes.append
            for name in ("_kill_gguf", "_kill_lead", "_kill_packer", "_write_gguf_meta",
                         "_wait_lead_ready", "_start_gguf_watch", "_stop_gguf_lead"):
                setattr(m, name, mock.Mock())
            results = list(probe_results)
            m._gguf_first_reply_error = lambda *a, **k: results.pop(0)
            m._gguf_nodes = lambda place: [{"id": "n1", "label": "1st Mac", "role": "lead"}]
            m._node_is_local = lambda n: True
            m._lead_log = lambda: d / "lead.log"
            t = dict(tune or {"guess_ahead": "on", "draft_path": str(draft)})
            entry = {"id": "gguf/m", "name": "m", "source": "gguf", "backend": "llama",
                     "lead_path": str(model), "tune_override": t}
            if strict:
                entry["strict_tune"] = True
            store = d / "tuned.json"
            argv = []
            with mock.patch.object(G, "LLAMA_BIN", str(d)), \
                    mock.patch.object(T, "STORE", store), \
                    mock.patch.object(W.subprocess, "Popen") as popen, \
                    mock.patch.object(W.time, "sleep"):
                popen.return_value.pid = 4242
                try:
                    m._load_gguf_inner(entry, {})
                    err = None
                except RuntimeError as ex:
                    err = str(ex)
                argv = [c[0][0] for c in popen.call_args_list]
            saved = json.loads(store.read_text()) if store.exists() else {}
            return SimpleNamespace(m=m, err=err, argv=argv, notes=notes, saved=saved)

    def test_good_first_reply_loads_once(self):
        r = self.load([None])
        self.assertIsNone(r.err)
        self.assertEqual(len(r.argv), 1)
        self.assertIn("--spec-draft-model", r.argv[0])

    def test_failed_helper_reply_falls_back_without_helper(self):
        r = self.load(["decode() failed: failed to process speculative batch", None])
        self.assertIsNone(r.err)
        self.assertEqual(len(r.argv), 2)
        self.assertIn("--spec-draft-model", r.argv[0])
        self.assertNotIn("--spec-draft-model", r.argv[1])
        self.assertTrue(r.m._loaded_entry["_loaded_tune"]["helper_failed"])
        e = next(iter(r.saved.values()))
        self.assertIn("guess_ahead=on", e["losses"])       # Auto stops retrying it

    def test_strict_trial_fails_instead_of_falling_back(self):
        r = self.load(["out of memory"], strict=True)
        self.assertIn("first test reply failed", r.err)
        self.assertEqual(len(r.argv), 1)

    def test_plain_load_that_cannot_reply_fails(self):
        r = self.load(["boom"], tune={"flash_attn": "on"})
        self.assertIn("first test reply failed", r.err)

    def test_strict_flag_is_not_kept_on_the_loaded_entry(self):
        r = self.load([None], strict=True)
        self.assertNotIn("strict_tune", r.m._loaded_entry)


class SelfTuneHelperTest(unittest.TestCase):
    def test_used_from_tune_keeps_speculative_settings(self):
        u = ST.used_from_tune({"flash_attn": "on", "ubatch": 512, "cache_type": "f16",
                               "guess_ahead": "on", "draft_path": "/h.gguf",
                               "prompt_lookup": "on"})
        self.assertEqual(u["guess_ahead"], "on")
        self.assertEqual(u["draft_path"], "/h.gguf")
        self.assertEqual(u["prompt_lookup"], "on")
        self.assertEqual(ST.used_from_tune({"guess_ahead": "on"})["guess_ahead"], "off")

    def test_pick_trial_tries_helper_first_when_on_disk(self):
        t = ST.pick_trial({"guess_ahead": "off"}, set(), [], draft_path="/h.gguf")
        self.assertEqual((t["name"], t["challenger"]), ("guess_ahead", "on"))
        self.assertEqual(t["extra"]["draft_path"], "/h.gguf")
        for kw in ({"decided": {"guess_ahead"}}, {"draft_path": None}):
            args = dict({"draft_path": "/h.gguf"}, **kw)
            self.assertNotEqual(ST.pick_trial({}, set(), [], **args)["name"], "guess_ahead")
        self.assertNotEqual(ST.pick_trial({}, set(), ["guess_ahead=on"], draft_path="/h")["name"],
                            "guess_ahead")
        self.assertNotEqual(ST.pick_trial({}, {"guess_ahead"}, [], draft_path="/h")["name"],
                            "guess_ahead")

    def test_pinned_guess_ahead_is_not_self_tuned(self):
        self.assertIn("guess_ahead", ST.pinned_knobs({"guess_ahead": "off"}))
        self.assertNotIn("guess_ahead", ST.pinned_knobs({"guess_ahead": "auto"}))

    def _observe(self, d, used, n, write, total, **kw):
        plan = None
        for _ in range(n):
            plan = ST.observe(d / "m.gguf", 1, {"write_tok_s": write, "ttft_s": 0.3,
                                                "total_s": total, "read_tok_s": 300},
                              used=used, settings={}, path=d / "self.json",
                              autotune_path=d / "auto.json",
                              find_draft=lambda mp: str(d / "h.gguf"), **kw)
        return plan

    def test_self_tune_helper_trial_wins_and_keeps_helper(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            base = {"flash_attn": "on", "ubatch": 512, "cache_type": "f16"}
            plan = self._observe(d, base, ST.MIN_SAMPLES, 20.0, 10.0)
            self.assertEqual(plan["action"], "reload")
            self.assertEqual(plan["tune"]["guess_ahead"], "on")
            self.assertEqual(plan["tune"]["draft_path"], str(d / "h.gguf"))
            loaded = dict(plan["tune"])
            plan = self._observe(d, loaded, 1 + ST.MIN_SAMPLES, 26.0, 8.0)
            self.assertNotEqual(plan["action"], "reload")
            e = ST.load_store(d / "self.json")[ST.entry_key(d / "m.gguf", 1)]
            self.assertEqual(e["used"]["guess_ahead"], "on")
            self.assertEqual(e["used"]["draft_path"], str(d / "h.gguf"))

    def test_helper_failure_during_self_tune_is_a_loss_not_a_loop(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            base = {"flash_attn": "on", "ubatch": 512, "cache_type": "f16"}
            plan = self._observe(d, base, ST.MIN_SAMPLES, 20.0, 10.0)
            self.assertEqual(plan["tune"]["guess_ahead"], "on")
            fell_back = dict(base, guess_ahead="off", helper_failed=True)
            plan = self._observe(d, fell_back, 1, 20.0, 10.0)
            self.assertEqual(plan["reason"], "helper failed")
            self.assertEqual(plan["action"], "idle")
            e = ST.load_store(d / "self.json")[ST.entry_key(d / "m.gguf", 1)]
            self.assertIn("guess_ahead=on", e["losses"])
            plan = self._observe(d, fell_back, ST.MIN_SAMPLES, 20.0, 10.0)
            if plan.get("trial"):
                self.assertNotEqual(plan["trial"]["name"], "guess_ahead")

    def test_autotune_decision_wins_over_self_tune(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            T.save_store({T.entry_key(d / "m.gguf", 1): {"best": {"guess_ahead": "off"},
                                                       "losses": [], "trials": []}},
                         d / "auto.json")
            plan = self._observe(d, {"flash_attn": "on"}, ST.MIN_SAMPLES, 20.0, 10.0)
            if plan.get("trial"):
                self.assertNotEqual(plan["trial"]["name"], "guess_ahead")


class BalanceHelperOfferTest(unittest.TestCase):
    def test_balance_split_offers_no_helper_and_says_why(self):
        import web_helpers
        snap = {"model_id": "mlx-community/Qwen3-14B-4bit", "split": True,
                "balance": {"counts": [20, 20]}, "settings": {}}
        self.assertTrue(web_helpers.balance_split(snap))
        self.assertIsNone(web_helpers.offer(snap))
        self.assertIn("Balance", web_helpers.BALANCE_NO_HELPER)
        self.assertFalse(web_helpers.balance_split(dict(snap, balance=None)))
        self.assertFalse(web_helpers.balance_split(dict(snap, split=False)))


class BenchOnlyOneSideTest(unittest.TestCase):
    def test_only_gguf_needs_no_mlx_model(self):
        import caravan_bench as B
        models = [{"id": "gguf/bartowski--Meta-Llama-3.1-8B-Instruct-GGUF",
                   "name": "Llama 3.1 8B", "source": "gguf"}]
        seen = {}

        def fake(args_, gid, mid, gname, mname):
            seen.update(gid=gid, mid=mid)
            return 0
        with mock.patch.object(B, "_main_speedups", side_effect=fake), \
                mock.patch.object(B, "resolve_pair", return_value={
                    "ok": False, "gguf": models[0], "mlx": None,
                    "messages": ['No MLX match for "llama 3.1 8b"']}):
            rc = B.main(["llama 3.1 8b", "--speedups", "--only", "gguf", "--yes"], models=models)
        self.assertEqual(rc, 0)
        self.assertEqual(seen.get("gid"), models[0]["id"])
        self.assertIsNone(seen.get("mid"))

    def test_only_gguf_by_id(self):
        import caravan_bench as B
        seen = {}
        with mock.patch.object(B, "_main_speedups",
                               side_effect=lambda a, g, m, gn, mn: seen.update(gid=g, mid=m) or 0):
            rc = B.main(["--gguf", "gguf/x", "--speedups", "--only", "gguf", "--yes"], models=[])
        self.assertEqual(rc, 0)
        self.assertEqual(seen, {"gid": "gguf/x", "mid": None})


if __name__ == "__main__":
    unittest.main()
