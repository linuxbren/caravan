from __future__ import annotations

import unittest

import optimize_schedule as AB
import gguf_split as G
from web_optimize import experimental_settings

FP = "f" * 64


def active(**kw):
    a = {"kv_bits": 16, "fuse_kernels": "off", "keepalive": True, "native_mtp": False,
         "adaptive_lookup": False, "native_mtp_on_disk": True, "split": False}
    a.update(kw)
    return a


def item(items, name):
    return next(i for i in items if i["name"] == name)


class ExperimentalSweeps(unittest.TestCase):
    def test_mtp_and_lookup_scheduled_last_one_at_a_time(self):
        items = AB.schedule({}, {}, active(), FP)
        names = [i["name"] for i in items]
        self.assertEqual(names[-2:], ["native_mtp", "adaptive_lookup"])
        self.assertEqual(item(items, "native_mtp")["challenger"], True)
        self.assertEqual(item(items, "adaptive_lookup")["challenger"], True)

    def test_mtp_unavailable_on_split_or_without_head(self):
        self.assertEqual(item(AB.schedule({}, {}, active(split=True), FP), "native_mtp")["skip"], "unavailable")
        self.assertEqual(item(AB.schedule({}, {}, active(native_mtp_on_disk=False), FP), "native_mtp")["skip"], "unavailable")

    def test_recorded_loser_skipped(self):
        entry = {"optimize_hardware": {FP: {"losses": [AB.TS.option_id("native_mtp", True)]}}}
        self.assertEqual(item(AB.schedule(entry, {}, active(), FP), "native_mtp")["skip"], "already lost or blocked")

    def test_mtp_needs_16bit_kv(self):
        self.assertIsNone(item(AB.schedule({}, {}, active(kv_bits=8), FP), "native_mtp")["challenger"])

    def test_pinned_by_page_setting(self):
        self.assertEqual(item(AB.schedule({}, {"prompt_lookup": "off"}, active(), FP), "adaptive_lookup")["skip"], "pinned")

    def test_winner_not_used_as_incumbent(self):
        base = AB.baseline({"winner": {"native_mtp": True}}, active())
        self.assertFalse(base["native_mtp"])

    def test_settings_mapping(self):
        self.assertEqual(experimental_settings({"guess_ahead": "auto"}, {"native_mtp": True})["guess_ahead"], "mtp")
        s = experimental_settings({}, {"adaptive_lookup": True})
        self.assertEqual((s["prompt_lookup"], s["pipeline_chats"]), ("adaptive", "1"))
        self.assertEqual(experimental_settings({"prompt_lookup": "adaptive"}, {"adaptive_lookup": False})["prompt_lookup"], "auto")

    def test_validate_bool(self):
        with self.assertRaises(ValueError):
            AB.validate("native_mtp", 1)


class GgufTuning(unittest.TestCase):
    def test_args(self):
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1], tune={"flash_attn": "off", "ubatch": 1024})
        self.assertIn("-fa", a); self.assertEqual(a[a.index("-fa") + 1], "off")
        self.assertEqual(a[a.index("-ub") + 1], "1024")
        with self.assertRaises(ValueError):
            G.llama_args("/m.gguf", port=1, peers=[], shares=[1], tune={"ubatch": 7})

    def test_schedule_skips_losers(self):
        items = G.gguf_schedule({}, ["flash_attn=off", "ubatch=256"])
        self.assertEqual(items[0]["skip"], "already lost")
        self.assertEqual(items[1]["challenger"], 1024)


if __name__ == "__main__":
    unittest.main()
