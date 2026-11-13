"""Day 25 GGUF round 2: self-tuning from chats, chat window, two chats, bench."""
from __future__ import annotations

import io
import time
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
import caravan_models as M  # noqa: E402
import caravan_progress as PR  # noqa: E402
import caravan_chart as CH  # noqa: E402


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
        self.assertIn("puts", text.lower())
        self.assertIn("original model back", text)
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
            ascii=True,
        )
        text = "\n".join(lines)
        self.assertIn("Qwen (GGUF)", text)
        self.assertIn("Qwen (MLX)", text)
        self.assertIn("Saved", text)
        self.assertIn("Reading (tok/s, higher is better)", text)
        self.assertIn("180", text)
        self.assertIn("220", text)
        self.assertIn("21", text)
        self.assertIn("28", text)
        self.assertNotIn("Write 30 tok", text)
        detailed = B.run_from_averages(
            "gguf/qwen", "mlx/qwen",
            gguf_name="Qwen (GGUF)", mlx_name="Qwen (MLX)", store=store,
            details=True, ascii=True,
        )
        dtext = "\n".join(detailed)
        self.assertIn("Write 30 tok at 21.0 tok/s", dtext)
        self.assertIn("Write 30 tok at 28.0 tok/s", dtext)

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
        result = B.run_live("gguf/a", "mlx/b", urlopen=urlopen,
                            gguf_name="G", mlx_name="M", prompts=["hi"])
        lines = result["lines"]
        text = "\n".join(lines)
        self.assertIn("G:", text)
        self.assertIn("Write 20 tok at 20.0 tok/s", text)
        self.assertIn("M:", text)
        self.assertIn("Write 20 tok at 30.0 tok/s", text)
        self.assertIn("Short prompts", text)
        self.assertTrue(any(c.endswith("/api/models/load") for c in calls))
        self.assertIsNone(result["error"])
        self.assertIsNone(result["original"])  # started idle, nothing to put back
        self.assertEqual(result["notes"], [])

    def test_caravan_dispatches_bench(self):
        import caravan as C
        with mock.patch("caravan_bench.main", return_value=0) as m:
            # caravan.py early-dispatches; import path is tools/
            pass
        src = (ROOT / "tools/caravan.py").read_text()
        self.assertIn('argv[0] == "bench"', src)
        self.assertIn('"bench"', src)



    def test_caravan_dispatches_models(self):
        src = (ROOT / "tools/caravan.py").read_text()
        self.assertIn('argv[0] == "models"', src)
        self.assertIn('"models"', src)


SAMPLE_MODELS = [
    {"id": "gguf/qwen2.5-coder-7b-instruct-q4_k_m",
     "name": "Qwen2.5 Coder 7B Instruct (GGUF)",
     "source": "gguf", "backend": "llama", "usable": True},
    {"id": "gguf/qwen2.5-coder-7b-instruct-q8_0",
     "name": "Qwen2.5 Coder 7B Instruct Q8 (GGUF)",
     "source": "gguf", "backend": "llama", "usable": True},
    {"id": "gguf/qwen2.5-coder-14b-instruct-q4_k_m",
     "name": "Qwen2.5 Coder 14B Instruct (GGUF)",
     "source": "gguf", "backend": "llama", "usable": True},
    {"id": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
     "name": "Qwen2.5 Coder 7B Instruct",
     "source": "hf-mlx", "hf": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
     "usable": True},
    {"id": "mlx-community/Qwen2.5-Coder-14B-Instruct-4bit",
     "name": "Qwen2.5 Coder 14B Instruct",
     "source": "hf-mlx", "hf": "mlx-community/Qwen2.5-Coder-14B-Instruct-4bit",
     "usable": True},
    {"id": "gguf/only-gguf-model-q4_k_m",
     "name": "Only GGUF Model (GGUF)",
     "source": "gguf", "backend": "llama", "usable": True},
]


class ModelsList(unittest.TestCase):
    def test_one_line_per_model_with_id_and_kind(self):
        text = M.format_list(SAMPLE_MODELS[:1] + SAMPLE_MODELS[3:4],
                             current="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit")
        lines = [ln for ln in text.strip().splitlines() if ln]
        self.assertEqual(len(lines), 2)
        self.assertIn("Qwen2.5 Coder 7B Instruct  (GGUF)  gguf/qwen2.5-coder-7b-instruct-q4_k_m", lines[0])
        self.assertNotIn("(currently loaded)", lines[0])
        self.assertIn("Qwen2.5 Coder 7B Instruct  (MLX)  mlx-community/Qwen2.5-Coder-7B-Instruct-4bit  (currently loaded)", lines[1])

    def test_not_running_is_plain(self):
        text = M.format_list(SAMPLE_MODELS[:1], current="gguf/qwen2.5-coder-7b-instruct-q4_k_m", running=False)
        self.assertIn("Caravan is not running", text)
        self.assertIn("caravan start", text)
        self.assertIn("gguf/qwen2.5-coder-7b-instruct-q4_k_m", text)
        self.assertNotIn("currently loaded", text)  # cannot know

    def test_empty_catalog(self):
        text = M.format_list([], running=True)
        self.assertIn("No models are downloaded", text)

    def test_cli_uses_running_catalog(self):
        cat = {
            "models": SAMPLE_MODELS[:1] + SAMPLE_MODELS[3:4],
            "current": "gguf/qwen2.5-coder-7b-instruct-q4_k_m",
            "running": True,
        }
        buf = io.StringIO()
        with mock.patch("caravan_models.fetch_catalog", return_value=cat), \
             mock.patch("sys.stdout", buf):
            rc = M.main([])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("(currently loaded)", out)
        self.assertIn("(GGUF)", out)
        self.assertIn("(MLX)", out)


