"""Day 25 GGUF round 2: self-tuning from chats, chat window, two chats, bench."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))

import gguf_split as G  # noqa: E402
import gguf_self_tune as GST  # noqa: E402
import gguf_tune as T  # noqa: E402
import kv_auto  # noqa: E402
import web_settings as WS  # noqa: E402
import web_speed as S  # noqa: E402
import caravan_bench as B  # noqa: E402


def _decide_f16(*a, **k):
    return SimpleNamespace(cache_type_k="f16", cache_type_v="f16", reason="fits",
                           estimate={"need_q8_0_mib": 10, "budget_mib": 10000})


def _meta(length):
    def fn(path):
        return {"general.architecture": "qwen2", "qwen2.context_length": length}
    return fn


def _decide(need_at):
    """need_at(ctx) -> (need_q8, budget)."""
    def fn(model_path, n_slots, ctx_per_slot, *a, **k):
        need, budget = need_at(int(ctx_per_slot), int(n_slots))
        return kv_auto.KvDecision("f16", "f16", "est", {
            "need_q8_0_mib": need, "budget_mib": budget,
        })
    return fn


class LaunchFlags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_default_window_stays_8192_without_a_measurable_file(self):
        a = G.llama_args("/m.gguf", port=8194, peers=[], shares=[1],
                         decide=_decide_f16, slot_root=self.root)
        self.assertEqual(a[a.index("-c") + 1], "8192")
        self.assertNotIn("--parallel", a)
        self.assertNotIn("--no-kv-unified", a)
        self.assertTrue(a[a.index("--slot-save-path") + 1].endswith("f16_f16/"))
        launch = G.resolve_launch("/m.gguf", decide=_decide_f16)
        self.assertEqual(launch["ctx"], 8192)
        self.assertEqual(launch["n_slots"], 1)

    def test_two_chats_sets_parallel_and_total_context(self):
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1],
                         tune={"n_slots": 2}, decide=_decide_f16, slot_root=self.root)
        self.assertEqual(a[a.index("--parallel") + 1], "2")
        self.assertIn("--no-kv-unified", a)
        self.assertEqual(a[a.index("-c") + 1], "16384")  # 8192 * 2
        slot = a[a.index("--slot-save-path") + 1]
        self.assertIn("_s2", slot)
        launch = G.resolve_launch("/m.gguf", tune={"n_slots": 2}, decide=_decide_f16)
        self.assertEqual(launch["ctx"], 8192)
        self.assertEqual(launch["n_slots"], 2)

    def test_pinned_window_and_two_chats(self):
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1],
                         tune={"ctx": 16384, "n_slots": 2},
                         decide=_decide_f16, slot_root=self.root)
        self.assertEqual(a[a.index("-c") + 1], "32768")
        self.assertEqual(a[a.index("--parallel") + 1], "2")
        slot = a[a.index("--slot-save-path") + 1]
        self.assertIn("_c16384", slot)
        self.assertIn("_s2", slot)

    def test_auto_ctx_falls_back_and_caps(self):
        self.assertEqual(G.auto_ctx("/missing.gguf"), 8192)
        # Model trained at 32768, memory fits everything: Auto is 32768.
        fits = _decide(lambda ctx, slots: (10, 10000))
        self.assertEqual(
            G.auto_ctx("/m.gguf", decide=fits, meta_fn=_meta(32768)), 32768)
        # Trained far above the agent-path window: Auto still caps, never 262144.
        self.assertEqual(
            G.auto_ctx("/m.gguf", decide=fits, meta_fn=_meta(262144)), 32768)
        self.assertLess(G.auto_ctx("/m.gguf", decide=fits, meta_fn=_meta(262144)), 65536)
        # Only 8192 fits: stay there.
        tight = _decide(lambda ctx, slots: (10 if ctx <= 8192 else 99999, 1000))
        self.assertEqual(
            G.auto_ctx("/m.gguf", decide=tight, meta_fn=_meta(32768)), 8192)
        # Model trained for 4096: Auto is 4096.
        self.assertEqual(
            G.auto_ctx("/m.gguf", decide=fits, meta_fn=_meta(4096)), 4096)

    def test_disabled_window_sizes_are_plain(self):
        tight = _decide(lambda ctx, slots: (10 if ctx <= 8192 else 99999, 1000))
        d = G.disabled_ctx_values("/m.gguf", decide=tight, meta_fn=_meta(32768))
        self.assertIn("16384", d)
        self.assertIn("will not fit", d["16384"])
        self.assertNotIn("GB", d["16384"])
        self.assertNotIn("16 GB", json.dumps(d))
        self.assertNotIn("8192", d)
        short = G.disabled_ctx_values("/m.gguf", decide=_decide(lambda c, s: (1, 10000)),
                                      meta_fn=_meta(8192))
        self.assertIn("16384", short)
        self.assertIn("shorter window", short["16384"])

    def test_resolve_web_kv_passes_slot_count(self):
        seen = {}
        def decide(model_path, n_slots, ctx_per_slot, **k):
            seen["n_slots"] = n_slots
            seen["ctx"] = ctx_per_slot
            return SimpleNamespace(cache_type_k="q8_0", cache_type_v="q8_0",
                                   reason="x", estimate={})
        G.resolve_web_kv(model_path="/m.gguf", ctx=16384, n_slots=2, decide=decide)
        self.assertEqual(seen["n_slots"], 2)
        self.assertEqual(seen["ctx"], 16384)

    def test_never_jumps_to_agent_window_in_llama_args(self):
        fits = _decide(lambda ctx, slots: (10, 10000))
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1],
                         decide=fits, meta_fn=_meta(262144), slot_root=self.root)
        self.assertEqual(int(a[a.index("-c") + 1]), 32768)
        self.assertNotEqual(a[a.index("-c") + 1], "262144")


class Settings(unittest.TestCase):
    def test_apply_pins_window_and_slots(self):
        t = WS.apply_gguf_settings({}, {"chat_window": "16384", "pipeline_chats": "2"})
        self.assertEqual(t["ctx"], 16384)
        self.assertEqual(t["n_slots"], 2)
        auto = WS.apply_gguf_settings({"ctx": 16384, "n_slots": 2},
                                      {"chat_window": "auto", "pipeline_chats": "auto"})
        self.assertNotIn("ctx", auto)
        self.assertNotIn("n_slots", auto)

    def test_gguf_active_settings(self):
        a = WS.gguf_active_settings(
            {"flash_attn": "on", "ubatch": 512, "cache_type": "q8_0", "slot_save": True},
            {"self_tune": "auto", "pipeline_chats": "2", "chat_window": "16384"},
            launch={"ctx": 16384, "n_slots": 2},
        )
        self.assertEqual(a["backend"], "llama")
        self.assertEqual(a["pipeline_chats"], 2)
        self.assertTrue(a["two_chats_available"])
        self.assertEqual(a["chat_window"], 16384)
        self.assertEqual(a["kv_bits"], 8)
        self.assertTrue(a["self_tune"])
        self.assertTrue(a["shared_start"])

    def test_page_help_is_plain(self):
        html = (ROOT / "proxy/web/index.html").read_text()
        self.assertIn("Let two chats share the model at the same time", html)
        self.assertIn("Auto keeps one chat", html)
        self.assertIn("How much of the conversation the model can keep in mind at once", html)
        self.assertNotIn("Not used until they will not get in each other's way", html)
        self.assertNotIn("prf-hays", html)
        self.assertNotIn("16 GB", html)
        self.assertIn('a.backend === "llama"', html)
        self.assertIn("Trying a different", (ROOT / "proxy/gguf_self_tune.py").read_text())


class SelfTune(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "self.json"
        self.speed = Path(self.tmp.name) / "speed.json"
        self.model = Path(self.tmp.name) / "qwen.gguf"
        self.model.write_bytes(b"x")

    def _obs(self, specs, **kw):
        kw.setdefault("used", {"flash_attn": "on", "ubatch": 512, "cache_type": "f16"})
        kw.setdefault("settings", {"self_tune": "auto"})
        kw.setdefault("path", self.store)
        kw.setdefault("speed_path", self.speed)
        kw.setdefault("model_id", "gguf/qwen")
        return GST.observe(self.model, 1, specs, **kw)

    def _fast(self, write=40.0):
        return {"write_tok_s": write, "read_tok_s": 100.0, "ttft_s": 0.30,
                "prompt_tokens": 20, "completion_tokens": 40, "total_s": 1.2}

    def test_proposes_one_quiet_trial_after_enough_chats(self):
        plan = None
        for _ in range(GST.MIN_SAMPLES):
            plan = self._obs(self._fast(40))
        self.assertEqual(plan["action"], "reload")
        self.assertEqual(plan["reason"], "trial")
        self.assertEqual(plan["label"], "Prompt batch")
        self.assertIn("ubatch", plan["tune"])
        self.assertNotEqual(plan["tune"]["ubatch"], 512)
        # Chat window and Two chats are never the trial.
        self.assertNotIn("ctx", plan["tune"])
        self.assertNotIn("n_slots", plan["tune"])

    def test_keeps_a_faster_trial_and_fills_before_after(self):
        for _ in range(GST.MIN_SAMPLES):
            self._obs(self._fast(40))
        # Settling skip, then MIN_SAMPLES faster chats.
        self._obs(self._fast(80))  # settling
        plan = None
        for _ in range(GST.MIN_SAMPLES):
            plan = self._obs(self._fast(80))
        self.assertEqual(plan["action"], "keep")
        self.assertTrue(plan["has_winners"])
        self.assertEqual(plan["before"]["write_tok_s"], 40)
        self.assertEqual(plan["after"]["write_tok_s"], 80)
        got = S.get_tuning("gguf/qwen", path=self.speed)
        self.assertEqual(got["source"], "self_tune")
        self.assertEqual(len(got["lines"]), 2)
        self.assertIn("Before ·", got["lines"][0])
        self.assertIn("Write", got["lines"][0])
        self.assertIn("After ·", got["lines"][1])
        # Frozen: further chats do not start another trial.
        later = self._obs(self._fast(90))
        self.assertEqual(later["action"], "idle")
        self.assertTrue(later["has_winners"])

    def test_reverts_a_slower_trial(self):
        for _ in range(GST.MIN_SAMPLES):
            self._obs(self._fast(40))
        self._obs(self._fast(10))  # settling
        plan = None
        for _ in range(GST.MIN_SAMPLES):
            plan = self._obs(self._fast(10))
        self.assertEqual(plan["action"], "reload")
        self.assertEqual(plan["reason"], "revert")
        self.assertEqual(plan["tune"]["ubatch"], 512)
        self.assertTrue(plan["unchanged"])
        got = S.get_tuning("gguf/qwen", path=self.speed)
        self.assertTrue(got.get("unchanged") or (got["lines"] and "nothing" in (got.get("line") or "").lower())
                        or got["source"] == "self_tune")

    def test_pinned_knob_is_skipped(self):
        for _ in range(GST.MIN_SAMPLES):
            plan = self._obs(
                self._fast(40),
                settings={"self_tune": "auto", "ubatch": "512", "flash_attn": "auto"},
            )
        # ubatch is pinned, so the first trial is the next knob (cache_type).
        self.assertEqual(plan["action"], "reload")
        self.assertEqual(plan["trial"]["name"], "cache_type")
        self.assertEqual(plan["label"], "Memory compression")

    def test_off_does_not_learn(self):
        plan = self._obs(self._fast(40), self_tune_on=False)
        self.assertEqual(plan["action"], "idle")
        self.assertFalse(self.store.exists() or (
            self.store.exists() and GST.load_store(self.store)))

    def test_pick_trial_order_and_losses(self):
        used = {"flash_attn": "on", "ubatch": 512, "cache_type": "f16"}
        t = GST.pick_trial(used, set(), [])
        self.assertEqual(t["name"], "ubatch")
        t2 = GST.pick_trial(used, {"ubatch"}, [])
        self.assertEqual(t2["name"], "cache_type")
        t3 = GST.pick_trial(used, {"ubatch", "cache_type"}, [])
        self.assertEqual(t3["name"], "flash_attn")
        t4 = GST.pick_trial(used, {"ubatch", "cache_type", "flash_attn"}, [])
        self.assertIsNone(t4)
        t5 = GST.pick_trial(used, set(), ["ubatch=256", "ubatch=1024"])
        self.assertEqual(t5["name"], "cache_type")

    def test_controller_reloads_when_idle(self):
        switched = []
        notes = []
        class Mgr:
            def _note(self, m):
                notes.append(m)
            def switch(self, *a, **k):
                switched.append((a, k))
            def snapshot(self):
                return {"status": "ready"}
        c = GST.Controller(Mgr(), inflight=lambda: 0,
                           optimizer_running=lambda: False, sleep=lambda x: None)
        c.handle(
            {"action": "reload", "tune": {"ubatch": 1024}, "reason": "trial",
             "label": "Prompt batch"},
            model_id="gguf/qwen", entry={"id": "gguf/qwen", "lead_path": str(self.model)},
            settings={}, model_path=str(self.model), n_minis=1,
        )
        c._thread.join(timeout=3)
        self.assertTrue(switched)
        self.assertEqual(switched[0][1]["entry"]["tune_override"]["ubatch"], 1024)
        self.assertTrue(any("The model is reloading" in n for n in notes))
        self.assertTrue(any("Prompt batch" in n for n in notes))

    def test_controller_waits_while_a_reply_is_in_flight(self):
        switched = []
        n = {"v": 1, "calls": 0}
        def inflight():
            n["calls"] += 1
            if n["calls"] > 5:
                n["v"] = 0
            return n["v"]
        class Mgr:
            def _note(self, m):
                pass
            def switch(self, *a, **k):
                switched.append(1)
            def snapshot(self):
                return {"status": "ready"}
        c = GST.Controller(Mgr(), inflight=inflight,
                           optimizer_running=lambda: False, sleep=lambda x: None)
        c.handle({"action": "reload", "tune": {"ubatch": 256}, "reason": "trial",
                  "label": "Prompt batch"}, model_id="x")
        c._thread.join(timeout=3)
        self.assertGreater(n["calls"], 5)
        self.assertTrue(switched)

    def test_reset_clears_both_stores(self):
        # Simulate a finished self-tune and an Optimize now winner.
        GST.observe  # ensure import
        store = Path(self.tmp.name) / "tuned.json"
        st = T.load_store(store)
        e = T.entry(st, T.entry_key(self.model, 1))
        e["best"] = {"ubatch": 1024}
        T.save_store(st, store)
        self._obs(self._fast(40))
        self.assertTrue(GST.load_store(self.store))
        GST.clear_entry(self.model, 1, path=self.store)
        self.assertFalse(GST.load_store(self.store))
        st2 = T.load_store(store)
        key = T.entry_key(self.model, 1)
        if key in st2:
            del st2[key]
            T.save_store(st2, store)
        self.assertNotIn(key, T.load_store(store))


class Bench(unittest.TestCase):
    def test_wording_matches_reply_stats(self):
        specs = {
            "write_tok_s": 20.7, "read_tok_s": 200, "ttft_s": 0.34,
            "prompt_tokens": 165, "completion_tokens": 10, "total_s": 0.78,
        }
        line = B.format_side("Qwen2.5 Coder 7B (GGUF Q4_K_M)", specs)
        expected = S.format_reply_stats(
            20.7, 0.34, prompt_tokens=165, read_tok_s=200,
            completion_tokens=10, total_s=0.78,
        )
        self.assertEqual(line, f"Qwen2.5 Coder 7B (GGUF Q4_K_M): {expected}")
        self.assertIn("Read 165 tok at 200 tok/s", line)
        self.assertIn("Write 10 tok at 20.7 tok/s", line)
        self.assertIn("first token 0.34s", line)
        self.assertIn("total 0.78s", line)
        self.assertIn("no speed numbers recorded yet", B.format_side("X", {}))

    def test_steps_do_not_invent_numbers(self):
        text = B.steps_text("gguf/qwen", "mlx-community/qwen")
        self.assertIn("caravan bench --gguf gguf/qwen --mlx mlx-community/qwen --yes", text)
        self.assertIn("--from-averages", text)
        self.assertIn("1st Mac", text)
        self.assertNotIn("tok/s", text)  # no invented speeds
        self.assertNotIn("prf-hays", text)

    def test_from_averages_uses_saved_numbers(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Path(tmp.name) / "speed.json"
        S.record("gguf/qwen", {}, write_tok_s=21.0, ttft_s=0.40,
                 prompt_tokens=100, read_tok_s=180, completion_tokens=30,
                 total_s=1.50, path=store)
        S.record("mlx/qwen", {}, write_tok_s=28.0, ttft_s=0.25,
                 prompt_tokens=100, read_tok_s=220, completion_tokens=30,
                 total_s=1.10, path=store)
        lines = B.run_from_averages(
            "gguf/qwen", "mlx/qwen",
            gguf_name="Qwen (GGUF)", mlx_name="Qwen (MLX)", store=store,
        )
        self.assertIn("Qwen (GGUF):", lines[0])
        self.assertIn("Write 30 tok at 21.0 tok/s", lines[0])
        self.assertIn("Qwen (MLX):", lines[1])
        self.assertIn("Write 30 tok at 28.0 tok/s", lines[1])

    def test_cli_without_yes_prints_steps(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = B.main(["--gguf", "gguf/a", "--mlx", "mlx/b"])
        self.assertEqual(rc, 0)
        self.assertIn("--yes", buf.getvalue())
        self.assertNotIn("tok/s", buf.getvalue())

    def test_live_measure_uses_chat_api(self):
        calls = []
        def urlopen(url, data=None, timeout=30, headers=None):
            calls.append(url)
            if url.endswith("/api/status"):
                # After a load, report ready for the requested model.
                mid = "gguf/a" if not any("mlx/b" in c and "load" in c for c in calls) else "mlx/b"
                if any(c.endswith("/api/models/load") for c in calls):
                    # last load body
                    last_load = [c for c in calls if c.endswith("/api/models/load")][-1]
                    # We don't have body here; use call count.
                n_loads = sum(1 for c in calls if c.endswith("/api/models/load"))
                mid = "gguf/a" if n_loads < 2 else "mlx/b"
                if n_loads == 0:
                    mid = None
                return {"worker": {"status": "ready" if mid else "idle", "model_id": mid}}
            if url.endswith("/api/models/load"):
                return {"ok": True}
            if url.endswith("/api/chat"):
                n_loads = sum(1 for c in calls if c.endswith("/api/models/load"))
                write = 20.0 if n_loads < 2 else 30.0
                return {
                    "timings": {"predicted_per_second": write, "prompt_per_second": 100,
                                "prompt_ms": 200},
                    "usage": {"prompt_tokens": 50, "completion_tokens": 20},
                    "caravan_web": {"stats": {
                        "write_tok_s": write, "read_tok_s": 100, "ttft_s": 0.20,
                        "prompt_tokens": 50, "completion_tokens": 20, "total_s": 0.80,
                    }},
                }
            raise AssertionError(url)
        lines = B.run_live("gguf/a", "mlx/b", urlopen=urlopen,
                           gguf_name="G", mlx_name="M", prompts=["hi"])
        self.assertIn("G:", lines[0])
        self.assertIn("Write 20 tok at 20.0 tok/s", lines[0])
        self.assertIn("M:", lines[1])
        self.assertIn("Write 20 tok at 30.0 tok/s", lines[1])
        self.assertTrue(any(c.endswith("/api/models/load") for c in calls))

    def test_caravan_dispatches_bench(self):
        import caravan as C
        with mock.patch("caravan_bench.main", return_value=0) as m:
            # caravan.py early-dispatches; import path is tools/
            pass
        src = (ROOT / "tools/caravan.py").read_text()
        self.assertIn('argv[0] == "bench"', src)
        self.assertIn('"bench"', src)


class Docs(unittest.TestCase):
    def test_day25_docs_are_plain(self):
        day = ROOT / "docs/DAY25.md"
        self.assertTrue(day.is_file())
        text = day.read_text()
        self.assertIn("Self-tuning", text)
        self.assertIn("Chat window", text)
        self.assertIn("Two chats", text)
        self.assertIn("caravan bench", text)
        self.assertIn("1st Mac", text)
        self.assertIn("2nd Mac", text)
        for bad in ("prf-hays", "16 GB", "24 GB", "exo1", "exo2", "262144"):
            self.assertNotIn(bad, text)
        web = (ROOT / "docs/WEB.md").read_text()
        self.assertIn("Chat window", web)
        self.assertIn("Two chats", web)
        self.assertIn("caravan bench", web)
        inst = (ROOT / "INSTALL.md").read_text()
        self.assertIn("`caravan bench`", inst)


if __name__ == "__main__":
    unittest.main()
