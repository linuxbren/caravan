"""Day 15: self-tuning covers reload options; Optimize now runner."""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
sys.path.insert(0, str(REPO / "agent"))

import tuned_settings as TS  # noqa: E402
import web_optimize  # noqa: E402
import web_settings  # noqa: E402
from web_workers import WorkerManager  # noqa: E402

ALL = list(TS.RELOAD_TRIO)


def feed(entry, used, tps, n, auto=ALL):
    out = None
    for _ in range(n):
        out = TS.observe_reload(entry, settings_used=used, norm_tps=tps, auto_names=auto)
    return out


class ReloadTrialTest(unittest.TestCase):
    def test_queue_each_of_three(self):
        for name in ALL:
            e = {}
            TS.plan_reload(e, [name])
            used = {name: TS.RELOAD_DEFAULTS[name]}
            out = feed(e, used, 10.0, TS.MIN_SAMPLES, auto=[name])
            self.assertEqual(out["queued"]["name"], name)
            self.assertIn(name, e["pending_reload"])
            self.assertNotEqual(e["pending_reload"][name], TS.RELOAD_DEFAULTS[name])

    def test_applied_on_load_then_promoted(self):
        e = {}
        TS.plan_reload(e, ALL)
        feed(e, dict(TS.RELOAD_DEFAULTS), 10.0, TS.MIN_SAMPLES)
        self.assertEqual(e["pending_reload"], {"kv_bits": 8})
        plan = TS.plan_reload(e, ALL)          # next load
        self.assertEqual(plan["values"]["kv_bits"], 8)
        self.assertEqual(plan["trial"]["incumbent"], 16)
        self.assertEqual(e["pending_reload"], {})
        used = dict(TS.RELOAD_DEFAULTS, kv_bits=8)
        out = feed(e, used, 12.0, TS.MIN_SAMPLES)
        self.assertTrue(any(p[0] == "kv_bits" for p in out["promotions"]) or
                        e["winner"]["kv_bits"] == 8)
        self.assertEqual(e["winner"]["kv_bits"], 8)
        self.assertIsNone(e["reload_trial"])

    def test_rolled_back_when_slower(self):
        e = {}
        TS.plan_reload(e, ALL)
        feed(e, dict(TS.RELOAD_DEFAULTS), 10.0, TS.MIN_SAMPLES)
        TS.plan_reload(e, ALL)
        used = dict(TS.RELOAD_DEFAULTS, kv_bits=8)
        # last trial reply finishes the trial (and may queue the next one)
        out = feed(e, used, 9.0, TS.MIN_SAMPLES)
        self.assertEqual(e["winner"]["kv_bits"], 16)
        self.assertTrue(out["rolled_back"])
        st = TS.reload_status(e, used, ALL)
        # Running 8-bit lost; next load either tries 4-bit or goes back to 16.
        want = [c for c in st["reload_wanted"] if c["name"] == "kv_bits"]
        self.assertEqual(len(want), 1)
        self.assertIn(want[0]["to"], ("4-bit", "16-bit"))
        e["pending_reload"] = {}
        st = TS.reload_status(e, used, ALL)
        self.assertEqual(st["reload_wanted"][0]["why"], "back to winner")

    def test_pinned_not_learned(self):
        e = {}
        plan = TS.plan_reload(e, ["kv_bits"])
        self.assertEqual(set(plan["values"]), {"kv_bits"})
        feed(e, {"kv_bits": 16, "keepalive": False}, 10.0, 5, auto=["kv_bits"])
        self.assertEqual(TS.samples_of(e, "keepalive", False), 0)

    def test_live_learning_untouched(self):
        # observe_reply (Day 10/13) still ignores reload options.
        e = {}
        TS.observe_reply(e, settings_used={"guess_ahead": True, "kv_bits": 8},
                         completion_tokens=100, total_s=2.0)
        self.assertEqual(TS.samples_of(e, "kv_bits", 8), 0)
        self.assertEqual(TS.samples_of(e, "guess_ahead", True), 1)

    def test_pending_left_alone_when_hold(self):
        e = {"winner": dict(TS.RELOAD_DEFAULTS), "pending_reload": {"kv_bits": 8}}
        plan = TS.plan_reload(e, ALL, apply_pending=False)
        self.assertEqual(plan["values"]["kv_bits"], 16)
        self.assertIsNone(plan["trial"])
        self.assertEqual(e["pending_reload"]["kv_bits"], 8)


