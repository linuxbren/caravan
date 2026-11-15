"""Day 28 fixes: model-neutral Guess-ahead text, the Auto-tune animation no
longer moving the chat, GGUF Auto-tune/Reset after Update now (web restart),
self-tune trials that never reloaded, and a plain "kept your settings" line."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
import gguf_self_tune as GST  # noqa: E402
import gguf_tune as GT  # noqa: E402
import web_gguf_optimize as WGO  # noqa: E402
import web_settings  # noqa: E402
import web_speed as S  # noqa: E402
import web_workers  # noqa: E402
from web_workers import WorkerManager  # noqa: E402

HTML = (ROOT / "proxy" / "web" / "index.html").read_text()


def _css_block(selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", HTML)
    assert m, selector
    return m.group(1)


class NeutralGuessAheadText(unittest.TestCase):
    def _help_strings(self):
        out = []
        for row in web_settings.SETTINGS if hasattr(web_settings, "SETTINGS") else []:
            out += [row.get("help") or "", row.get("help_gguf") or ""]
        return out

    def test_settings_help_names_no_model(self):
        src = (ROOT / "proxy" / "web_settings.py").read_text()
        for line in src.splitlines():
            if '"help' in line:
                self.assertNotRegex(line.lower(), r"qwen|llama|gemma|deepseek|mistral", line)

    def test_page_help_names_no_model(self):
        for name in ("SETTINGS_HELP_COPY", "SETTINGS_HELP_GGUF"):
            m = re.search(r"const " + name + r" = \{(.*?)\n\s*\};", HTML, re.S)
            self.assertIsNotNone(m, name)
            self.assertNotRegex(m.group(1).lower(), r"qwen|llama|gemma|deepseek|mistral")
        self.assertNotIn("Qwen N2", HTML)

    def test_generic_wording_and_same_text_on_page(self):
        src = (ROOT / "proxy" / "web_settings.py").read_text()
        for needle in ("often faster on code edits", "Gains vary by model and Mac",
                       "first word on long prompts can come a little later"):
            self.assertIn(needle, src)
            self.assertIn(needle, HTML)
        self.assertNotIn("93%", src + HTML)


class TuneAnimationDoesNotMoveChat(unittest.TestCase):
    def test_campfire_glyph_has_a_fixed_box(self):
        for sel in ("button.primary.is-tuning::before", ".tune-badge.is-tuning::before"):
            css = _css_block(sel)
            self.assertIn("width: 1em", css)
            self.assertIn("height: 1em", css)
            self.assertIn("line-height: 1", css)
            self.assertIn("overflow: hidden", css)

    def test_badge_and_header_reserve_height(self):
        self.assertIn("height: 1.35rem", _css_block(".tune-badge"))
        self.assertIn(".chathead h2 { display: flex; align-items: center; flex-wrap: wrap; "
                      "min-height: 1.35rem; }", HTML)


def _adopt(td: Path, meta: dict):
    mgr = WorkerManager(state_dir=td / "state", repo=ROOT, lead_port=8297)
    (td / "state").mkdir(parents=True, exist_ok=True)
    (td / "state" / "gguf.json").write_text(json.dumps(meta))
    with mock.patch("gguf_split.pid_cmdline", return_value="llama-server --model x"), \
            mock.patch.object(WorkerManager, "lead_healthy", return_value=True), \
            mock.patch.object(WorkerManager, "_start_gguf_watch", return_value=None), \
            mock.patch("web_catalog.gguf_entry", return_value=None):
        assert mgr.adopt_gguf()
    return mgr


class AdoptedGgufCanTuneAndReset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.td = Path(self.tmp.name)
        self.model = self.td / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
        self.model.write_bytes(b"x")
        # The gguf.json a 718cf98 load wrote: no "entry" key.
        self.meta = {"lead_pid": 4242, "peers": [], "tunnels": [], "model": str(self.model),
                     "id": "gguf/Qwen2.5-Coder-7B-Instruct-Q4_K_M",
                     "name": "Qwen2.5-Coder-7B-Instruct-Q4_K_M (GGUF)",
                     "gguf": {"mode": "one", "nodes": [{"id": "lead"}]}, "shares": [1]}

    def test_entry_rebuilt_from_gguf_json(self):
        mgr = _adopt(self.td, self.meta)
        e = mgr._loaded_entry
        self.assertEqual(e["source"], "gguf")
        self.assertEqual(e["lead_path"], str(self.model))
        self.assertEqual(e["id"], self.meta["id"])

    def test_saved_entry_is_used_when_present(self):
        meta = dict(self.meta, entry={"id": self.meta["id"], "name": "x", "source": "gguf",
                                      "lead_path": str(self.model), "_loaded_tune": {"ubatch": 256}})
        mgr = _adopt(self.td, meta)
        self.assertEqual(mgr._loaded_entry["_loaded_tune"], {"ubatch": 256})

    def test_auto_tune_starts_after_adoption(self):
        mgr = _adopt(self.td, self.meta)

        class FakeTuner:
            def __init__(self, *a, **k):
                pass

            def run(self):
                return {"status": "done", "best": {}, "tried": [], "before": None, "after": None}

        opt = WGO.GgufOptimizer(mgr, tuner_cls=FakeTuner, measure=lambda: 1.0,
                                store_path=self.td / "tuned.json")
        with mock.patch.object(WGO.GgufOptimizer, "_restart", return_value=None):
            snap = opt.start(source="optimize_now")
            opt._thread.join(timeout=5)
        self.assertTrue(snap["running"])

    def test_reset_clears_gguf_results_after_adoption(self):
        mgr = _adopt(self.td, self.meta)
        store = self.td / "gguf-tuned.json"
        key = GT.entry_key(self.model, 1)
        store.write_text(json.dumps({key: {"best": {"ubatch": 256}}, "other|1mini": {}}))
        with mock.patch.object(GT, "STORE", store), \
                mock.patch.object(GST, "clear_entry") as clear, \
                mock.patch("web_speed.clear_tuning", return_value={}):
            out = mgr.reset_tuning()
        self.assertTrue(out["ok"])
        left = json.loads(store.read_text())
        self.assertNotIn(key, left)
        self.assertIn("other|1mini", left)
        clear.assert_called_once()
        self.assertEqual(Path(clear.call_args[0][0]), self.model)

    def test_load_saves_entry_for_next_adoption(self):
        src = (ROOT / "proxy" / "web_workers.py").read_text()
        self.assertIn('meta["entry"] = json.loads(json.dumps(self._loaded_entry, default=str))', src)


class SelfTuneTrialMustReallyRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "self.json"
        self.speed = Path(self.tmp.name) / "speed.json"
        self.model = Path(self.tmp.name) / "Llama-3.2-3B-Instruct-Q2_K_L.gguf"
        self.model.write_bytes(b"x")

    def _obs(self, write, used):
        return GST.observe(self.model, 1, {"write_tok_s": write, "read_tok_s": 100.0,
                                           "ttft_s": 0.3, "prompt_tokens": 20,
                                           "completion_tokens": 40, "total_s": 1.0},
                           used=used, settings={"self_tune": "auto"}, path=self.store,
                           speed_path=self.speed, model_id="gguf/llama")

    def test_trial_that_never_reloaded_is_asked_again_not_counted(self):
        base = {"flash_attn": "on", "ubatch": 512, "cache_type": "f16"}
        plan = None
        for _ in range(GST.MIN_SAMPLES):
            plan = self._obs(55.0, base)
        self.assertEqual(plan["action"], "reload")
        self.assertEqual(plan["tune"]["ubatch"], 256)
        # The reload never happened (model switched, or Update now restarted
        # the page): replies still run at ubatch 512.
        for _ in range(GST.MIN_SAMPLES + 2):
            plan = self._obs(55.0, base)
            self.assertEqual(plan["action"], "reload")
            self.assertEqual(plan["tune"]["ubatch"], 256)
        e = GST.load_store(self.store)[GST.entry_key(self.model, 1)]
        self.assertEqual(e["status"], "trial")
        self.assertFalse(e["trial"]["samples"])
        self.assertFalse(e.get("losses"))
        # Once the trial really runs, it settles, then is measured.
        trial = dict(base, ubatch=256)
        self.assertEqual(self._obs(70.0, trial)["reason"], "settling")
        for _ in range(GST.MIN_SAMPLES):
            plan = self._obs(70.0, trial)
        self.assertEqual(plan["action"], "keep")


class KeptSettingsLine(unittest.TestCase):
    # Brenden's 1st Mac Llama 3.2 3B run: all four trials lost.
    TRIED = [
        {"name": "flash_attn", "incumbent": "on", "challenger": "off",
         "incumbent_tps": 55.56, "challenger_tps": 53.37, "won": False},
        {"name": "ubatch", "incumbent": 512, "challenger": 256,
         "incumbent_tps": 55.44, "challenger_tps": 56.11, "won": False},
        {"name": "cache_type", "incumbent": "f16", "challenger": "q8_0",
         "incumbent_tps": 55.51, "challenger_tps": 54.62, "won": False},
        {"name": "prompt_lookup", "incumbent": "off", "challenger": "on",
         "incumbent_tps": 55.37, "challenger_tps": 56.19, "won": False},
    ]

    def test_detail_line(self):
        line = S.format_kept_detail(self.TRIED)
        self.assertIn("Kept your current settings: tried 4 changes, none was at least 3% faster.", line)
        self.assertIn("Current settings 55.5 tok/s writing", line)
        self.assertIn("closest try (Prompt lookup On) 56.2 tok/s", line)
        self.assertEqual(S.format_kept_detail(self.TRIED[:1] + [dict(self.TRIED[1], won=True)]), "")
        self.assertEqual(S.format_kept_detail([]), "")

    def test_record_shows_both_lines(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "speed.json"
            got = S.record_tuning("gguf/llama", before={"write_tok_s": 55.56},
                                  after={"write_tok_s": 55.37}, unchanged=True,
                                  detail="Kept your current settings: x", path=p)
            self.assertEqual(got["lines"], [S.NOTHING_FASTER, "Kept your current settings: x"])
            self.assertEqual(S.get_tuning("gguf/llama", path=p)["lines"][1],
                             "Kept your current settings: x")

    def test_optimizer_marks_no_winner_as_unchanged(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tried = self.TRIED
        recorded = []

        class FakeTuner:
            def __init__(self, *a, **k):
                pass

            def run(self):
                # After is a later re-measure of the same settings: noise.
                return {"status": "done", "best": {}, "tried": tried,
                        "before": {"write_tok_s": 55.56, "read_tok_s": 300, "ttft_s": 0.2},
                        "after": {"write_tok_s": 55.37, "read_tok_s": 298, "ttft_s": 0.21}}

        class Mgr:
            def snapshot(self):
                return {"status": "ready", "model_id": "gguf/llama", "backend": "llama",
                        "settings": {}, "gguf": {"nodes": [1]}}

        mgr = Mgr()
        mgr._loaded_entry = {"source": "gguf", "lead_path": str(Path(tmp.name) / "l.gguf")}
        Path(mgr._loaded_entry["lead_path"]).write_bytes(b"x")
        opt = WGO.GgufOptimizer(mgr, tuner_cls=FakeTuner, measure=lambda: 1.0,
                                store_path=Path(tmp.name) / "t.json")
        with mock.patch("web_speed.record_tuning",
                        side_effect=lambda *a, **k: recorded.append(k) or {"lines": []}):
            opt.start(source="optimize_now")
            opt._thread.join(timeout=5)
        self.assertTrue(recorded[0]["unchanged"])
        self.assertIn("none was at least 3% faster", recorded[0]["detail"])
        summ = opt.snapshot().get("summary") or {}
        self.assertTrue(summ.get("unchanged"))
        self.assertIn("closest try", summ.get("detail") or "")


if __name__ == "__main__":
    unittest.main()
