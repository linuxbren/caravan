"""Day 24 live review: Tune again is redoable, sits next to Self-tuning,
and a no-improvement run shows one plain line instead of two identical ones.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "agent"), str(REPO / "proxy")]

import gguf_split as G
import optimize_schedule as AB
import tuned_settings as TS
import web_optimize as WO
import web_settings
import web_speed as S
from web_workers import WorkerManager

HTML = (REPO / "proxy/web/index.html").read_text()
ACTIVE = dict(
    self_tune=True, guess_ahead=False, guess_ahead_loaded=False,
    shared_start=True, pipeline_chats=1, keepalive=None,
    kv_bits=4, fuse_kernels="on", pinned=[],
    two_chats_available=True, kv_quant_supported=True,
)


class TuneAgainButton(unittest.TestCase):
    def test_sits_next_to_self_tuning_outside_advanced(self):
        rows = HTML.index('id="optRows"')
        start = HTML.index('id="btnOptStart"')
        reset = HTML.index('id="btnTuneReset"')
        adv = HTML.index('id="optAdvanced"')
        apply = HTML.index('id="btnApply"')
        self.assertTrue(rows < start < adv)
        self.assertTrue(rows < reset < adv)
        self.assertTrue(adv < apply)
        self.assertIn(">Tune again</button>", HTML)
        self.assertIn(">Reset tuning</button>", HTML)
        # No leftover Start / Optimize now title, and no duplicate in Advanced.
        self.assertNotIn('id="btnOptStart">Start</button>', HTML)
        self.assertNotIn(">Optimize now</b>", HTML)
        adv_end = HTML.index("</details>", adv)
        self.assertNotIn("btnOptStart", HTML[adv:adv_end])
        self.assertNotIn("Tune again", HTML[adv:adv_end])
        self.assertNotIn("Optimize now", HTML[adv:adv_end])

    def test_press_always_sends_fresh(self):
        self.assertIn('JSON.stringify({ fresh: true })', HTML)
        self.assertIn("/api/settings/reset-tuning", HTML)
        self.assertIn("/api/optimize/start", HTML)

    def test_no_now_line_on_self_tune(self):
        self.assertIn('if (o.id === "self_tune")', HTML)
        self.assertIn('now.textContent = ""', HTML)
        # The contradictory leftover notice is cleared once a model is loaded.
        self.assertIn("takes effect when you load", HTML)
        self.assertIn("state.loadedModel", HTML)

    def test_self_tune_help_is_generic(self):
        opt = next(o for o in web_settings.OPTIONS if o["id"] == "self_tune")
        self.assertIn("for each model", opt["help"])
        self.assertNotIn("for each MLX model", opt["help"])
        self.assertIn("for each model", HTML)
        self.assertNotIn("for each MLX model", HTML)
        # OPTIONS.help and the page copy stay in lockstep.
        self.assertIn(opt["help"], HTML)


class FreshSchedule(unittest.TestCase):
    def test_fresh_retries_losses_and_pins(self):
        opt = WO.Optimizer(SimpleNamespace())
        entry = {
            "optimize_hardware": {
                "fp": {"losses": ["kv_bits:8", "kv_bits:16", "fuse_kernels:off",
                                  "shared_prefix:off"]},
            },
            "winner": {"shared_prefix": True, "kv_bits": 4, "fuse_kernels": "on"},
        }
        settings = web_settings.normalize({
            "kv_bits": "4", "fuse_kernels": "on", "shared_start": "on",
            "pipeline_chats": "2",
        })
        active = dict(ACTIVE, pinned=["kv_bits"], pipeline_chats=2)
        skipped = opt._schedule(entry, settings, active, "fp", fresh=False)
        by = {i["name"]: i for i in skipped}
        self.assertEqual(by["kv_bits"]["skip"], "pinned")
        self.assertEqual(by["fuse_kernels"]["skip"], "pinned")
        self.assertEqual(by["shared_prefix"]["skip"], "pinned")
        # Fresh Tune again retries those, without writing the saved losses.
        fresh = opt._schedule(entry, settings, active, "fp", fresh=True)
        fby = {i["name"]: i for i in fresh}
        self.assertIsNone(fby["kv_bits"]["skip"])
        self.assertIsNotNone(fby["kv_bits"]["challenger"])
        self.assertIsNone(fby["fuse_kernels"]["skip"])
        self.assertEqual(fby["fuse_kernels"]["challenger"], "off")
        self.assertIsNone(fby["shared_prefix"]["skip"])
        self.assertEqual(fby["shared_prefix"]["challenger"], False)
        # On-disk (the original entry) still has the losses until a run commits.
        self.assertIn("kv_bits:8", entry["optimize_hardware"]["fp"]["losses"])

    def test_fresh_still_skips_unavailable(self):
        opt = WO.Optimizer(SimpleNamespace())
        active = dict(ACTIVE, guess_ahead_loaded=False, two_chats_available=False,
                      keepalive=None, n_layers=None)
        items = opt._schedule({}, {}, active, "fp", fresh=True)
        by = {i["name"]: i for i in items}
        self.assertEqual(by["guess_ahead"]["skip"], "unavailable")
        self.assertEqual(by["keepalive"]["skip"], "unavailable")

    def test_gguf_fresh_retries_losses(self):
        lost = G.gguf_schedule({"cache_type": "q8_0", "flash_attn": "on",
                                "ubatch": 512}, ["cache_type=f16"])
        self.assertEqual(next(i for i in lost if i["name"] == "cache_type")["skip"],
                         "already lost")
        fresh = G.gguf_schedule({"cache_type": "q8_0", "flash_attn": "on",
                                 "ubatch": 512}, [])
        item = next(i for i in fresh if i["name"] == "cache_type")
        self.assertIsNone(item["skip"])
        self.assertEqual(item["challenger"], "f16")


class NothingFaster(unittest.TestCase):
    def test_identical_before_after_is_one_sentence(self):
        same = {
            "write_tok_s": 92.457, "ttft_s": 0.2863,
            "completion_tokens": 67, "total_s": 0.9416,
        }
        self.assertEqual(S.format_tuning_lines(same, same), [S.NOTHING_FASTER])
        self.assertTrue(S.tuning_bodies_match(same, dict(same)))
        faster = dict(same, write_tok_s=110.0)
        self.assertEqual(len(S.format_tuning_lines(same, faster)), 2)
        self.assertTrue(S.format_tuning_lines(same, faster)[0].startswith("Before · "))

    def test_stored_identical_record_paints_one_line(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "speed.json"
            same = {
                "write_tok_s": 92.457, "ttft_s": 0.2863,
                "completion_tokens": 67, "total_s": 0.9416,
            }
            got = S.record_tuning("qwen", before=same, after=same,
                                  source="optimize_now", path=path)
            self.assertEqual(got["lines"], [S.NOTHING_FASTER])
            self.assertTrue(got["unchanged"])
            self.assertEqual(S.get_tuning("qwen", path=path)["line"], S.NOTHING_FASTER)
            # An older file that never set the flag still paints the one line.
            data = json.loads(path.read_text())
            data["tuning"]["legacy"] = {
                "before": same, "after": same, "source": "optimize_now",
            }
            path.write_text(json.dumps(data))
            legacy = S.get_tuning("legacy", path=path)
            self.assertEqual(legacy["lines"], [S.NOTHING_FASTER])

    def test_unchanged_flag_without_specs(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "speed.json"
            got = S.record_tuning("m", before=None, after=None, unchanged=True,
                                  source="optimize_now", path=path)
            self.assertEqual(got["line"], S.NOTHING_FASTER)
            self.assertTrue(got["unchanged"])

    def test_clear_tuning_drops_the_slot(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "speed.json"
            S.record_tuning(
                "m",
                before={"write_tok_s": 10, "ttft_s": 1},
                after={"write_tok_s": 12, "ttft_s": 0.8},
                path=path,
            )
            self.assertIsNotNone(S.get_tuning("m", path=path)["line"])
            S.clear_tuning("m", path=path)
            self.assertIsNone(S.get_tuning("m", path=path)["line"])


class LeadLearnsWhenOn(unittest.TestCase):
    def test_drop_no_learn_when_self_tune_is_on(self):
        base = ["--model", "m", "--no-split-draft", "--no-learn",
                "--split-pipeline-chats", "1", "--kv-bits", "4"]
        out = web_settings.drop_no_learn_for_lead(base, {"self_tune": "auto"})
        self.assertNotIn("--no-learn", out)
        self.assertIn("--kv-bits", out)
        # Off, or an experimental mode that needs --no-learn, keeps the flag.
        self.assertIn("--no-learn", web_settings.drop_no_learn_for_lead(
            base, {"self_tune": "off"}))
        self.assertIn("--no-learn", web_settings.drop_no_learn_for_lead(
            base, {"self_tune": "auto", "guess_ahead": "mtp"}))
        self.assertIn("--no-learn", web_settings.drop_no_learn_for_lead(
            base, {"self_tune": "auto", "prompt_lookup": "adaptive"}))
        self.assertTrue(web_settings.lead_omits_no_learn({}))
        self.assertFalse(web_settings.lead_omits_no_learn({"self_tune": "off"}))

    def test_pipeline_lead_start_drops_no_learn(self):
        src = (REPO / "proxy/web_pipeline.py").read_text()
        self.assertIn("drop_no_learn_for_lead", src)


class ResetTuning(unittest.TestCase):
    def test_clears_saved_winners_and_speed_line(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tuned = Path(tmp.name) / "tuned.json"
        speed = Path(tmp.name) / "speed.json"
        st = {"models": {"m:spanned": {
            "winner": {"shared_prefix": True},
            "optimize_hardware": {"fp": {"losses": ["shared_prefix:off"]}},
            "pending_reload": {"kv_bits": 8},
            "reload_trial": "x",
            "reply_n": 4,
        }}}
        TS.save_store(st, tuned)
        os.environ["CARAVAN_SPEED_AVERAGES"] = str(speed)
        self.addCleanup(lambda: os.environ.pop("CARAVAN_SPEED_AVERAGES", None))
        S.record_tuning(
            "qwen",
            before={"write_tok_s": 90, "ttft_s": 0.3},
            after={"write_tok_s": 90, "ttft_s": 0.3},
            path=speed,
        )

        mgr = SimpleNamespace(
            state={"model_id": "qwen", "backend": "mlx", "split": True},
            _lead_path="/models/qwen",
            tuned_path=tuned,
        )
        def snapshot():
            return dict(mgr.state)
        def _tuned_entry(lead_path, *, create=False, spanned=None):
            store = TS.load_store(tuned)
            return store, (store.get("models") or {}).get("m:spanned")
        mgr.snapshot = snapshot
        mgr._tuned_entry = _tuned_entry
        out = WorkerManager.reset_tuning(mgr)
        self.assertTrue(out["ok"])
        self.assertIn("Tune again", out["notice"])
        store = TS.load_store(tuned)
        e = store["models"]["m:spanned"]
        self.assertEqual(e["winner"], {})
        self.assertEqual(e["optimize_hardware"], {})
        self.assertEqual(e.get("reply_n"), 0)
        self.assertIsNone(S.get_tuning("qwen", path=speed)["line"])

    def test_reset_does_not_unload(self):
        src = (REPO / "proxy/web_workers.py").read_text()
        # The method must not call stop or switch (no unload / reload).
        start = src.index("def reset_tuning")
        body = src[start:src.index("def lead_healthy")]
        self.assertNotIn("self.stop(", body)
        self.assertNotIn("self.switch(", body)
        self.assertIn("The loaded model stays loaded", body)


class Notices(unittest.TestCase):
    def test_ready_notice_does_not_say_when_you_load(self):
        src = (REPO / "proxy/web_workers.py").read_text()
        start = src.index("def set_self_tune")
        body = src[start:src.index("def _page_self_tune")]
        self.assertIn('if status == "ready"', body)
        self.assertIn("Caravan will learn from your next chats.", body)
        self.assertIn("It takes effect when you load a model.", body)
        # The "when you load" wording is only used when status is not ready.
        self.assertIn("load_on", body)
        self.assertIn("ready_on", body)

    def test_start_enables_learn_when_worker_is_off(self):
        src = (REPO / "proxy/web_optimize.py").read_text()
        start = src.index("def start(")
        body = src[start:src.index("def cancel(")]
        self.assertIn("set_self_tune", body)
        self.assertIn('fresh=True', body)
        self.assertIn("self.fresh", body)


if __name__ == "__main__":
    unittest.main()