class LauncherArgsTest(unittest.TestCase):
    def test_plan_args_and_pins(self):
        with tempfile.TemporaryDirectory() as d:
            m = WorkerManager(state_dir=Path(d) / "s")
            m.tuned_path = Path(d) / "t.json"
            ent = {"lead_path": str(Path(d) / "Model-X")}
            s = web_settings.normalize({"kv_bits": "4"})
            lead, packer = web_settings.to_args(s)
            m.plan_reload_args(ent, s, lead, packer)
            self.assertIn("--learn-reload-auto", lead)
            self.assertEqual(lead[lead.index("--learn-reload-auto") + 1], "fuse_kernels,keepalive")
            self.assertEqual(lead.count("--kv-bits"), 1)  # only the pin
            self.assertIn("--fuse-kernels", packer)
            # queued trial is applied on load
            st = TS.load_store(m.tuned_path)
            key = TS.entry_key(ent["lead_path"], spanned=True)
            st["models"][key]["pending_reload"] = {"keepalive": False}
            TS.save_store(st, m.tuned_path)
            s2 = web_settings.normalize({})
            lead2, packer2 = web_settings.to_args(s2)
            lines = m.plan_reload_args(ent, s2, lead2, packer2)
            self.assertIn("--no-split-keepalive", lead2)
            self.assertIn("--no-split-keepalive", packer2)
            self.assertTrue(any("try GPU keep-warm off" in x for x in lines))

    def test_self_tune_off_no_args(self):
        m = WorkerManager(state_dir=Path(tempfile.mkdtemp()))
        s = web_settings.normalize({"self_tune": "off"})
        lead, packer = web_settings.to_args(s)
        self.assertEqual(m.plan_reload_args({"lead_path": "/x/M"}, s, lead, packer), [])
        self.assertNotIn("--learn-reload-auto", lead)

    def test_from_args(self):
        cmd = ("python mlx_worker.py --model /m --pin-guess-ahead --kv-bits 4 "
               "--fuse-kernels off --learn-reload-auto fuse_kernels,keepalive")
        s = web_settings.from_args(cmd)
        self.assertEqual(s["guess_ahead"], "on")
        self.assertEqual(s["kv_bits"], "4")
        self.assertEqual(s["fuse_kernels"], "auto")

    def test_reload_force_holds_value(self):
        with tempfile.TemporaryDirectory() as d:
            m = WorkerManager(state_dir=Path(d) / "s")
            m.tuned_path = Path(d) / "t.json"
            ent = {"lead_path": str(Path(d) / "Model-X")}
            s = web_settings.normalize({})
            lead, packer = web_settings.to_args(s)
            m.plan_reload_args(ent, s, lead, packer, hold_trials=True,
                               reload_force={"kv_bits": 8}, freeze_forced=True)
            self.assertEqual(lead[lead.index("--kv-bits") + 1], "8")
            learned = lead[lead.index("--learn-reload-auto") + 1]
            self.assertNotIn("kv_bits", learned)
            self.assertIn("fuse_kernels", learned)

    def test_packer_k_saved_then_pending(self):
        with tempfile.TemporaryDirectory() as d:
            m = WorkerManager(state_dir=Path(d) / "s")
            m.tuned_path = Path(d) / "t.json"
            lead = str(Path(d) / "Model-X")
            st, e = m._tuned_entry(lead, create=True)
            e["winner"]["packer_layers"] = 18
            e["pending_reload"]["packer_layers"] = 19
            TS.save_store(st, m.tuned_path)
            entry = {"lead_path": lead, "packer_layers": 16}
            self.assertEqual(m._packer_k(entry), 19)
            self.assertEqual(m._packer_k(entry), 18)


def _baseline():
    return {
        "guess_ahead": True, "shared_prefix": False, "pipeline_chats": 2,
        "kv_bits": 16, "fuse_kernels": "off", "keepalive": True, "packer_layers": 16,
    }


