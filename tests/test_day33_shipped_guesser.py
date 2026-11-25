"""Day 33 (v0.9.15): prefer a shipped guesser, else the helper.

No live MLX: the Linux dev node has no Apple Silicon. These tests cover
the pure order in agent/guesser_choice.py, the MLX worker wiring (head
chosen, helper fallback, first-load check, greedy-only routing), the GGUF
paired-helper preference, the helper offer, the chips, and the locales.
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tests"))

import guesser_choice as GC  # noqa: E402
import guess_ahead  # noqa: E402
import helper_offer as HO  # noqa: E402
import mlx_worker as W  # noqa: E402
import web_settings  # noqa: E402
import gguf_split as GS  # noqa: E402

LOCALES = ("en", "es", "ru", "ja", "zh-Hans")
NEW_KEYS = sorted(
    [k for k in json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
     if k.startswith("agent.guesser_choice.")]
    + ["server.helper_offer.this_model_uses_its_built_in",
       "web.this_model_uses_its_built_in", "web.built_in_guesser"])


# ---------------------------------------------------------------- order ----
class MlxOrderTests(unittest.TestCase):
    def eligible(self, **kw):
        base = dict(head_present=True, head_error=None, split=False, kv_bits=None,
                    prompt_lookup=False)
        base.update(kw)
        return GC.mlx_choice(**base)

    def test_off_wins_over_everything(self):
        c = GC.mlx_choice(off=True, native_mtp_flag=True, explicit_draft=True, head_present=True)
        self.assertEqual((c["kind"], c["source"], c["reason"]), ("none", "off", "off"))

    def test_settings_native_mtp_test_stays_explicit(self):
        c = GC.mlx_choice(native_mtp_flag=True, head_present=False)
        self.assertEqual((c["kind"], c["source"]), ("native_mtp", "explicit"))
        self.assertFalse(c["gate"])

    def test_named_helper_wins_over_shipped_head(self):
        c = GC.mlx_choice(explicit_draft=True, head_present=True)
        self.assertEqual((c["kind"], c["source"], c["reason"]), ("helper", "explicit", "explicit_helper"))

    def test_no_head_falls_back_to_paired_helper(self):
        c = GC.mlx_choice(head_present=False)
        self.assertEqual((c["kind"], c["source"], c["reason"]), ("helper", "paired", "paired_helper"))

    def test_shipped_head_first_and_checked_once(self):
        c = self.eligible()
        self.assertEqual((c["kind"], c["source"], c["reason"]), ("native_mtp", "shipped", "shipped_first"))
        self.assertTrue(c["gate"])

    def test_split_and_balance_never_use_the_head(self):
        c = self.eligible(split=True)
        self.assertEqual((c["kind"], c["reason"]), ("helper", "shipped_needs_one_mac"))

    def test_compressed_memory_lookup_and_mismatch_use_helper(self):
        self.assertEqual(self.eligible(kv_bits=8)["reason"], "shipped_needs_16bit")
        self.assertEqual(self.eligible(kv_bits=4)["reason"], "shipped_needs_16bit")
        self.assertEqual(self.eligible(kv_bits=16)["kind"], "native_mtp")
        self.assertEqual(self.eligible(prompt_lookup=True)["reason"], "shipped_not_with_lookup")
        c = self.eligible(head_error="target mismatch")
        self.assertEqual((c["kind"], c["reason"]), ("helper", "shipped_mismatch"))

    def test_autotune_reload_leaves_head_to_its_own_trial(self):
        c = self.eligible(sweep_paused=True)
        self.assertEqual((c["kind"], c["reason"]), ("helper", "autotune_trial"))

    def test_autotune_verdict_beats_first_load_cache(self):
        c = self.eligible(autotune_verdict=False, first_load={"keep": True})
        self.assertEqual((c["kind"], c["reason"]), ("helper", "helper_won_autotune"))
        c = self.eligible(autotune_verdict=True, first_load={"keep": False})
        self.assertEqual((c["kind"], c["reason"]), ("native_mtp", "shipped_won_autotune"))
        self.assertFalse(c["gate"])

    def test_cached_first_load_result_is_reused(self):
        c = self.eligible(first_load={"keep": True})
        self.assertEqual((c["kind"], c["reason"], c["gate"]), ("native_mtp", "shipped_won_first_load", False))
        c = self.eligible(first_load={"keep": False})
        self.assertEqual((c["kind"], c["reason"]), ("helper", "helper_won_first_load"))

    def test_helper_outcome_without_a_helper_is_no_guesser(self):
        base = GC.choice(GC.HELPER, "paired", "shipped_needs_16bit")
        out = GC.helper_outcome(base, loaded=False)
        self.assertEqual((out["kind"], out["reason"]), ("none", "no_guesser"))
        self.assertEqual(out["passed_over"], "shipped_needs_16bit")
        self.assertTrue(out["passed_over_why"])
        plain = GC.helper_outcome(GC.choice(GC.HELPER, "paired", "paired_helper"), loaded=False)
        self.assertNotIn("passed_over", plain)
        self.assertEqual(GC.helper_outcome(base, loaded=True), base)
        named = GC.choice(GC.HELPER, "explicit", "explicit_helper")
        self.assertEqual(GC.helper_outcome(named, loaded=False), named)

    def test_every_reason_has_words(self):
        for code in GC.WHY:
            text = GC.why(code, name="Model-X")
            self.assertTrue(text and text != code, code)
        self.assertIn("Model-X", GC.why("gguf_paired_helper", name="Model-X"))


# ------------------------------------------------------------------ GGUF ----
class GgufPairedHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _file(self, name, size):
        p = self.root / name
        with open(p, "wb") as f:
            f.truncate(size)
        return p

    def test_paired_helper_beats_a_slightly_smaller_same_family_file(self):
        main = self._file("Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf", 4_000_000_000)
        other = self._file("Qwen2.5-0.5B-Instruct-Q8_0.gguf", 531_068_480)
        paired = self._file("Qwen2.5-Coder-0.5B-Instruct-Q8_0.gguf", 531_068_576)
        inv = [{"path": str(other), "name": other.stem}, {"path": str(paired), "name": paired.stem}]
        got = GS.find_gguf_draft(main, inventory=inv)
        self.assertEqual(Path(got["path"]).name, paired.name)
        self.assertEqual(got["source"], "paired")

    def test_without_the_paired_helper_the_smallest_file_is_found(self):
        main = self._file("Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf", 4_000_000_000)
        other = self._file("Qwen2.5-0.5B-Instruct-Q8_0.gguf", 531_068_480)
        got = GS.find_gguf_draft(main, inventory=[{"path": str(other), "name": other.stem}])
        self.assertEqual(Path(got["path"]).name, other.name)
        self.assertEqual(got["source"], "found")

    def test_paired_helper_still_has_to_pass_the_family_checks(self):
        # A Qwen3 main model must not take a Qwen2.5 file, paired or not.
        main = self._file("Qwen3-8B-Q4_K_M.gguf", 5_000_000_000)
        wrong = self._file("Qwen2.5-0.5B-Instruct-Q8_0.gguf", 531_068_480)
        self.assertIsNone(GS.find_gguf_draft(main, inventory=[{"path": str(wrong)}]))

    def test_gguf_source_and_active_chip(self):
        g = GC.gguf_source("/x/Qwen2.5-Coder-0.5B-Instruct-Q8_0.gguf",
                           main_name="Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
        self.assertEqual((g["source"], g["reason"]), ("paired", "gguf_paired_helper"))
        self.assertIn("Qwen2.5-Coder-0.5B-Instruct-Q8_0", g["why"])
        g = GC.gguf_source("/x/Qwen2.5-0.5B-Instruct-Q8_0.gguf",
                           main_name="Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
        self.assertEqual(g["source"], "found")
        self.assertIsNone(GC.gguf_source(None))
        a = web_settings.gguf_active_settings(
            {"guess_ahead": "on", "draft_path": "/x/Qwen2.5-Coder-0.5B-Instruct-Q8_0.gguf"},
            {}, model_path="/m/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
        self.assertEqual(a["guesser"]["source"], "paired")
        self.assertTrue(a["guess_ahead"])
        a = web_settings.gguf_active_settings({"guess_ahead": "off"}, {"guess_ahead": "off"})
        self.assertEqual(a["guesser"]["reason"], "off")
        a = web_settings.gguf_active_settings({}, {})
        self.assertIsNone(a["guesser"])


# ------------------------------------------------------------ MLX worker ----
def _engine(model_dir: Path, **kw):
    e = SimpleNamespace(
        model_dir=model_dir, model="MAIN", client=None, prompt_lookup_n=0,
        native_mtp=None, draft_model=None, guesser=None, _learn_path=None,
        _native_mtp_auto=False, _shipped_head_path=None, _shipped_gate_pending=False,
        mx=SimpleNamespace(clear_cache=lambda: None))
    for name in ("_setup_guesser", "_shipped_head_state", "_autotune_native_verdict",
                 "_guesser_log_line", "_drop_shipped_head", "_shipped_first_load_gate"):
        setattr(e, name, types.MethodType(getattr(W.Engine, name), e))
    e.helper_calls = []

    def _setup_guess_ahead(args, _e=e):
        _e.helper_calls.append(args)
        if getattr(_e, "helper_on_disk", False) and not getattr(args, "no_split_draft", False):
            _e.draft_model = "DRAFT"
    e._setup_guess_ahead = _setup_guess_ahead
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def _args(**kw):
    base = dict(no_split_draft=False, split_draft_model=None, native_mtp=False,
                kv_bits=None, sweep_paused=False)
    base.update(kw)
    return SimpleNamespace(**base)


QWEN35 = {"model_type": "qwen3_5", "text_config": {
    "hidden_size": 2560, "vocab_size": 248320, "num_hidden_layers": 32,
    "intermediate_size": 9216, "tie_word_embeddings": True, "mtp_num_hidden_layers": 1}}


def _install_head(model_dir: Path, target_repo="Orvena/Orvena-4B-MLX-4bit"):
    (model_dir / "config.json").write_text(json.dumps(QWEN35))
    h = model_dir / "caravan-mtp"
    h.mkdir()
    (h / "model.safetensors").write_bytes(b"x")
    (h / "config.json").write_text(json.dumps({"text_config": QWEN35["text_config"],
                                               "target_repo": target_repo}))
    return h


class WorkerSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model_dir = Path(self.tmp.name) / "Orvena--Orvena-4B-MLX-4bit"
        self.model_dir.mkdir()
        self.logs = []
        p = mock.patch.object(W, "log", self.logs.append)
        p.start()
        self.addCleanup(p.stop)
        self.state = Path(self.tmp.name) / "state.json"
        p = mock.patch.object(guess_ahead, "state_path", return_value=self.state)
        p.start()
        self.addCleanup(p.stop)
        self.loaded = []
        fake = types.ModuleType("native_mtp")
        import native_mtp as real
        fake.head_path = real.head_path
        fake.validate_pair = real.validate_pair
        fake.load_head = lambda d, m: (self.loaded.append((d, m)) or "HEAD")
        p = mock.patch.dict(sys.modules, {"native_mtp": fake})
        p.start()
        self.addCleanup(p.stop)

    def test_head_state_reads_configs_only(self):
        e = _engine(self.model_dir)
        self.assertEqual(e._shipped_head_state(), (False, None, None))
        hp = _install_head(self.model_dir)
        present, err, path = e._shipped_head_state()
        self.assertTrue(present)
        self.assertIsNone(err)
        self.assertEqual(path, hp)

    def test_head_for_another_model_is_a_mismatch(self):
        _install_head(self.model_dir, target_repo="someone/else")
        present, err, _ = _engine(self.model_dir)._shipped_head_state()
        self.assertTrue(present)
        self.assertTrue(err)

    def test_auto_uses_shipped_head_and_never_loads_the_helper(self):
        _install_head(self.model_dir)
        e = _engine(self.model_dir, helper_on_disk=True)
        e._setup_guesser(_args())
        self.assertEqual(e.native_mtp, "HEAD")
        self.assertTrue(e._native_mtp_auto)
        self.assertTrue(e._shipped_gate_pending)
        self.assertIsNone(e.draft_model)
        self.assertEqual(e.helper_calls, [])
        self.assertEqual((e.guesser["kind"], e.guesser["source"]), ("native_mtp", "shipped"))
        self.assertTrue(any(m.startswith("guesser: native_mtp (shipped") for m in self.logs))

    def test_no_head_uses_the_paired_helper(self):
        (self.model_dir / "config.json").write_text("{}")
        e = _engine(self.model_dir, helper_on_disk=True)
        e._setup_guesser(_args())
        self.assertIsNone(e.native_mtp)
        self.assertEqual(e.draft_model, "DRAFT")
        self.assertEqual(len(e.helper_calls), 1)
        self.assertEqual(e.guesser["reason"], "paired_helper")
        self.assertEqual(self.loaded, [])

    def test_autotune_helper_verdict_skips_the_head(self):
        _install_head(self.model_dir)
        store = Path(self.tmp.name) / "tuned.json"
        import tuned_settings as TS
        key = TS.entry_key(self.model_dir, spanned=False)
        store.write_text(json.dumps({"version": TS.VERSION, "models": {
            key: {"winner": {"native_mtp": False}}}}))
        e = _engine(self.model_dir, helper_on_disk=True, _learn_path=str(store))
        self.assertIs(e._autotune_native_verdict(), False)
        e._setup_guesser(_args())
        self.assertIsNone(e.native_mtp)
        self.assertEqual(e.draft_model, "DRAFT")
        self.assertEqual(e.guesser["reason"], "helper_won_autotune")
        self.assertEqual(self.loaded, [])

    def test_head_that_fails_to_load_falls_back_to_helper(self):
        _install_head(self.model_dir)
        sys.modules["native_mtp"].load_head = mock.Mock(side_effect=ValueError("bad weights"))
        e = _engine(self.model_dir, helper_on_disk=True)
        e._setup_guesser(_args())
        self.assertIsNone(e.native_mtp)
        self.assertFalse(e._native_mtp_auto)
        self.assertEqual(e.draft_model, "DRAFT")
        self.assertEqual(e.guesser["reason"], "shipped_load_failed")

    def test_head_failed_and_no_helper_is_no_guesser(self):
        _install_head(self.model_dir)
        e = _engine(self.model_dir, helper_on_disk=False, kv_bits=8)
        e._setup_guesser(_args(kv_bits=8))
        self.assertIsNone(e.native_mtp)
        self.assertEqual(e.guesser["kind"], "none")
        self.assertEqual(e.guesser["passed_over"], "shipped_needs_16bit")

    def test_off_and_split_never_touch_the_head(self):
        _install_head(self.model_dir)
        e = _engine(self.model_dir, helper_on_disk=True)
        e._setup_guesser(_args(no_split_draft=True))
        self.assertIsNone(e.native_mtp)
        self.assertEqual(e.guesser["kind"], "none")
        e = _engine(self.model_dir, helper_on_disk=True, client=object())
        e._setup_guesser(_args())
        self.assertIsNone(e.native_mtp)
        self.assertEqual(e.guesser["reason"], "shipped_needs_one_mac")
        self.assertEqual(self.loaded, [])

    def test_autotune_reload_uses_helper_arm(self):
        _install_head(self.model_dir)
        e = _engine(self.model_dir, helper_on_disk=True)
        e._setup_guesser(_args(sweep_paused=True))
        self.assertIsNone(e.native_mtp)
        self.assertEqual(e.guesser["reason"], "autotune_trial")

    def test_settings_native_mtp_keeps_strict_checks(self):
        _install_head(self.model_dir)
        e = _engine(self.model_dir)
        with self.assertRaises(ValueError):
            e._setup_guesser(_args(native_mtp=True, kv_bits=8))
        e = _engine(self.model_dir)
        e._setup_guesser(_args(native_mtp=True))
        self.assertEqual(e.native_mtp, "HEAD")
        self.assertFalse(e._native_mtp_auto)
        self.assertEqual(e.guesser["source"], "explicit")
        self.assertEqual(len(e.helper_calls), 1)  # still logs the v0.9.13 skip

    def test_cached_first_load_loss_goes_straight_to_helper(self):
        hp = _install_head(self.model_dir)
        guess_ahead.set_first_load(self.model_dir, hp, {"keep": False, "kind": "native_mtp"})
        e = _engine(self.model_dir, helper_on_disk=True)
        e._setup_guesser(_args())
        self.assertIsNone(e.native_mtp)
        self.assertEqual(e.guesser["reason"], "helper_won_first_load")
        self.assertEqual(self.loaded, [])


class FirstLoadGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model_dir = Path(self.tmp.name) / "m"
        self.model_dir.mkdir()
        self.head = self.model_dir / "caravan-mtp"
        self.state = Path(self.tmp.name) / "state.json"
        for p in (mock.patch.object(guess_ahead, "state_path", return_value=self.state),
                  mock.patch.object(W, "log", lambda *_: None)):
            p.start()
            self.addCleanup(p.stop)

    def _gate(self, *, answers, off_tps, on_tps):
        e = _engine(self.model_dir, native_mtp="HEAD")
        ans = iter(answers)
        e._gate_complete = lambda q, max_tokens=24, use_draft=True: next(ans)
        e._gate_timed = lambda p, max_tokens=40, use_draft=True: {
            "tps": on_tps if use_draft else off_tps, "accepted_frac": 0.9 if use_draft else None}
        return e._shipped_first_load_gate(self.head)

    def test_keeps_head_when_quality_ok_and_faster(self):
        self.assertTrue(self._gate(answers=["4", "Paris", "cold"], off_tps=36.0, on_tps=50.0))
        cached = guess_ahead.get_first_load(self.model_dir, self.head)
        self.assertTrue(cached["keep"])
        self.assertEqual(cached["kind"], "native_mtp")

    def test_drops_head_when_not_five_percent_faster(self):
        self.assertFalse(self._gate(answers=["4", "Paris", "cold"], off_tps=36.0, on_tps=37.0))
        self.assertFalse(guess_ahead.get_first_load(self.model_dir, self.head)["keep"])

    def test_drops_head_on_quality_fail(self):
        self.assertFalse(self._gate(answers=["5", "Paris", "cold"], off_tps=1.0, on_tps=99.0))
        self.assertFalse(guess_ahead.get_first_load(self.model_dir, self.head)["keep"])


class RoutingTests(unittest.TestCase):
    def _engine(self, auto):
        e = SimpleNamespace(native_mtp="HEAD", _native_mtp_auto=auto, mtp_calls=0)

        def _mtp(key, prompt, body, cancel, _e=e):
            _e.mtp_calls += 1
            if float(body.get("temperature", 0) or 0) != 0:
                raise ValueError("greedy only")
            yield ("done", {"how": "native-mtp-fresh-cache"})
        e._run_native_mtp = _mtp
        e._greedy = W.Engine._greedy
        return e

    def _first(self, e, body):
        gen = W.Engine._run_impl(e, "k", [1, 2], body, None)
        try:
            return next(gen)
        except (AttributeError, TypeError):
            return "normal-path"

    def test_auto_head_serves_greedy_replies(self):
        e = self._engine(auto=True)
        self.assertEqual(self._first(e, {"temperature": 0}), ("done", {"how": "native-mtp-fresh-cache"}))
        self.assertEqual(e.mtp_calls, 1)

    def test_auto_head_sends_sampled_replies_to_normal_path(self):
        e = self._engine(auto=True)
        self.assertEqual(self._first(e, {"temperature": 0.7}), "normal-path")
        self.assertEqual(self._first(e, {"temperature": 0, "repetition_penalty": 1.1}), "normal-path")
        self.assertEqual(e.mtp_calls, 0)

    def test_settings_native_mtp_stays_greedy_only(self):
        e = self._engine(auto=False)
        with self.assertRaises(ValueError):
            self._first(e, {"temperature": 0.7})

    def test_greedy_helper(self):
        self.assertTrue(W.Engine._greedy({}))
        self.assertTrue(W.Engine._greedy({"temperature": 0}))
        self.assertFalse(W.Engine._greedy({"temperature": "x"}))
        self.assertFalse(W.Engine._greedy({"temperature": 0.2}))


class GateCompleteTests(unittest.TestCase):
    def test_baseline_arm_turns_the_head_off_and_back_on(self):
        seen = []
        e = SimpleNamespace(draft_model=None, native_mtp="HEAD")
        e._gate_messages = lambda t: [{"role": "user", "content": t}]
        e.tokenizer = SimpleNamespace(apply_chat_template=lambda m, **k: [1, 2, 3])

        def _run(key, prompt, body, cancel, _e=e):
            seen.append(_e.native_mtp)
            yield ("piece", "4", True)
        e._run = _run
        self.assertEqual(W.Engine._gate_complete(e, "q", use_draft=False), "4")
        self.assertEqual(W.Engine._gate_complete(e, "q", use_draft=True), "4")
        self.assertEqual(seen, [None, "HEAD"])
        self.assertEqual(e.native_mtp, "HEAD")


# --------------------------------------------------------- offer and UI ----
class OfferAndChipTests(unittest.TestCase):
    ACTIVE = {"guesser": {"kind": "native_mtp", "source": "shipped", "reason": "shipped_first"}}

    def test_no_helper_offer_while_shipped_guesser_runs(self):
        snap = {"model_id": "Orvena/Orvena-4B-MLX-4bit", "settings": {}}
        with mock.patch("web_helpers.offer", return_value={"id": "x", "repo_id": "r"}):
            self.assertIsNone(HO.offer_for(snap, {"id": snap["model_id"], "source": "mlx"},
                                           active=self.ACTIVE))
            got = HO.offer_for(snap, {"id": snap["model_id"], "source": "mlx"}, active={})
            self.assertEqual(got["id"], "x")

    def test_helper_button_says_built_in_guesser(self):
        snap = {"model_id": "Orvena/Orvena-4B-MLX-4bit"}
        st = HO.helper_status(snap, {"id": snap["model_id"], "source": "mlx"}, active=self.ACTIVE)
        self.assertTrue(st["shipped"])
        self.assertTrue(st["message"])

    def test_page_shows_guesser_and_why(self):
        html = (ROOT / "proxy" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('T("web.built_in_guesser")', html)
        self.assertIn("a.guesser.why", html)
        js = (ROOT / "proxy" / "web" / "helpers.js").read_text(encoding="utf-8")
        self.assertIn("st.shipped", js)

    def test_active_settings_reports_guesser(self):
        src = (ROOT / "agent" / "mlx_worker.py").read_text(encoding="utf-8")
        self.assertIn('"guesser": {k: v for k, v in (getattr(self, "guesser", None) or {}).items()', src)


class LocaleTests(unittest.TestCase):
    def test_new_keys_in_every_language_with_same_placeholders(self):
        import re
        en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(NEW_KEYS), 20)
        for lang in LOCALES:
            d = json.loads((ROOT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
            for k in NEW_KEYS:
                self.assertIn(k, d, (lang, k))
                self.assertTrue(d[k].strip(), (lang, k))
                self.assertEqual(sorted(re.findall(r"\{(\w+)", d[k])),
                                 sorted(re.findall(r"\{(\w+)", en[k])), (lang, k))


if __name__ == "__main__":
    unittest.main()
