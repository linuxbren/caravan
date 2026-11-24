"""Day 33: Guess-ahead helper for an MLX model on one Mac.

No live MLX: the Linux dev node has no Apple Silicon. These tests stub
the worker, the helper offer, Auto-tune scoring, speedups, locales, and
the Helper button copy. Split MLX and GGUF paths stay covered by earlier
suites; this file checks the new one-Mac gates and that the old
split-only skips are gone.
"""
from __future__ import annotations

import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import threading
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

import guess_ahead as G  # noqa: E402
import helper_offer as HO  # noqa: E402
import mlx_worker as W  # noqa: E402
import web_helpers as H  # noqa: E402
import web_settings  # noqa: E402
from i18n_check import english_source  # noqa: E402

NODE = shutil.which("node")
PAIRING = {
    "id": "qwen3-30b-a3b",
    "draft": {"name": "Qwen3-0.6B-4bit", "size_mb": 335, "k": 5, "vocab": "ok"},
}


def _engine(model_dir: Path, **kw):
    e = SimpleNamespace(
        model_dir=model_dir,
        speculate_k=4,
        _speculate_k_explicit=False,
        prompt_lookup_n=0,
        prompt_lookup_adaptive=False,
        draft_model=None,
        draft_tokenizer=None,
        draft_path=None,
        draft_remap_d2t={},
        draft_remap_t2d={},
        guess_pairing=None,
        client=None,
        native_mtp=None,
        _learn_guess_override=None,
        prompt_lookup_n_attr=0,
    )
    for k, v in kw.items():
        setattr(e, k, v)
    e._draft_fits = lambda dpath, pairing, _e=e: W.Engine._draft_fits(_e, dpath, pairing)
    return e


def _install_draft(root: Path, name="Qwen3-0.6B-4bit"):
    d = root / name
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    return d


class DraftFitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model_dir = Path(self.tmp.name) / "Qwen3-30B-A3B-4bit"
        self.model_dir.mkdir()
        (self.model_dir / "config.json").write_text("{}")
        self.draft = _install_draft(Path(self.tmp.name))
        self.engine = _engine(self.model_dir)

    def test_fits_when_enough_memory(self):
        with mock.patch("mlx_split.host_memory_gb", return_value=(24.0, 8.0)):
            ok, reason = W.Engine._draft_fits(self.engine, self.draft, PAIRING)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_does_not_fit_fails_closed(self):
        with mock.patch("mlx_split.host_memory_gb", return_value=(24.0, 0.1)):
            ok, reason = W.Engine._draft_fits(self.engine, self.draft, PAIRING)
        self.assertFalse(ok)
        self.assertIn("need", reason)
        self.assertIn("available", reason)

    def test_unknown_memory_fails_closed(self):
        with mock.patch("mlx_split.host_memory_gb", return_value=(24.0, None)):
            ok, reason = W.Engine._draft_fits(self.engine, self.draft, PAIRING)
        self.assertFalse(ok)
        self.assertIn("memory unknown", reason)

    def test_memory_error_fails_closed(self):
        with mock.patch("mlx_split.host_memory_gb", side_effect=RuntimeError("no stats")):
            ok, reason = W.Engine._draft_fits(self.engine, self.draft, PAIRING)
        self.assertFalse(ok)
        self.assertIn("memory unknown", reason)

    def test_unknown_size_fails_closed(self):
        empty = Path(self.tmp.name) / "empty-draft"
        empty.mkdir()
        with mock.patch("mlx_split.host_memory_gb", return_value=(24.0, 8.0)):
            ok, reason = W.Engine._draft_fits(self.engine, empty, {"draft": {}})
        self.assertFalse(ok)
        self.assertIn("helper size unknown", reason)


class SetupGuessAheadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model_dir = Path(self.tmp.name) / "Qwen3-30B-A3B-4bit"
        self.model_dir.mkdir()
        (self.model_dir / "config.json").write_text("{}")
        self.drafts = Path(self.tmp.name) / "drafts"
        self.drafts.mkdir()
        self.engine = _engine(self.model_dir)
        self.logs = []
        self.log_p = mock.patch.object(W, "log", self.logs.append)
        self.log_p.start()
        self.addCleanup(self.log_p.stop)
        self.mem_p = mock.patch("mlx_split.host_memory_gb", return_value=(24.0, 8.0))
        self.mem_p.start()
        self.addCleanup(self.mem_p.stop)

    def _args(self, **kw):
        base = dict(no_split_draft=False, split_draft_model=None,
                    split_draft_auto_download=False, native_mtp=False)
        base.update(kw)
        return SimpleNamespace(**base)

    def _pair_ok(self):
        return dict(PAIRING)

    def _run(self, args, *, pairing=None, vocab=None, load=None):
        calls = {"load": []}

        def _load(path):
            calls["load"].append(path)
            return ("DRAFT-MODEL", "DRAFT-TOK")

        mlx_lm = types.ModuleType("mlx_lm")
        mlx_lm.load = load or _load
        patches = [
            mock.patch.object(W.guess_ahead, "find_pairing",
                              return_value=pairing if pairing is not None else self._pair_ok()),
            mock.patch.object(W.guess_ahead, "drafts_dir", return_value=self.drafts),
            mock.patch.object(W.guess_ahead, "build_vocab_maps",
                              return_value=vocab if vocab is not None else {
                                  "ok": True, "mode": "shared", "n_remap": 0,
                                  "remap_draft_to_target": {}, "remap_target_to_draft": {},
                              }),
            mock.patch.dict(sys.modules, {"mlx_lm": mlx_lm}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        W.Engine._setup_guess_ahead(self.engine, args)
        return calls

    def _run_spied(self, args):
        """Call _setup_guess_ahead with pairing/download/load as spies."""
        load_calls = []

        def _load(path):
            load_calls.append(path)
            return ("DRAFT-MODEL", "DRAFT-TOK")

        mlx_lm = types.ModuleType("mlx_lm")
        mlx_lm.load = _load
        dest = self.drafts / PAIRING["draft"]["name"]
        find = mock.patch.object(W.guess_ahead, "find_pairing", return_value=self._pair_ok())
        drafts = mock.patch.object(W.guess_ahead, "drafts_dir", return_value=self.drafts)
        vocab = mock.patch.object(W.guess_ahead, "build_vocab_maps", return_value={
            "ok": True, "mode": "shared", "n_remap": 0,
            "remap_draft_to_target": {}, "remap_target_to_draft": {},
        })
        ask = mock.patch.object(W.guess_ahead, "ask_download", return_value=True)
        download = mock.patch.object(W.guess_ahead, "download_draft", return_value=dest)
        modules = mock.patch.dict(sys.modules, {"mlx_lm": mlx_lm})
        spies = {}
        for name, p in (("find_pairing", find), ("drafts_dir", drafts),
                        ("build_vocab_maps", vocab), ("ask_download", ask),
                        ("download_draft", download), ("mlx_lm", modules)):
            spies[name] = p.start()
            self.addCleanup(p.stop)
        W.Engine._setup_guess_ahead(self.engine, args)
        spies["load_calls"] = load_calls
        return spies

    def test_auto_pair_loads_draft_on_one_mac(self):
        dpath = _install_draft(self.drafts)
        calls = self._run(self._args())
        self.assertEqual(self.engine.draft_model, "DRAFT-MODEL")
        self.assertEqual(self.engine.draft_tokenizer, "DRAFT-TOK")
        self.assertEqual(self.engine.draft_path, dpath.resolve())
        self.assertEqual(self.engine.speculate_k, 5)
        self.assertEqual(self.engine.guess_pairing["id"], "qwen3-30b-a3b")
        self.assertEqual(calls["load"], [str(dpath.resolve())])
        self.assertTrue(any("auto-pair" in m for m in self.logs))
        self.assertTrue(any("idea 3 guess-ahead" in m for m in self.logs))

    def test_no_split_draft_skips(self):
        _install_draft(self.drafts)
        self._run(self._args(no_split_draft=True))
        self.assertIsNone(self.engine.draft_model)
        self.assertTrue(any("--no-split-draft" in m for m in self.logs))

    def test_native_mtp_skips_auto_pair_download_and_load(self):
        # Helper is already on disk for an auto-pairable model (Qwen3-30B-A3B).
        _install_draft(self.drafts)
        spies = self._run_spied(self._args(native_mtp=True))
        self.assertIsNone(self.engine.draft_model)
        self.assertIsNone(self.engine.draft_path)
        self.assertIsNone(self.engine.guess_pairing)
        spies["find_pairing"].assert_not_called()
        spies["ask_download"].assert_not_called()
        spies["download_draft"].assert_not_called()
        spies["build_vocab_maps"].assert_not_called()
        self.assertEqual(spies["load_calls"], [])
        self.assertTrue(any("native MTP" in m and "conventional draft helper off" in m
                            for m in self.logs))

    def test_native_mtp_ignores_explicit_split_draft_model(self):
        dpath = _install_draft(self.drafts)
        missing = Path(self.tmp.name) / "no-such-draft"
        # Existing explicit path: no load. Missing path: no FileNotFoundError.
        spies = self._run_spied(self._args(native_mtp=True, split_draft_model=str(dpath)))
        self.assertIsNone(self.engine.draft_model)
        spies["find_pairing"].assert_not_called()
        self.assertEqual(spies["load_calls"], [])
        self.logs.clear()
        spies2 = self._run_spied(self._args(native_mtp=True, split_draft_model=str(missing)))
        self.assertIsNone(self.engine.draft_model)
        spies2["find_pairing"].assert_not_called()
        self.assertEqual(spies2["load_calls"], [])

    def test_settings_mtp_flow_never_loads_conventional_draft(self):
        lead, packer = web_settings.to_args({"guess_ahead": "mtp"})
        self.assertIn("--native-mtp", lead)
        self.assertIn("--no-learn", lead)
        self.assertNotIn("--no-split-draft", lead)
        self.assertNotIn("--pin-guess-ahead", lead)
        self.assertNotIn("--split-draft-model", lead)
        # Apply the real Settings flags the same way the worker sees them
        # (store_true: present → True, absent → False).
        args = self._args()
        args.native_mtp = "--native-mtp" in lead
        args.no_split_draft = "--no-split-draft" in lead
        args.split_draft_model = None
        _install_draft(self.drafts)
        spies = self._run_spied(args)
        self.assertTrue(args.native_mtp)
        self.assertFalse(args.no_split_draft)
        self.assertIsNone(self.engine.draft_model)
        self.assertIsNone(self.engine.draft_path)
        spies["find_pairing"].assert_not_called()
        spies["ask_download"].assert_not_called()
        spies["download_draft"].assert_not_called()
        spies["build_vocab_maps"].assert_not_called()
        self.assertEqual(spies["load_calls"], [])
        self.assertTrue(any("native MTP" in m and "conventional draft helper off" in m
                            for m in self.logs))

    def test_explicit_missing_path_raises(self):
        missing = Path(self.tmp.name) / "no-such-draft"
        with self.assertRaises(FileNotFoundError):
            self._run(self._args(split_draft_model=str(missing)))
        self.assertIsNone(self.engine.draft_model)

    def test_vocab_mismatch_skips_without_crash(self):
        _install_draft(self.drafts)
        self._run(self._args(), vocab={"ok": False, "reason": "tokenizer mismatch"})
        self.assertIsNone(self.engine.draft_model)
        self.assertTrue(any("vocab mismatch" in m and "skipping draft" in m
                            for m in self.logs))

    def test_helper_does_not_fit_skips_without_crash(self):
        _install_draft(self.drafts)
        with mock.patch("mlx_split.host_memory_gb", return_value=(24.0, 0.1)):
            self._run(self._args())
        self.assertIsNone(self.engine.draft_model)
        self.assertTrue(any("helper does not fit" in m and "skipping draft" in m
                            for m in self.logs))

    def test_declined_download_skips(self):
        with mock.patch.object(W.guess_ahead, "ask_download", return_value=False) as ask:
            self._run(self._args())
        self.assertIsNone(self.engine.draft_model)
        ask.assert_called_once()
        self.assertTrue(any("helper download declined" in m for m in self.logs))

    def test_no_pairing_skips(self):
        self._run(self._args(), pairing=None)
        self.assertIsNone(self.engine.draft_model)

    def test_skip_pairing_logs_reason(self):
        self._run(self._args(), pairing={"skip": True, "reason": "no compatible helper"})
        self.assertIsNone(self.engine.draft_model)
        self.assertTrue(any("no pairing (no compatible helper)" in m for m in self.logs))

    def test_accepted_download_loads_draft(self):
        dest = _install_draft(Path(self.tmp.name) / "downloaded")
        with mock.patch.object(W.guess_ahead, "ask_download", return_value=True), \
                mock.patch.object(W.guess_ahead, "download_draft", return_value=dest):
            self._run(self._args())
        self.assertEqual(self.engine.draft_model, "DRAFT-MODEL")
        self.assertEqual(self.engine.draft_path, dest.resolve())
        self.assertTrue(any("downloaded helper" in m for m in self.logs))


class ActiveSettingsAndLearnTests(unittest.TestCase):
    def _stub(self, **kw):
        defaults = dict(
            args=SimpleNamespace(kv_bits=16, fuse_kernels="off",
                                 split_keepalive=False, split_front_layers=None),
            native_mtp=None,
            client=None,
            draft_model=None,
            _learn_guess_override=None,
            prompt_lookup_n=0,
            prompt_lookup_adaptive=False,
            pipeline_chats=1,
            _learn_enabled=True,
            _learn_explicit={},
            _sweep_pause=False,
            _learn_reload_auto=[],
            _learn_entry=None,
            _learn_n_layers=None,
        )
        defaults.update(kw)
        e = SimpleNamespace(**defaults)
        e._shared_prefix_on = lambda: False
        return e

    def test_active_settings_reports_helper_on_one_mac(self):
        e = self._stub(draft_model="DRAFT")
        out = W.Engine.active_settings(e)
        self.assertTrue(out["guess_ahead"])
        self.assertTrue(out["guess_ahead_loaded"])
        self.assertEqual(out["guess_ahead_mode"], "helper")
        self.assertFalse(out["two_chats_available"])

    def test_active_settings_override_off(self):
        e = self._stub(draft_model="DRAFT", _learn_guess_override=False)
        out = W.Engine.active_settings(e)
        self.assertFalse(out["guess_ahead"])
        self.assertTrue(out["guess_ahead_loaded"])

    def test_active_settings_no_draft(self):
        e = self._stub()
        out = W.Engine.active_settings(e)
        self.assertFalse(out["guess_ahead"])
        self.assertFalse(out["guess_ahead_loaded"])

    def test_learn_observe_scores_guess_ahead_on_one_mac(self):
        import tuned_settings as TS
        captured = {}

        def fake_observe(entry, **kw):
            captured.update(kw)
            return {"promotions": [], "keep_reasons": [], "explore": None,
                    "norm_tps": 1.0, "winner": {}}

        e = self._stub(
            draft_model="DRAFT",
            _learn_entry={"winner": {}},
            _learn_store={"models": {}},
            _learn_path=None,
            _learn_lock=threading.Lock(),
            _learn_trial=None,
        )
        e._learn_guess_ahead_on = lambda: W.Engine._learn_guess_ahead_on(e)
        with mock.patch.object(TS, "observe_reply", side_effect=fake_observe), \
                mock.patch.object(TS, "save_store"):
            W.Engine._learn_observe(e, {"completion_tokens": 20, "total_s": 1.0,
                                        "prefill_s": 0.2, "prompt_tokens": 10})
        self.assertTrue(captured["settings_used"]["guess_ahead"])

    def test_learn_observe_skips_guess_ahead_without_draft_or_split(self):
        import tuned_settings as TS
        captured = {}

        def fake_observe(entry, **kw):
            captured.update(kw)
            return {"promotions": [], "keep_reasons": [], "explore": None,
                    "norm_tps": 1.0, "winner": {}}

        e = self._stub(
            draft_model=None, client=None,
            _learn_entry={"winner": {}},
            _learn_store={"models": {}},
            _learn_path=None,
            _learn_lock=threading.Lock(),
            _learn_trial=None,
        )
        e._learn_guess_ahead_on = lambda: W.Engine._learn_guess_ahead_on(e)
        with mock.patch.object(TS, "observe_reply", side_effect=fake_observe), \
                mock.patch.object(TS, "save_store"):
            W.Engine._learn_observe(e, {"completion_tokens": 20, "total_s": 1.0,
                                        "prefill_s": 0.2, "prompt_tokens": 10})
        self.assertIsNone(captured["settings_used"]["guess_ahead"])


class SourceGateTests(unittest.TestCase):
    def test_setup_is_shared_and_speculate_does_not_require_client(self):
        setup = inspect.getsource(W.Engine._setup)
        self.assertIn("self._setup_guess_ahead(args)", setup)
        # Draft load must not live only in the split-lead branch.
        self.assertNotIn("no_draft = bool(getattr(args, \"no_split_draft\"", setup)
        run = inspect.getsource(W.Engine._run_impl)
        self.assertIn("use_spec = (draft_ok or int(self.prompt_lookup_n) > 0)", run)
        self.assertNotIn("self.client is not None and draft_ok", run)
        self.assertIn("if self.draft_model is not None:", run)
        self.assertNotIn("if self.client is not None and self.draft_model is not None:", run)

    def test_guesses_kept_still_reported_from_run(self):
        src = inspect.getsource(W.Engine._run_impl)
        self.assertIn('"from_draft": n_from_draft', src)
        self.assertIn('"accepted_frac"', src)


class SettingsArgsTests(unittest.TestCase):
    def test_auto_off_on_flags(self):
        self.assertNotIn("--no-split-draft", web_settings.to_args({"guess_ahead": "auto"})[0])
        self.assertNotIn("--pin-guess-ahead", web_settings.to_args({"guess_ahead": "auto"})[0])
        self.assertIn("--no-split-draft", web_settings.to_args({"guess_ahead": "off"})[0])
        self.assertIn("--pin-guess-ahead", web_settings.to_args({"guess_ahead": "on"})[0])
        lead, _ = web_settings.to_args({"guess_ahead": "mtp"})
        self.assertIn("--native-mtp", lead)
        self.assertNotIn("--no-split-draft", lead)


class OfferAndStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        table = H.G.load_table()
        table["drafts_dir"] = self.tmp.name + "/drafts"
        table["state_file"] = self.tmp.name + "/state.json"
        self.table = table
        self.patcher = mock.patch.object(H.G, "load_table", return_value=table)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        # helper_status also imports guess_ahead as G
        self.g2 = mock.patch.object(G, "load_table", return_value=table)
        self.g2.start()
        self.addCleanup(self.g2.stop)
        self.snap = {"model_id": "mlx-community/Qwen3-30B-A3B-4bit",
                     "split": False, "settings": {"guess_ahead": "auto"}}

    def test_offer_one_mac_when_helper_missing(self):
        off = H.offer(self.snap)
        self.assertIsNotNone(off)
        self.assertEqual(off["id"], "qwen3-30b-a3b")
        self.assertEqual(off["size_mb"], 335)
        self.assertFalse(off["declined"])

    def test_offer_split_still_works(self):
        off = H.offer({**self.snap, "split": True, "settings": {"guess_ahead": "on"}})
        self.assertIsNotNone(off)
        self.assertEqual(off["id"], "qwen3-30b-a3b")

    def test_offer_hidden_when_off_mtp_balance_or_installed(self):
        self.assertIsNone(H.offer({**self.snap, "settings": {"guess_ahead": "off"}}))
        self.assertIsNone(H.offer({**self.snap, "settings": {"guess_ahead": "mtp"}}))
        self.assertIsNone(H.offer({**self.snap, "split": True,
                                   "balance": {"counts": [20, 28]}}))
        p = H.G.drafts_dir() / "Qwen3-0.6B-4bit"
        p.mkdir(parents=True)
        (p / "config.json").write_text("{}")
        self.assertIsNone(H.offer(self.snap))

    def test_helper_status_known_and_present_on_one_mac(self):
        st = HO.helper_status(self.snap, {"id": self.snap["model_id"]})
        self.assertEqual(st["kind"], "mlx")
        self.assertFalse(st["split"])
        self.assertFalse(st.get("present"))
        self.assertEqual(st["known_id"], "qwen3-30b-a3b")
        self.assertEqual(st["known_name"], "Qwen3-0.6B-4bit")
        self.assertEqual(st["known_size_mb"], 335)
        p = G.drafts_dir() / "Qwen3-0.6B-4bit"
        p.mkdir(parents=True)
        (p / "config.json").write_text("{}")
        st2 = HO.helper_status(self.snap, {"id": self.snap["model_id"]})
        self.assertTrue(st2["present"])
        self.assertEqual(st2["present_name"], "Qwen3-0.6B-4bit")
        self.assertIn("already", (st2.get("message") or "").lower())

    def test_helper_status_balance_still_skips(self):
        snap = {**self.snap, "split": True, "balance": {"counts": [20, 28]}}
        st = HO.helper_status(snap, {"id": snap["model_id"]})
        self.assertTrue(st.get("balance"))
        self.assertIn("Balance split", st.get("message") or "")


class SpeedupsOneMacTests(unittest.TestCase):
    def test_runs_when_helper_is_active(self):
        import caravan_speedups as SU
        st = {"split": False, "worker": {"split": False},
              "active": {"guess_ahead": True, "two_chats_available": False}}
        with mock.patch.object(SU, "load_with", return_value=st), \
                mock.patch.object(SU, "run_set", return_value={"write_tok_s": 20.0}):
            out = SU.run_side("mlx", "mlx-community/X", port=1, urlopen=None,
                              status_fn=None, window_fn=lambda *a: 32768,
                              sets_args={"run_short": True, "run_edits": False,
                                         "run_long": False})
        ga = [r for r in out["rows"] if r["mode"] == "Guess-ahead"]
        self.assertTrue(ga)
        self.assertFalse(any(r.get("skipped") and "one Mac" in str(r.get("reason") or "")
                             for r in ga))
        self.assertTrue(any(not r.get("skipped") for r in ga))

    def test_skips_with_no_helper_reason_when_inactive(self):
        import caravan_speedups as SU
        st = {"split": False, "active": {"guess_ahead": False}}
        with mock.patch.object(SU, "load_with", return_value=st), \
                mock.patch.object(SU, "run_set", return_value={"write_tok_s": 20.0}):
            out = SU.run_side("mlx", "mlx-community/X", port=1, urlopen=None,
                              status_fn=None, window_fn=lambda *a: 32768,
                              sets_args={"run_short": True, "run_edits": False,
                                         "run_long": False})
        ga = [r for r in out["rows"] if r["mode"] == "Guess-ahead"]
        self.assertEqual(len(ga), 1)
        self.assertTrue(ga[0].get("skipped"))
        self.assertIn("no helper model on this Mac", ga[0]["reason"])
        self.assertNotIn("split models only", ga[0]["reason"])


@unittest.skipUnless(NODE, "node not installed")
class HelperButtonTextTests(unittest.TestCase):
    def say(self, st):
        js = english_source(ROOT / "proxy/web/helpers.js")
        a = js.index("  function helperButtonText(")
        b = js.index("  async function helperButtonClick(")
        prog = (js[a:b] + "\nconsole.log(JSON.stringify(helperButtonText("
                + json.dumps(st) + ")));")
        r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_one_mac_mlx_download_and_present(self):
        t = self.say({"kind": "mlx", "split": False, "known_id": "qwen3-30b-a3b",
                      "known_name": "Qwen3-0.6B-4bit", "known_size_mb": 335})
        self.assertIn("Download the Qwen3-0.6B-4bit helper (335 MB)", t["ask"])
        t = self.say({"kind": "mlx", "split": False, "present": True,
                      "present_name": "Qwen3-0.6B-4bit"})
        self.assertIn("already on this Mac (Qwen3-0.6B-4bit)", t["say"])
        t = self.say({"kind": "mlx", "split": False})
        self.assertIn("loaded MLX model", t["say"])
        self.assertNotIn("one Mac", t["say"])
        self.assertNotIn("do not use", t["say"])
        t = self.say({"kind": "mlx", "split": True, "balance": True,
                      "message": "A Balance split of an MLX model does not use a Guess-ahead helper"})
        self.assertIn("Balance split", t["say"])


class LocaleCopyTests(unittest.TestCase):
    def test_all_five_locales_updated_and_old_keys_gone(self):
        names = ("en", "es", "ru", "ja", "zh-Hans")
        locales = {}
        for name in names:
            locales[name] = json.loads((ROOT / "locales" / f"{name}.json").read_text())
        dropped = ("web.on_one_mac_mlx_models_do", "cli.speedups.on_one_mac_an_mlx_model")
        help_keys = (
            "web.a_smaller_model_guesses_upcoming_words_2",
            "server.web_settings.a_smaller_model_guesses_upcoming_words",
        )
        en = locales["en"]
        for k in dropped:
            for name, data in locales.items():
                self.assertNotIn(k, data, f"{name} still has {k}")
        self.assertIn("one Mac or a split", en[help_keys[0]])
        self.assertIn("one Mac or a split", en[help_keys[1]])
        self.assertNotIn("on a split model in our tests, but slower", en[help_keys[0]])
        self.assertEqual(en["web.no_missing_compatible_helper_for_the"],
                         "No missing compatible helper for the loaded MLX model.")
        self.assertNotIn("split MLX", en["web.no_missing_compatible_helper_for_the"])
        for name, data in locales.items():
            for k in help_keys:
                self.assertTrue(data[k].strip(), f"{name} {k} empty")
                self.assertNotEqual(data[k], en[k] if name != "en" else data[k] + "x")
            self.assertTrue(data["web.no_missing_compatible_helper_for_the"].strip())
            # Every locale still mentions a helper / Mac, not the old "not yet".
            self.assertNotIn("do not use a Guess-ahead helper yet",
                             data.get("web.no_missing_compatible_helper_for_the", ""))


if __name__ == "__main__":
    unittest.main()