class ScheduleTest(unittest.TestCase):
    def test_one_challenger_covers_every_option(self):
        ui = {s["ui"] for s in TS.OPTIMIZE_KNOBS if s["ui"]}
        self.assertEqual(ui, {o["id"] for o in web_settings.OPTIONS if o["id"] != "self_tune"})
        items = TS.build_schedule(
            {}, fingerprint="spanned:24:24", settings=web_settings.normalize({}),
            baseline=_baseline(), n_layers=32)
        self.assertEqual([i["name"] for i in items],
                         ["guess_ahead", "shared_prefix", "pipeline_chats", "kv_bits",
                          "fuse_kernels", "keepalive", "packer_layers"])
        self.assertTrue(all(i["skip"] is None and i["challenger"] is not None for i in items))
        kv = next(i for i in items if i["name"] == "kv_bits")
        self.assertEqual(kv["incumbent"], 16)
        self.assertEqual(kv["challenger"], 8)  # one step, not 8 and 4
        self.assertEqual(next(i for i in items if i["name"] == "packer_layers")["challenger"], 15)

    def test_skip_pinned_and_losses_until_fingerprint_changes(self):
        e = {}
        TS.remember_loss(e, "spanned:24:24", "guess_ahead", False)
        TS.remember_loss(e, "spanned:24:24", "kv_bits", 8)
        pinned = web_settings.normalize({"fuse_kernels": "on"})
        items = TS.build_schedule(
            e, fingerprint="spanned:24:24", settings=pinned, baseline=_baseline(), n_layers=32)
        by = {i["name"]: i for i in items}
        self.assertEqual(by["guess_ahead"]["skip"], "already lost")
        self.assertEqual(by["fuse_kernels"]["skip"], "pinned")
        self.assertEqual(by["kv_bits"]["challenger"], 4)
        again = TS.build_schedule(
            e, fingerprint="spanned:16:16", settings=web_settings.normalize({}),
            baseline=_baseline(), n_layers=32)
        self.assertEqual(next(i for i in again if i["name"] == "guess_ahead")["challenger"], False)
        self.assertEqual(next(i for i in again if i["name"] == "kv_bits")["challenger"], 8)

    def test_ab_pick_needs_a_margin(self):
        self.assertEqual(TS.ab_pick([10, 10, 10], [10.2, 10.2, 10.2]), "incumbent")
        self.assertEqual(TS.ab_pick([10, 10, 10], [11, 11, 11]), "challenger")
        self.assertEqual(TS.ab_pick([], [11]), "challenger")
        self.assertEqual(TS.ab_pick([11], []), "incumbent")


class FakeMgr:
    lead_port = 1
    n_layers = 32

    def __init__(self, store_path, settings=None):
        self.tuned_path = store_path
        self._lead_path = "/x/Fake-Model"
        self.snap = {"status": "ready", "model_id": "fake",
                     "settings": web_settings.normalize(settings or {})}
        self.running = dict(TS.RELOAD_DEFAULTS)
        self.live = {"guess_ahead": True, "shared_prefix": False,
                     "pipeline_chats": 2, "packer_layers": 16}
        self.reloads = []
        self.holds = []
        self.fingerprint = "spanned:24:24"
        self.paused = False
        self._switch_thread = None

    def snapshot(self):
        return dict(self.snap)

    _tuned_entry = WorkerManager._tuned_entry

    def hardware_fingerprint(self):
        return self.fingerprint

    def catalog_packer_layers(self):
        return 16

    def lead_active_settings(self):
        return {
            "guess_ahead": self.live["guess_ahead"],
            "guess_ahead_loaded": True,
            "shared_start": self.live["shared_prefix"],
            "pipeline_chats": self.live["pipeline_chats"],
            "keepalive": self.running["keepalive"],
            "kv_bits": self.running["kv_bits"],
            "fuse_kernels": self.running["fuse_kernels"],
            "reload_auto": list(TS.RELOAD_TRIO),
            "self_tune": True,
        }

    def switch(self, model_id, wait=True, settings=None, packer_layers=None,
               hold_trials=False, reload_force=None, freeze_forced=False):
        settings = settings or {}
        for n, v in (reload_force or {}).items():
            if settings.get(n, "auto") == "auto" and n in TS.RELOAD_TRIO:
                self.running[n] = TS.norm_knob(n, v)
        if packer_layers is not None:
            self.live["packer_layers"] = int(packer_layers)
        self.snap["settings"] = settings
        self.reloads.append({"force": dict(reload_force or {}), "packer": packer_layers})

    def sweep(self, body):
        body = body or {}
        if body.get("release"):
            self.paused = False
            return {"paused": False, "winner": self._winner()}
        self.paused = True
        if body.get("clear_pending"):
            st, e = self._tuned_entry(self._lead_path, create=True)
            e["pending_reload"] = {}
            e["reload_trial"] = None
            TS.save_store(st, self.tuned_path)
        for k, v in (body.get("hold") or {}).items():
            self.live[k] = v
        if body.get("hold"):
            self.holds.append(dict(body["hold"]))
        commit = body.get("commit")
        if commit:
            st, e = self._tuned_entry(self._lead_path, create=True)
            TS.commit_ab(e, fingerprint=commit.get("fingerprint") or self.fingerprint,
                         name=commit["name"], winner_value=commit["winner"],
                         lost_value=commit.get("lost"))
            TS.save_store(st, self.tuned_path)
            if commit["name"] in ("guess_ahead", "shared_prefix", "pipeline_chats", "packer_layers"):
                self.live[commit["name"]] = TS.norm_knob(commit["name"], commit["winner"])
        return {"paused": True, "winner": self._winner()}

    def _winner(self):
        try:
            _st, e = self._tuned_entry(self._lead_path)
        except (OSError, ValueError, TypeError):
            return {}
        return dict((e or {}).get("winner") or {})


