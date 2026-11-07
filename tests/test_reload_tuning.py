"""Day 15: self-tuning covers reload options; Deep/Quick optimize runner."""
from __future__ import annotations

import sys
import tempfile
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

    def test_coverage(self):
        e = {}
        self.assertFalse(TS.coverage(e)["done"])
        q = TS.coverage(e, mode="quick")
        self.assertEqual({i["name"] for i in q["items"]}, set(TS.LIVE_VALUES))
        d = TS.coverage(e, pinned={"guess_ahead"})
        self.assertNotIn("guess_ahead", {i["name"] for i in d["items"]})


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


# The legacy Deep/Quick runner tests moved to test_optimize_now.py. Reload
# learning above remains covered independently of the walk-away scheduler.

if __name__ == "__main__":
    unittest.main()