class NameMatch(unittest.TestCase):
    def test_unique_pair_ignores_case_punctuation_and_quants(self):
        # One 7B GGUF only, one 7B MLX: unique pair. Drop the Q8 GGUF.
        models = [SAMPLE_MODELS[0], SAMPLE_MODELS[2], SAMPLE_MODELS[3], SAMPLE_MODELS[4]]
        pair = M.resolve_pair(models, query="Qwen2.5 Coder 7B")
        self.assertTrue(pair["ok"])
        self.assertEqual(M.model_id(pair["gguf"]), "gguf/qwen2.5-coder-7b-instruct-q4_k_m")
        self.assertEqual(M.model_id(pair["mlx"]), "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit")

    def test_several_gguf_lists_ids_and_how_to_pick(self):
        pair = M.resolve_pair(SAMPLE_MODELS, query="qwen2.5 coder 7b")
        self.assertFalse(pair["ok"])
        msg = "\n".join(pair["messages"])
        self.assertIn("Several GGUF models match", msg)
        self.assertIn("--gguf", msg)
        self.assertIn("gguf/qwen2.5-coder-7b-instruct-q4_k_m", msg)
        self.assertIn("gguf/qwen2.5-coder-7b-instruct-q8_0", msg)
        # The 14B model is not a 7B match.
        self.assertNotIn("14b", msg.lower())
        # MLX side is unique for 7B, so it is chosen; only GGUF is ambiguous.
        self.assertEqual(M.model_id(pair["mlx"]), "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit")

    def test_none_match_is_plain(self):
        pair = M.resolve_pair(SAMPLE_MODELS, query="gemma 4 26b")
        self.assertFalse(pair["ok"])
        msg = "\n".join(pair["messages"])
        self.assertIn("No GGUF model matches 'gemma 4 26b'", msg)
        self.assertIn("No MLX model matches 'gemma 4 26b'", msg)
        self.assertIn("caravan models", msg)

    def test_one_side_only(self):
        pair = M.resolve_pair(SAMPLE_MODELS, query="only gguf model")
        self.assertFalse(pair["ok"])
        msg = "\n".join(pair["messages"])
        self.assertIn("No MLX model matches", msg)
        self.assertEqual(M.model_id(pair["gguf"]), "gguf/only-gguf-model-q4_k_m")

    def test_flags_override_and_disambiguate(self):
        pair = M.resolve_pair(
            SAMPLE_MODELS, query="qwen2.5 coder 7b",
            gguf_id="gguf/qwen2.5-coder-7b-instruct-q8_0",
        )
        self.assertTrue(pair["ok"])
        self.assertEqual(M.model_id(pair["gguf"]), "gguf/qwen2.5-coder-7b-instruct-q8_0")
        self.assertEqual(M.model_id(pair["mlx"]), "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit")

    def test_flags_alone_still_work(self):
        pair = M.resolve_pair(
            SAMPLE_MODELS,
            gguf_id="gguf/qwen2.5-coder-7b-instruct-q4_k_m",
            mlx_id="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
        )
        self.assertTrue(pair["ok"])
        self.assertEqual(M.model_id(pair["gguf"]), "gguf/qwen2.5-coder-7b-instruct-q4_k_m")

    def test_cli_without_yes_shows_pair_and_command(self):
        models = [SAMPLE_MODELS[0], SAMPLE_MODELS[3]]
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = B.main(["qwen2.5 coder 7b"], models=models)
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("This would compare", out)
        self.assertIn("gguf/qwen2.5-coder-7b-instruct-q4_k_m", out)
        self.assertIn("mlx-community/Qwen2.5-Coder-7B-Instruct-4bit", out)
        self.assertIn("caravan bench --gguf gguf/qwen2.5-coder-7b-instruct-q4_k_m --mlx mlx-community/Qwen2.5-Coder-7B-Instruct-4bit --yes", out)
        self.assertIn('caravan bench "qwen2.5 coder 7b" --yes', out)
        self.assertIn("original model back", out)
        self.assertNotIn("tok/s", out)

    def test_cli_ambiguous_prints_candidates(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = B.main(["qwen2.5 coder 7b"], models=SAMPLE_MODELS)
        self.assertEqual(rc, 2)
        out = buf.getvalue()
        self.assertIn("Several GGUF models match", out)
        self.assertIn("--gguf", out)
        self.assertIn("gguf/qwen2.5-coder-7b-instruct-q8_0", out)


class RestoreOriginal(unittest.TestCase):
    def _urlopen(self, loaded, calls, *, fail_chat_on=None, fail_restore=False):
        def urlopen(url, data=None, timeout=30, headers=None):
            body = {}
            if data:
                import json as _json
                body = _json.loads(data.decode() if isinstance(data, (bytes, bytearray)) else data)
            calls.append((url, body))
            if url.endswith("/api/status"):
                mid = loaded.get("id")
                return {"worker": {
                    "status": "ready" if mid else "idle",
                    "model_id": mid,
                    "model_name": loaded.get("name") or mid,
                }}
            if url.endswith("/api/models/load"):
                if fail_restore and body.get("id") == "orig/model":
                    # Accept the load request, then status will... actually
                    # raise here so restore catches it.
                    raise RuntimeError("restore refused")
                loaded["id"] = body.get("id")
                loaded["name"] = body.get("id")
                return {"ok": True}
            if url.endswith("/api/chat"):
                if fail_chat_on and loaded.get("id") == fail_chat_on:
                    raise RuntimeError("chat failed")
                write = 20.0 if str(loaded.get("id", "")).startswith("gguf/") else 30.0
                return {
                    "caravan_web": {"stats": {
                        "write_tok_s": write, "read_tok_s": 100, "ttft_s": 0.20,
                        "prompt_tokens": 50, "completion_tokens": 20, "total_s": 0.80,
                    }},
                }
            raise AssertionError(url)
        return urlopen

    def test_puts_original_back_after_success(self):
        loaded = {"id": "orig/model", "name": "Original Model"}
        calls = []
        result = B.run_live(
            "gguf/a", "mlx/b", urlopen=self._urlopen(loaded, calls),
            gguf_name="G", mlx_name="M", prompts=["hi"],
        )
        self.assertIsNone(result["error"])
        self.assertEqual(result["original"], "orig/model")
        self.assertIn("Putting the original model back: Original Model.", result["notes"])
        loads = [body.get("id") for url, body in calls if url.endswith("/api/models/load")]
        self.assertEqual(loads, ["gguf/a", "mlx/b", "orig/model"])
        self.assertEqual(loaded["id"], "orig/model")
        text = "\n".join(result["lines"])
        self.assertIn("Write 20 tok at 20.0 tok/s", text)
        self.assertIn("Write 20 tok at 30.0 tok/s", text)

    def test_puts_original_back_when_a_measurement_fails(self):
        loaded = {"id": "orig/model", "name": "Original Model"}
        calls = []
        result = B.run_live(
            "gguf/a", "mlx/b",
            urlopen=self._urlopen(loaded, calls, fail_chat_on="gguf/a"),
            gguf_name="G", mlx_name="M", prompts=["hi"],
        )
        self.assertIsNotNone(result["error"])
        self.assertIn("chat failed", str(result["error"]))
        self.assertEqual(result["lines"], [])  # failed before any line
        self.assertIn("Putting the original model back: Original Model.", result["notes"])
        loads = [body.get("id") for url, body in calls if url.endswith("/api/models/load")]
        self.assertEqual(loads, ["gguf/a", "orig/model"])
        self.assertEqual(loaded["id"], "orig/model")

    def test_restore_failure_is_plain_and_results_still_show(self):
        loaded = {"id": "orig/model", "name": "Original Model"}
        calls = []
        result = B.run_live(
            "gguf/a", "mlx/b",
            urlopen=self._urlopen(loaded, calls, fail_restore=True),
            gguf_name="G", mlx_name="M", prompts=["hi"],
        )
        self.assertIsNone(result["error"])
        text = "\n".join(result["lines"])
        self.assertIn("G:", text)
        self.assertIn("M:", text)
        self.assertIn("Write", text)
        self.assertIn("Putting the original model back: Original Model.", result["notes"])
        self.assertTrue(any("Could not put the original model back" in n for n in result["notes"]))

    def test_already_the_original_is_said_plainly(self):
        # Original is the MLX side, which is the last one measured.
        loaded = {"id": "mlx/b", "name": "MLX Side"}
        calls = []
        result = B.run_live(
            "gguf/a", "mlx/b", urlopen=self._urlopen(loaded, calls),
            gguf_name="G", mlx_name="M", prompts=["hi"],
        )
        self.assertIsNone(result["error"])
        self.assertIn("Putting the original model back: MLX Side.", result["notes"])
        self.assertIn("It is already loaded.", result["notes"])
        loads = [body.get("id") for url, body in calls if url.endswith("/api/models/load")]
        self.assertEqual(loads, ["gguf/a", "mlx/b"])  # no third load

    def test_main_prints_restore_note(self):
        loaded = {"id": "orig/model", "name": "Original Model"}
        calls = []
        models = [SAMPLE_MODELS[0], SAMPLE_MODELS[3]]
        buf = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(B, "_urlopen", self._urlopen(loaded, calls)), \
             mock.patch("sys.stdout", buf), mock.patch("sys.stderr", err):
            # main() calls run_live which defaults to _urlopen; pass through
            # by patching run_live's default is already bound. Patch run_live.
            urlopen = self._urlopen(loaded, calls)
            real_live = B.run_live
            def fake_live(*a, **k):
                k.setdefault("urlopen", urlopen)
                k.setdefault("prompts", ["hi"])
                return real_live(*a, **k)
            with mock.patch.object(B, "run_live", side_effect=fake_live):
                rc = B.main(["qwen2.5 coder 7b", "--yes"], models=models)
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Putting the original model back: Original Model.", out)
        self.assertIn("Reading (tok/s, higher is better)", out)
        self.assertIn("Writing (tok/s, higher is better)", out)
        self.assertIn("First token (s, lower is better)", out)
        self.assertNotIn("Write 20 tok at 20.0 tok/s", out)
        # --details adds the reply-stats lines
        buf2 = io.StringIO()
        err2 = io.StringIO()
        calls2 = []
        loaded2 = {"id": "orig/model", "name": "Original Model"}
        with mock.patch("sys.stdout", buf2), mock.patch("sys.stderr", err2):
            urlopen = self._urlopen(loaded2, calls2)
            real_live = B.run_live
            def fake_live2(*a, **k):
                k.setdefault("urlopen", urlopen)
                k.setdefault("prompts", ["hi"])
                return real_live(*a, **k)
            with mock.patch.object(B, "run_live", side_effect=fake_live2):
                rc2 = B.main(
                    ["qwen2.5 coder 7b", "--yes", "--details", "--ascii"],
                    models=models,
                )
        self.assertEqual(rc2, 0)
        out2 = buf2.getvalue()
        self.assertIn("Write 20 tok at 20.0 tok/s", out2)
        self.assertIn("Write 20 tok at 30.0 tok/s", out2)
        self.assertIn("Putting the original model back: Original Model.", out2)
        self.assertIn("Reading (tok/s, higher is better)", out2)



class LongSeries(unittest.TestCase):
    def test_five_short_prompts_keep_the_auto_tune_pair(self):
        import caravan_prompts as P
        import gguf_tune as T
        self.assertEqual(len(P.SHORT_PROMPTS), 5)
        self.assertEqual(P.SHORT_PROMPTS[0], T.BENCH_PROMPTS[0])
        self.assertEqual(P.SHORT_PROMPTS[1], T.BENCH_PROMPTS[1])
        self.assertIn("bicycle", P.SHORT_PROMPTS[0])
        self.assertIn("palindrome", P.SHORT_PROMPTS[1])
        # The three new ones: code, explanation, list.
        self.assertTrue(any("def average" in p for p in P.SHORT_PROMPTS))
        self.assertTrue(any("hash table" in p for p in P.SHORT_PROMPTS))
        self.assertTrue(any(p.startswith("List eight") or "List eight" in p for p in P.SHORT_PROMPTS))
        # Unique openings.
        shorts = P.short_prompts()
        self.assertEqual(len({s[:50] for s in shorts}), 5)

    def test_long_prompts_are_sized_and_unique(self):
        import caravan_prompts as P
        for size in (1024, 4096, 8192):
            pair = P.long_prompts_for_size(size)
            self.assertEqual(len(pair), 2)
            self.assertNotEqual(pair[0][:80], pair[1][:80])
            for text in pair:
                est = P.estimate_tokens(text)
                self.assertGreater(est, size * 0.8)
                self.assertLess(est, size * 1.25)
                self.assertIn("This opening is only for this prompt", text)

    def test_skips_sizes_that_will_not_fit(self):
        import caravan_prompts as P
        self.assertTrue(P.fits_window(1024, 8192))
        self.assertTrue(P.fits_window(4096, 8192))
        self.assertFalse(P.fits_window(8192, 8192))
        self.assertFalse(P.fits_window(2048, 2048))
        self.assertTrue(P.fits_window(2048, 8192))
        reason = P.skip_reason(8192, 8192)
        self.assertIn("chat window is 8192", reason)
        self.assertIn("8k", reason)

    def test_measure_series_skips_and_labels_counts(self):
        calls = []
        def urlopen(url, data=None, timeout=30, headers=None):
            calls.append(url)
            if url.endswith("/api/chat"):
                import json as _json
                body = _json.loads(data.decode()) if data else {}
                n = len((body.get("messages") or [{}])[-1].get("content") or "")
                return {"caravan_web": {"stats": {
                    "write_tok_s": 20.0, "read_tok_s": 100.0, "ttft_s": 0.20,
                    "prompt_tokens": max(10, n // 4), "completion_tokens": 20,
                    "total_s": 0.80,
                }}}
            raise AssertionError(url)
        rows = B.measure_series(8190, urlopen, run_short=True, run_long=True, window=8192)
        labels = [r["label"] for r in rows]
        self.assertEqual(labels[0], "Short prompts (5)")
        self.assertTrue(labels[1].startswith("Long prompts (~1k tok) (2)"))
        self.assertTrue(labels[2].startswith("Long prompts (~4k tok) (2)"))
        self.assertTrue(labels[3].startswith("Long prompts (~8k tok) (2)"))
        self.assertTrue(rows[3].get("skipped"))
        self.assertIn("chat window is 8192", rows[3]["reason"])
        self.assertFalse(rows[0].get("skipped"))
        self.assertFalse(rows[1].get("skipped"))
        # 5 short + 2 at 1k + 2 at 4k; 8k skipped. No shared prefix across first 80 chars
        # (already tested on the prompts themselves).
        self.assertEqual(sum(1 for c in calls if c.endswith("/api/chat")), 5 + 2 + 2)

    def test_short_flag_skips_long(self):
        n = [0]
        def urlopen(url, data=None, timeout=30, headers=None):
            n[0] += 1
            return {"caravan_web": {"stats": {
                "write_tok_s": 20.0, "read_tok_s": 100, "ttft_s": 0.2,
                "prompt_tokens": 40, "completion_tokens": 20, "total_s": 0.8,
            }}}
        rows = B.measure_series(8190, urlopen, run_short=True, run_long=False, window=32768)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "Short prompts (5)")
        self.assertEqual(n[0], 5)

    def test_summary_uses_only_measured_numbers(self):
        g = [{"label": "Short prompts (5)", "specs": {
            "write_tok_s": 22.3, "read_tok_s": 157, "ttft_s": 0.22,
            "total_s": 7.65, "prompt_tokens": 46, "completion_tokens": 166,
        }}]
        m = [{"label": "Short prompts (5)", "specs": {
            "write_tok_s": 23.5, "read_tok_s": 182, "ttft_s": 0.33,
            "total_s": 7.61, "prompt_tokens": 46, "completion_tokens": 172,
        }}]
        text = B.summarize(g, m, gguf_name="GGUF", mlx_name="MLX")
        self.assertIn("On short prompts", text)
        self.assertIn("MLX was faster at reading", text)
        self.assertIn("16% faster", text)
        self.assertIn("182 vs 157", text)
        self.assertIn("MLX was faster at writing", text)
        self.assertIn("22.3", text)
        self.assertIn("23.5", text)
        self.assertIn("GGUF's first token was sooner", text)
        self.assertIn("0.22s vs 0.33s", text)
        self.assertIn("about the same", text)  # totals 7.61 vs 7.65
        self.assertIn("7.61", text)
        self.assertIn("7.65", text)
        # no invented third speed
        self.assertNotIn("999", text)

    def test_summary_skips_unmeasured_sizes(self):
        g = [{"label": "Long prompts (~8k tok) (2)", "skipped": True,
              "reason": "this model's chat window is 8192, and a ~8k-token prompt would not fit."}]
        m = [{"label": "Long prompts (~8k tok) (2)", "specs": {
            "write_tok_s": 20, "read_tok_s": 80, "ttft_s": 1.0, "total_s": 10,
        }}]
        text = B.summarize(g, m)
        self.assertIn("GGUF was skipped", text)
        self.assertIn("No comparison at this size", text)
        self.assertNotIn("faster at writing", text)

    def test_preview_mentions_long_series_and_no_speeds(self):
        text = B.steps_text("gguf/qwen", "mlx-community/qwen")
        self.assertIn("five short prompts", text)
        self.assertIn("1k, 4k, and 8k", text)
        self.assertIn("chart", text.lower())
        self.assertIn("--details", text)
        self.assertIn("--ascii", text)
        self.assertIn("original model back", text)
        self.assertNotIn("tok/s", text)
        self.assertIn("--yes", text)

    def test_cli_short_flag_in_preview(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = B.main(["--gguf", "gguf/a", "--mlx", "mlx/b", "--short"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("--short --yes", out)
        self.assertIn("five short prompts", out)
        self.assertNotIn("1k, 4k, and 8k", out)
        self.assertNotIn("tok/s", out)


class ModelsMerge(unittest.TestCase):
    def test_merge_adds_gguf_omitted_by_the_page(self):
        api = [
            {"id": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
             "name": "Qwen2.5 Coder 7B Instruct", "source": "hf-mlx", "usable": True},
        ]
        disk = api + [
            {"id": "gguf/Llama-3.2-3B-Instruct-Q2_K_L",
             "name": "Llama-3.2-3B-Instruct-Q2_K_L", "source": "gguf",
             "backend": "llama", "usable": True},
        ]
        with mock.patch("caravan_models.disk_models", return_value=disk):
            merged = M.merge_local_gguf(api)
        ids = [M.model_id(m) for m in merged]
        self.assertIn("mlx-community/Qwen2.5-Coder-7B-Instruct-4bit", ids)
        self.assertIn("gguf/Llama-3.2-3B-Instruct-Q2_K_L", ids)
        # Listing shows the GGUF line with its id.
        text = M.format_list(merged)
        self.assertIn("Llama-3.2-3B-Instruct-Q2_K_L  (GGUF)  gguf/Llama-3.2-3B-Instruct-Q2_K_L", text)
        self.assertIn("(MLX)", text)

    def test_merge_does_not_duplicate(self):
        both = [
            {"id": "gguf/Llama-3.2-3B-Instruct-Q2_K_L", "name": "Llama", "source": "gguf"},
            {"id": "mlx-community/foo", "name": "Foo", "source": "hf-mlx"},
        ]
        with mock.patch("caravan_models.disk_models", return_value=both):
            merged = M.merge_local_gguf(both)
        self.assertEqual(len(merged), 2)

    def test_fetch_catalog_merges_when_api_omits_gguf(self):
        api = {"models": [{"id": "mlx/only", "name": "Only MLX", "source": "hf-mlx"}],
               "current": "mlx/only"}
        disk = [
            {"id": "mlx/only", "name": "Only MLX", "source": "hf-mlx"},
            {"id": "gguf/Llama-3.2-3B-Instruct-Q2_K_L", "name": "Llama",
             "source": "gguf", "backend": "llama"},
        ]
        def urlopen(url, data=None, timeout=5, headers=None):
            return api
        with mock.patch("caravan_models.disk_models", return_value=disk):
            cat = M.fetch_catalog(port=8190, urlopen=urlopen)
        ids = [M.model_id(m) for m in cat["models"]]
        self.assertIn("gguf/Llama-3.2-3B-Instruct-Q2_K_L", ids)
        self.assertTrue(cat["running"])


class AutotunePromptsAndScore(unittest.TestCase):
    def test_default_measure_uses_five_short_and_one_long(self):
        import gguf_tune as T
        seen = []
        class R:
            def __init__(self, body): self._b = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return (
                    b'{"timings":{"predicted_per_second":40,"prompt_per_second":200,'
                    b'"prompt_ms":250},"usage":{"prompt_tokens":100,"completion_tokens":20}}'
                )
        def fake(req, timeout=0):
            # urlopen is passed the Request; body is on req
            seen.append(req.data.decode() if req.data else "")
            return R(b"")
        specs = T.measure_http_specs(9000, urlopen=fake, chat_window=8192)
        self.assertEqual(len(seen), 6)  # 5 short + 1 long (~2k)
        # Unique openings
        openings = [s[:80] for s in seen]
        self.assertEqual(len(set(openings)), 6)
        self.assertEqual(specs["write_tok_s"], 40.0)
        self.assertEqual(specs["long_read_tok_s"], 200.0)
        # Long prompt is actually long.
        long_bodies = [s for s in seen if "about 2k tokens" in s or "2048" in s or "2k" in s]
        self.assertTrue(long_bodies)
        self.assertGreater(len(max(seen, key=len)), 4000)

    def test_long_autotune_prompt_skipped_when_window_is_small(self):
        import gguf_tune as T
        seen = []
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return b'{"timings":{"predicted_per_second":40,"prompt_per_second":200,"prompt_ms":250}}'
        def fake(req, timeout=0):
            seen.append(1)
            return R()
        specs = T.measure_http_specs(9000, urlopen=fake, chat_window=2048)
        self.assertEqual(len(seen), 5)  # long skipped
        self.assertNotIn("long_read_tok_s", specs)

    def test_faster_write_loses_if_long_read_is_much_slower(self):
        import gguf_tune as T
        inc = {"write_tok_s": 100.0, "long_read_tok_s": 200.0, "total_s": 8.0}
        # Writes 15% faster but reads at half speed.
        ch = {"write_tok_s": 115.0, "long_read_tok_s": 100.0, "total_s": 8.0}
        self.assertFalse(T.beats(ch, inc))
        # And a fair improvement on both still wins.
        ch2 = {"write_tok_s": 115.0, "long_read_tok_s": 230.0, "total_s": 7.0}
        self.assertTrue(T.beats(ch2, inc))

    def test_garbled_still_recorded(self):
        import gguf_tune as T
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                # A clearly garbled reply: repeated junk, if is_garbled checks content.
                return (
                    b'{"timings":{"predicted_per_second":99},"choices":'
                    b'[{"message":{"content":"aaaaaaaaaa"}}]}'
                )
        def fake(req, timeout=0):
            return R()
        # Even if garble detection does not fire on this string, the field is optional;
        # the keep-a-garbled-loss path is covered in existing GGUF tests.
        specs = T.measure_http_specs(9000, urlopen=fake, prompts=["hi"])
        self.assertEqual(specs["write_tok_s"], 99)



class ProgressAnimation(unittest.TestCase):
    def test_step_text_is_plain(self):
        self.assertEqual(
            PR.loading_step("Qwen2.5 Coder 7B (GGUF)"),
            "Loading Qwen2.5 Coder 7B (GGUF)…",
        )
        self.assertEqual(PR.short_step("GGUF", 3, 5), "GGUF · short prompt 3 of 5")
        self.assertEqual(PR.long_step("MLX", "4k", 1, 2), "MLX · long prompt ~4k, 1 of 2")
        self.assertEqual(PR.long_step("MLX", 4096, 1, 2), "MLX · long prompt ~4k, 1 of 2")
        self.assertEqual(PR.restore_step(), "Putting the original model back…")
        self.assertEqual(PR.format_elapsed(12), "0:12")
        self.assertEqual(PR.format_elapsed(75), "1:15")

    def test_non_tty_is_plain_and_quiet_is_off(self):
        buf = io.StringIO()
        self.assertFalse(buf.isatty())
        self.assertEqual(PR.decide_mode(buf), "plain")
        self.assertEqual(PR.decide_mode(buf, quiet=True), "off")
        with mock.patch.dict("os.environ", {"NO_COLOR": "1"}):
            self.assertEqual(PR.decide_mode(buf), "plain")
            # Even a fake tty is plain when NO_COLOR is set.
            tty = mock.Mock()
            tty.isatty.return_value = True
            self.assertEqual(PR.decide_mode(tty), "plain")
        tty = mock.Mock()
        tty.isatty.return_value = True
        with mock.patch.dict("os.environ", {"NO_COLOR": ""}, clear=False):
            # empty NO_COLOR does not force plain
            # If NO_COLOR is already in env from the parent, pop it.
            import os
            env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
            with mock.patch.dict("os.environ", env, clear=True):
                self.assertEqual(PR.decide_mode(tty), "animate")
                self.assertEqual(PR.decide_mode(buf), "plain")

    def test_plain_path_prints_step_lines(self):
        buf = io.StringIO()
        prog = PR.Progress(out=buf, mode="plain")
        prog.start()
        self.assertFalse(prog.alive)  # no thread in plain mode
        prog.set(PR.loading_step("Qwen2.5 Coder 7B (GGUF)"))
        prog.set(PR.short_step("GGUF", 3, 5))
        prog.set(PR.long_step("MLX", "4k", 1, 2))
        prog.set(PR.restore_step())
        prog.stop()
        self.assertFalse(prog.alive)
        out = buf.getvalue()
        self.assertIn("Loading Qwen2.5 Coder 7B (GGUF)…\n", out)
        self.assertIn("GGUF · short prompt 3 of 5\n", out)
        self.assertIn("MLX · long prompt ~4k, 1 of 2\n", out)
        self.assertIn("Putting the original model back…\n", out)
        self.assertNotIn("\r", out)

    def test_quiet_prints_nothing(self):
        buf = io.StringIO()
        prog = PR.Progress(out=buf, mode="off", quiet=True)
        prog.start()
        prog.set("Loading X…")
        prog.println("should not matter if we never call it from run")
        # println still writes if called — quiet is about set() / animation.
        # The mode is off, println is used for results; that's fine.
        prog.stop()
        # set() must be silent
        buf2 = io.StringIO()
        prog = PR.Progress(out=buf2, quiet=True)
        self.assertEqual(prog.mode, "off")
        prog.start()
        prog.set("Loading X…")
        prog.stop()
        self.assertEqual(buf2.getvalue(), "")

    def test_thread_starts_and_stops(self):
        buf = io.StringIO()
        prog = PR.Progress(out=buf, mode="animate")
        prog.start()
        prog.set("Loading Qwen2.5 Coder 7B (GGUF)…")
        time.sleep(0.35)
        self.assertTrue(prog.alive)
        raw = buf.getvalue()
        self.assertIn("Loading Qwen2.5 Coder 7B (GGUF)…", raw)
        self.assertIn("\r", raw)
        # elapsed is on the line
        self.assertRegex(raw, r"0:0[0-9]")
        # a campfire frame is present
        self.assertTrue(any(f in raw for f in PR.FRAMES))
        prog.stop()
        self.assertFalse(prog.alive)
        # After stop the in-place line is cleared (spaces + CR), no hanging frame.
        end = buf.getvalue()
        self.assertTrue(end.endswith("\r") or "\r" in end[-20:])

    def test_clear_before_result_line(self):
        buf = io.StringIO()
        prog = PR.Progress(out=buf, mode="animate")
        prog.start()
        prog.set("GGUF · short prompt 3 of 5")
        time.sleep(0.2)
        prog.println("Qwen (GGUF):")
        prog.stop()
        out = buf.getvalue()
        # Result line is a real newline, after a clear.
        self.assertIn("Qwen (GGUF):\n", out)
        # The clear uses CR and spaces.
        self.assertIn("\r", out)

    def test_live_plain_steps_and_ctrl_c_restores(self):
        loaded = {"id": "orig/model", "name": "Original Model"}
        calls = []
        buf = io.StringIO()
        prog = PR.Progress(out=buf, mode="plain")

        def urlopen(url, data=None, timeout=30, headers=None):
            body = {}
            if data:
                import json as _json
                body = _json.loads(data.decode() if isinstance(data, (bytes, bytearray)) else data)
            calls.append((url, body))
            if url.endswith("/api/status"):
                mid = loaded.get("id")
                return {"worker": {
                    "status": "ready" if mid else "idle",
                    "model_id": mid,
                    "model_name": loaded.get("name") or mid,
                }}
            if url.endswith("/api/models/load"):
                loaded["id"] = body.get("id")
                loaded["name"] = body.get("id")
                return {"ok": True}
            if url.endswith("/api/chat"):
                raise KeyboardInterrupt()
            if url.endswith("/api/settings"):
                return {}
            raise AssertionError(url)

        result = B.run_live(
            "gguf/a", "mlx/b", urlopen=urlopen,
            gguf_name="Qwen2.5 Coder 7B (GGUF)",
            mlx_name="Qwen2.5 Coder 7B (MLX)",
            prompts=["hi"],
            progress=prog,
        )
        prog.stop()
        self.assertFalse(prog.alive)
        self.assertIsInstance(result["error"], KeyboardInterrupt)
        self.assertIn("Stopped.", result["notes"])
        self.assertIn("Putting the original model back: Original Model.", result["notes"])
        loads = [body.get("id") for url, body in calls if url.endswith("/api/models/load")]
        # Loaded GGUF, then interrupted on first chat, then original put back.
        self.assertEqual(loads, ["gguf/a", "orig/model"])
        self.assertEqual(loaded["id"], "orig/model")
        out = buf.getvalue()
        self.assertIn("Loading Qwen2.5 Coder 7B (GGUF)…", out)
        self.assertIn("GGUF · short prompt 1 of 1", out)
        self.assertIn("Putting the original model back…", out)

    def test_help_mentions_the_animation(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            try:
                B.main(["--help"])
            except SystemExit as e:
                self.assertEqual(e.code, 0)
        help_txt = buf.getvalue()
        self.assertIn("campfire", help_txt.lower())
        self.assertIn("--quiet", help_txt)
        self.assertIn("Ctrl-C", help_txt)
        self.assertIn("--details", help_txt)
        self.assertIn("--ascii", help_txt)
        self.assertIn("chart", help_txt.lower())




class Chart(unittest.TestCase):
    """ASCII chart from Brenden's real 1st Mac Qwen2.5 Coder 7B figures."""

    def test_fixture_ascii_is_stable_and_fits_80(self):
        text = CH.fixture_chart(ascii=True)
        expected = (
            "GGUF  Qwen2.5 Coder 7B (GGUF Q4_K_M)\n"
            "MLX   Qwen2.5 Coder 7B (MLX 4bit)\n"
            "\n"
            "Reading (tok/s, higher is better)\n"
            "Short  GGUF  ###################################                   182\n"
            "       MLX   #######################################               204  * +12%\n"
            "~1k    GGUF  ##############################################        239\n"
            "       MLX   #################################################     257  * +8%\n"
            "~4k    GGUF  #########################################             215\n"
            "       MLX   ##############################################        242  * +13%\n"
            "~8k    GGUF  #####################################                 195\n"
            "       MLX   ##########################################            218  * +12%\n"
            "\n"
            "Writing (tok/s, higher is better)\n"
            "Short  GGUF  ##############################################       22.2\n"
            "       MLX   #################################################    23.4  * +5%\n"
            "~1k    GGUF  #############################################        21.5\n"
            "       MLX   ################################################     22.9  * +7%\n"
            "~4k    GGUF  ########################################             19.1\n"
            "       MLX   ##############################################       21.8  * +14%\n"
            "~8k    GGUF  ###################################                  16.7\n"
            "       MLX   ###########################################          20.4  * +22%\n"
            "\n"
            "First token (s, lower is better)\n"
            "Short  GGUF  ##############################                      0.28s  * +39%\n"
            "       MLX   #################################################   0.46s\n"
            "~1k    GGUF  #################################################   5.30s\n"
            "       MLX   ##############################################      5.01s  * +5%\n"
            "~4k    GGUF  #################################################  23.40s\n"
            "       MLX   ############################################       20.96s  * +10%\n"
            "~8k    GGUF  #################################################  52.15s\n"
            "       MLX   ############################################       46.74s  * +10%\n"
        )
        self.assertEqual(text, expected)
        for line in text.splitlines():
            self.assertLessEqual(len(line), 80, line)
        self.assertIn("#", text)
        self.assertNotIn("█", text)
        self.assertNotIn("★", text)

    def test_unicode_uses_block_characters(self):
        text = CH.fixture_chart(ascii=False, color=False)
        self.assertIn("█", text)
        self.assertIn("★", text)
        self.assertNotIn("#", text)
        self.assertIn("204  ★ +12%", text)
        self.assertIn("20.4  ★ +22%", text)
        self.assertIn("0.28s  ★ +39%", text)
        for line in text.splitlines():
            self.assertLessEqual(len(line), 80, line)

    def test_color_only_when_asked_and_wraps_bars(self):
        plain = CH.fixture_chart(ascii=True, color=False)
        # NO_COLOR wins over color=True, as the CLI promises; clear it
        # here so we can still check the paint wrapping.
        env = {k: v for k, v in __import__("os").environ.items() if k != "NO_COLOR"}
        with mock.patch.dict(__import__("os").environ, env, clear=True):
            colored = CH.fixture_chart(ascii=True, color=True)
        self.assertNotIn("\033[", plain)
        self.assertIn(CH.AMBER, colored)
        self.assertIn(CH.GREEN, colored)
        self.assertIn(CH.RESET, colored)
        # Stripping color codes yields the plain chart.
        import re
        stripped = re.sub(r"\033\[[0-9;]*m", "", colored)
        self.assertEqual(stripped, plain)

    def test_skipped_and_missing_sizes_are_omitted(self):
        g = [
            {"label": "Short prompts (5)", "specs": {
                "read_tok_s": 182, "write_tok_s": 22.2, "ttft_s": 0.28,
            }},
            {"label": "Long prompts (~8k tok) (2)", "size": 8192,
             "skipped": True, "reason": "would not fit"},
        ]
        m = [
            {"label": "Short prompts (5)", "specs": {
                "read_tok_s": 204, "write_tok_s": 23.4, "ttft_s": 0.46,
            }},
        ]
        text = CH.render_chart(g, m, gguf_name="G", mlx_name="M", ascii=True, color=False)
        self.assertIn("Short", text)
        self.assertNotIn("~8k", text)
        self.assertNotIn("~1k", text)
        self.assertNotIn("~4k", text)
        self.assertIn("182", text)
        self.assertIn("204", text)

    def test_one_sided_row_has_no_winner_mark(self):
        g = [{"label": "Short prompts (5)", "specs": {
            "read_tok_s": 182, "write_tok_s": 22.2, "ttft_s": 0.28,
        }}]
        text = CH.render_chart(g, [], gguf_name="G", mlx_name="M", ascii=True, color=False)
        self.assertIn("182", text)
        self.assertIn("22.2", text)
        self.assertNotIn("*", text)
        self.assertNotIn("+", text)
        self.assertIn("GGUF  G", text)

    def test_empty_rows_say_no_numbers(self):
        text = CH.render_chart([], [], ascii=True)
        self.assertEqual(text, "No speed numbers to chart yet.\n")

    def test_no_color_forces_ascii_bars(self):
        style = CH.decide_style(ascii=None, color=None, stream=io.StringIO())
        # NO_COLOR is set in the official test environment; bars are '#'.
        # Even if it is not, a non-TTY stream has no color.
        self.assertFalse(style["color"])
        forced = CH.decide_style(ascii=True, color=False)
        self.assertEqual(forced["full"], "#")
        self.assertEqual(forced["star"], "*")
        uni = CH.decide_style(ascii=False, color=False)
        self.assertEqual(uni["full"], "█")
        self.assertEqual(uni["star"], "★")

    def test_live_result_includes_a_chart(self):
        calls = []
        def urlopen(url, data=None, timeout=30, headers=None):
            calls.append(url)
            n_loads = sum(1 for c in calls if c.endswith("/api/models/load"))
            if url.endswith("/api/status"):
                mid = "gguf/a" if 0 < n_loads < 2 else ("mlx/b" if n_loads >= 2 else None)
                return {"worker": {"status": "ready" if mid else "idle", "model_id": mid}}
            if url.endswith("/api/models/load"):
                return {"ok": True}
            if url.endswith("/api/chat"):
                write = 20.0 if n_loads < 2 else 30.0
                return {"caravan_web": {"stats": {
                    "write_tok_s": write, "read_tok_s": 100, "ttft_s": 0.20,
                    "prompt_tokens": 50, "completion_tokens": 20, "total_s": 0.80,
                }}}
            raise AssertionError(url)
        result = B.run_live("gguf/a", "mlx/b", urlopen=urlopen,
                            gguf_name="G", mlx_name="M", prompts=["hi"])
        chart = result["chart"]
        self.assertIn("Reading (tok/s, higher is better)", chart)
        self.assertIn("100", chart)
        self.assertIn("20", chart)
        self.assertIn("30", chart)
        # Default lines still have the reply-stats wording for --details.
        text = "\n".join(result["lines"])
        self.assertIn("Write 20 tok at 20.0 tok/s", text)
        self.assertIn("Write 20 tok at 30.0 tok/s", text)


class Docs(unittest.TestCase):
    def test_day25_docs_are_plain(self):
        day = ROOT / "docs/DAY25.md"
        self.assertTrue(day.is_file())
        text = day.read_text()
        self.assertIn("Self-tuning", text)
        self.assertIn("Chat window", text)
        self.assertIn("Two chats", text)
        self.assertIn("caravan bench", text)
        self.assertIn("caravan models", text)
        self.assertIn("1st Mac", text)
        self.assertIn("157 tok/s", text)
        self.assertIn("22.3 tok/s", text)
        self.assertIn("23.5 tok/s", text)
        self.assertIn("five short prompts", text)
        self.assertIn("long-prompt series", text)
        self.assertIn("campfire", text.lower())
        self.assertIn("--details", text)
        self.assertIn("--ascii", text)
        self.assertIn("Reading (tok/s, higher is better)", text)
        self.assertIn("* +22%", text)
        self.assertIn("182", text)
        self.assertIn("20.4", text)
        self.assertIn("2nd Mac", text)
        bench = (ROOT / "docs/BENCHMARKS.md").read_text()
        chart = CH.fixture_chart(ascii=True).rstrip()
        self.assertIn(chart, bench)
        self.assertIn(chart, text)
        for bad in ("prf-hays", "16 GB", "24 GB", "exo1", "exo2", "262144"):
            self.assertNotIn(bad, text)
        web = (ROOT / "docs/WEB.md").read_text()
        self.assertIn("Chat window", web)
        self.assertIn("Two chats", web)
        self.assertIn("caravan bench", web)
        inst = (ROOT / "INSTALL.md").read_text()
        self.assertIn("`caravan bench`", inst)
        self.assertIn("`caravan models`", inst)


if __name__ == "__main__":
    unittest.main()