def _timed_send(mgr):
    def send(_msgs):
        e = 1.0
        if mgr.running["kv_bits"] == 8:
            e *= 0.8
        elif mgr.running["kv_bits"] == 4:
            e *= 1.25
        if mgr.running["fuse_kernels"] == "on":
            e *= 0.85
        if not mgr.running["keepalive"]:
            e *= 1.2
        if mgr.live.get("packer_layers", 16) != 16:
            e *= 1.1
        if mgr.live.get("guess_ahead") is False:
            e *= 1.2
        ttft = e * (0.45 if mgr.live.get("shared_prefix") else 0.7)
        return {"elapsed": e, "ttft": ttft, "completion_tokens": 40, "total_s": e,
                "prefill_s": e * 0.2, "prompt_tokens": 30, "simulated": True}
    return send


class OptimizerTest(unittest.TestCase):
    def test_optimize_now_one_ab_per_option(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = FakeMgr(Path(d) / "t.json")
            opt = web_optimize.Optimizer(mgr, inflight=lambda: 0, send=_timed_send(mgr),
                                         sleep=lambda s: None)
            opt.start()
            opt._thread.join(10)
            s = opt.snapshot()
            self.assertEqual(s["phase"], "done", s)
            self.assertEqual(s["mode"], "now")
            self.assertTrue(s["summary"]["complete"])
            w = s["summary"]["winner"]
            self.assertEqual(w["kv_bits"], 8)
            self.assertEqual(w["fuse_kernels"], "on")
            self.assertTrue(w["shared_prefix"])
            self.assertTrue(w["guess_ahead"])
            self.assertEqual(w["pipeline_chats"], 2)
            self.assertTrue(w["keepalive"])
            self.assertEqual(w["packer_layers"], 16)
            # One challenger reload each, plus a restore when the challenger lost.
            self.assertEqual(len(mgr.reloads), 6, mgr.reloads)
            self.assertTrue(all(int(r["force"].get("kv_bits", 8)) != 4 for r in mgr.reloads))
            self.assertEqual(sum(1 for r in mgr.reloads if r["packer"] == 15), 1)
            self.assertTrue(any(h.get("guess_ahead") is False for h in mgr.holds))
            self.assertFalse(mgr.paused)  # everyday learning resumed
            self.assertIsNotNone(s["reply_s"])
            by = {i["name"]: i for i in s["schedule"]}
            self.assertTrue(all(i["state"] == "kept" for i in by.values()))

    def test_pinned_reload_knob_is_not_reloaded(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = FakeMgr(Path(d) / "t.json", settings={"kv_bits": "4"})
            opt = web_optimize.Optimizer(mgr, inflight=lambda: 0, send=_timed_send(mgr),
                                         sleep=lambda s: None)
            opt.start("deep")  # ignored; there is no Quick/Deep path
            opt._thread.join(10)
            s = opt.snapshot()
            self.assertEqual(s["phase"], "done", s)
            kv = next(i for i in s["schedule"] if i["name"] == "kv_bits")
            self.assertEqual(kv["state"], "skipped")
            self.assertEqual(kv["detail"], "pinned")
            self.assertTrue(all("kv_bits" not in r["force"] or mgr.snap["settings"]["kv_bits"] != "auto"
                                for r in mgr.reloads))
            self.assertLess(len(mgr.reloads), 6)

    def test_skips_when_every_challenger_already_lost(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = FakeMgr(Path(d) / "t.json")
            st, e = mgr._tuned_entry(mgr._lead_path, create=True)
            e["winner"] = dict(_baseline())
            fp = mgr.fingerprint
            for name, val in (("guess_ahead", False), ("shared_prefix", True),
                              ("pipeline_chats", 1), ("kv_bits", 8), ("kv_bits", 4),
                              ("fuse_kernels", "on"), ("keepalive", False),
                              ("packer_layers", 15), ("packer_layers", 17),
                              ("packer_layers", 14), ("packer_layers", 18)):
                TS.remember_loss(e, fp, name, val)
            TS.save_store(st, mgr.tuned_path)
            opt = web_optimize.Optimizer(mgr, inflight=lambda: 0, send=_timed_send(mgr),
                                         sleep=lambda s: None)
            opt.start()
            opt._thread.join(10)
            s = opt.snapshot()
            self.assertEqual(s["phase"], "done", s)
            self.assertEqual(s["prompts"], 0)
            self.assertEqual(mgr.reloads, [])
            self.assertTrue(all(i["state"] == "skipped" for i in s["schedule"]))

    def test_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = FakeMgr(Path(d) / "t.json")
            opt = web_optimize.Optimizer(mgr, inflight=lambda: 0, sleep=lambda s: None,
                                         send=lambda m: (opt.cancel(), {"elapsed": 0.2, "simulated": True,
                                                                        "completion_tokens": 8,
                                                                        "total_s": 0.2, "ttft": 0.05,
                                                                        "prefill_s": 0.02,
                                                                        "prompt_tokens": 4})[1])
            opt.start()
            opt._thread.join(10)
            self.assertEqual(opt.snapshot()["phase"], "canceled")
            self.assertFalse(mgr.paused)

    def test_eta_from_measured_times(self):
        self.assertIsNone(web_optimize.eta_s(prompts_left=3, reloads_left=1,
                                             reply_s=None, reload_s=None))
        self.assertEqual(web_optimize.eta_s(prompts_left=3, reloads_left=1,
                                            reply_s=5.0, reload_s=60.0), 75.0)
        self.assertIsNone(web_optimize.eta_s(prompts_left=0, reloads_left=1,
                                             reply_s=5.0, reload_s=None))

    def test_shared_prompt_long(self):
        sys_msg = web_optimize.prompt_plan(0)[0]["content"]
        self.assertGreater(len(sys_msg) / 4, TS.SHARED_PREFIX_MIN_PROMPT)

    def test_sweep_pause_skips_everyday_observe(self):
        import mlx_worker as W
        held = {}

        class E:
            def __init__(self):
                self._sweep_pause = False
                self._learn_enabled = True
                self._learn_entry = {"reply_n": 0, "winner": {}, "stats": {}}
                self._learn_explicit = {}
                self._learn_trial = {"name": "guess_ahead", "remaining": 2}
                self._learn_lock = threading.Lock()
                self.client = object()
                self.draft_model = object()
                self.pipeline_chats = 2
                self._learn_guess_override = None
                self.model_dir = None

            def _set_shared_prefix(self, enabled, reason=""):
                held["shared"] = enabled

        e = E()
        out = W.apply_sweep_hold(e, {"pause": True, "hold": {
            "guess_ahead": False, "shared_prefix": True, "pipeline_chats": 1}})
        self.assertTrue(out["paused"])
        self.assertFalse(e._learn_guess_override)
        self.assertTrue(held["shared"])
        self.assertEqual(e.pipeline_chats, 1)
        self.assertIsNone(e._learn_trial)
        before = e._learn_entry["reply_n"]
        W.Engine._learn_observe(e, {"completion_tokens": 10, "total_s": 1.0})
        self.assertEqual(e._learn_entry["reply_n"], before)
        W.apply_sweep_hold(e, {"release": True})
        self.assertFalse(e._sweep_pause)


if __name__ == "__main__":
    unittest.main()
