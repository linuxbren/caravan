"""Day 30: GGUF Auto chat window runs as close to the trained window as memory allows."""
from __future__ import annotations

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

import gguf_split as G  # noqa: E402
import gguf_self_tune as GST  # noqa: E402
import kv_auto  # noqa: E402
import web_restore as WR  # noqa: E402
import web_settings as WS  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

MIB = 1024 * 1024


def _meta(length, heads=32, arch="llama"):
    def fn(path):
        out = {"general.architecture": arch, f"{arch}.attention.head_count": heads}
        if length:
            out[f"{arch}.context_length"] = length
        return out
    return fn


def _decide(weights=4000.0, budget=18000.0, per_tok_q8=0.065, per_tok_f16=0.125, fixed=600.0):
    """A kv_auto.decide stand-in: need grows linearly with the window (MiB per token)."""
    def fn(model_path, n_slots, ctx_per_slot, n_ubatch=512, n_devices=1, **k):
        t = int(ctx_per_slot) * int(n_slots)
        return kv_auto.KvDecision("f16", "f16", "est", {
            "need_q8_0_mib": weights + fixed + per_tok_q8 * t,
            "need_f16_mib": weights + fixed + per_tok_f16 * t,
            "budget_mib": budget * max(1, int(n_devices)),
        })
    return fn


def _unknown(*a, **k):
    return kv_auto.KvDecision("q8_0", "q8_0", "can't estimate", {})


class AutoWindow(unittest.TestCase):
    def test_full_trained_window_when_it_fits(self):
        # 4000 + 600 + 0.065 * 131072 (~8520) + mask 256 = ~13.4K <= 18K
        self.assertEqual(G.auto_ctx("/m.gguf", decide=_decide(), meta_fn=_meta(131072)), 131072)

    def test_no_fixed_32k_cap(self):
        big = _decide(budget=10 ** 7)
        self.assertEqual(G.auto_ctx("/m.gguf", decide=big, meta_fn=_meta(262144)), 262144)
        self.assertIsNone(G.GGUF_CTX_AUTO_CAP)

    def test_native_window_not_in_the_list_is_used(self):
        # A model trained for 40960 gets 40960, not 32768.
        big = _decide(budget=10 ** 7)
        self.assertEqual(G.auto_ctx("/m.gguf", decide=big, meta_fn=_meta(40960)), 40960)
        self.assertEqual(G.ctx_candidates(40960)[-1], 40960)
        self.assertEqual(G.ctx_candidates(131072)[-1], 131072)
        self.assertNotIn(262144, G.ctx_candidates(131072))

    def test_largest_window_that_fits_memory(self):
        # q8_0 at 0.065 MiB/token: 65536 fits 18000, 131072 does not.
        tight = _decide(budget=9500.0)
        self.assertEqual(G.auto_ctx("/m.gguf", decide=tight, meta_fn=_meta(131072)), 65536)

    def test_never_below_the_old_rule(self):
        # Nothing fits: the old rule kept 8192; so does Day 30.
        none_fit = _decide(budget=100.0)
        self.assertEqual(G.auto_ctx("/m.gguf", decide=none_fit, meta_fn=_meta(131072)), 8192)
        for budget in (100.0, 5000.0, 7000.0, 9500.0, 18000.0, 10 ** 7):
            for trained in (4096, 8192, 32768, 40960, 131072, 262144):
                d = _decide(budget=budget)
                old = G.legacy_auto_ctx("/m.gguf", decide=d, meta_fn=_meta(trained))
                new = G.auto_ctx("/m.gguf", decide=d, meta_fn=_meta(trained))
                self.assertGreaterEqual(new, old, (budget, trained))
                self.assertLessEqual(new, max(trained, G.GGUF_CTX), (budget, trained))

    def test_unknown_memory_or_file_keeps_8192(self):
        self.assertEqual(G.auto_ctx("/missing.gguf"), 8192)
        self.assertEqual(G.auto_ctx("/m.gguf", decide=_unknown, meta_fn=_meta(131072)), 8192)
        self.assertEqual(G.auto_ctx("/m.gguf", decide=_decide(), meta_fn=_meta(None)), 8192)

    def test_split_budget_allows_a_longer_window(self):
        tight = _decide(budget=9500.0)
        one = G.auto_ctx("/m.gguf", decide=tight, meta_fn=_meta(131072), n_devices=1)
        two = G.auto_ctx("/m.gguf", decide=tight, meta_fn=_meta(131072), n_devices=2)
        self.assertEqual((one, two), (65536, 131072))

    def test_pinned_16bit_memory_sizes_with_16bit(self):
        d = _decide(budget=18000.0)
        self.assertEqual(G.auto_ctx("/m.gguf", decide=d, meta_fn=_meta(131072), cache_type="f16"), 65536)

    def test_flash_attention_off_counts_the_score_matrix(self):
        d = _decide(budget=18000.0)
        on = G.auto_ctx("/m.gguf", decide=d, meta_fn=_meta(131072), flash_attn="on")
        off = G.auto_ctx("/m.gguf", decide=d, meta_fn=_meta(131072), flash_attn="off")
        self.assertEqual(on, 131072)
        self.assertLess(off, on)
        # 32 heads x 131072 x 512 x 4 bytes = 8 GiB on top of the mask.
        self.assertAlmostEqual(
            G.attention_scratch_mib("/m.gguf", 131072, flash_attn="off", meta_fn=_meta(131072)),
            256 + 8192, places=3)
        self.assertAlmostEqual(G.attention_scratch_mib("/m.gguf", 131072, n_devices=2), 512, places=3)


class LaunchWindowFirst(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_learned_16bit_does_not_shorten_the_window(self):
        launch = G.resolve_launch("/m.gguf", tune={"cache_type": "f16"},
                                  decide=_decide(), meta_fn=_meta(131072))
        self.assertEqual(launch["ctx"], 131072)
        self.assertEqual(launch["lighter"], {"cache_type": "q8_0"})
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1], tune={"cache_type": "f16"},
                         decide=_decide(), meta_fn=_meta(131072), slot_root=self.tmp.name)
        self.assertEqual(a[a.index("-c") + 1], "131072")
        self.assertEqual(a[a.index("-ctk") + 1], "q8_0")
        self.assertEqual(a[a.index("-ctv") + 1], "q8_0")

    def test_learned_flash_off_falls_back_to_on(self):
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1], tune={"flash_attn": "off"},
                         decide=_decide(), meta_fn=_meta(131072), slot_root=self.tmp.name)
        self.assertEqual(a[a.index("-c") + 1], "131072")
        self.assertEqual(a[a.index("-fa") + 1], "on")

    def test_pinned_choices_stay_and_size_the_window(self):
        tune = {"cache_type": "f16", "pinned_knobs": ["cache_type"]}
        launch = G.resolve_launch("/m.gguf", tune=tune, decide=_decide(), meta_fn=_meta(131072))
        self.assertEqual(launch["ctx"], 65536)
        self.assertNotIn("lighter", launch)
        tune = {"flash_attn": "off", "pinned_knobs": ["flash_attn"]}
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1], tune=tune,
                         decide=_decide(), meta_fn=_meta(131072), slot_root=self.tmp.name)
        self.assertEqual(a[a.index("-fa") + 1], "off")
        self.assertLess(int(a[a.index("-c") + 1]), 131072)

    def test_learned_helper_never_shortens_the_window(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf") as f:
            f.write(b"x")
            f.flush()
            tune = {"guess_ahead": "on", "draft_path": f.name}
            with mock.patch.object(G, "helper_overhead_mib", return_value=6000.0):
                launch = G.resolve_launch("/m.gguf", tune=tune, decide=_decide(),
                                          meta_fn=_meta(131072))
            self.assertEqual(launch["ctx"], 131072)
            self.assertFalse(launch["helper_fits"])
            # Pinned On: the helper is part of the window size.
            tune["pinned_knobs"] = ["guess_ahead"]
            with mock.patch.object(G, "helper_overhead_mib", return_value=6000.0):
                launch = G.resolve_launch("/m.gguf", tune=tune, decide=_decide(),
                                          meta_fn=_meta(131072))
            self.assertLess(launch["ctx"], 131072)
            self.assertTrue(launch["helper_fits"])

    def test_saved_auto_window_is_sized_again(self):
        # An old Auto load saved ctx 32768; with ctx_auto it is sized again.
        launch = G.resolve_launch("/m.gguf", tune={"ctx": 32768, "ctx_auto": True},
                                  decide=_decide(), meta_fn=_meta(131072))
        self.assertEqual(launch["ctx"], 131072)
        self.assertTrue(launch["ctx_auto"])
        pinned = G.resolve_launch("/m.gguf", tune={"ctx": 32768},
                                  decide=_decide(), meta_fn=_meta(131072))
        self.assertEqual(pinned["ctx"], 32768)
        self.assertFalse(pinned["ctx_auto"])
        self.assertIn("ctx_auto", WR.GGUF_TUNE_KEYS)
        self.assertTrue(WR.restorable_gguf_tune({"ctx": 32768, "ctx_auto": True})["ctx_auto"])

    def test_native_value(self):
        launch = G.resolve_launch("/m.gguf", tune={"ctx": "native"},
                                  decide=_decide(), meta_fn=_meta(40960))
        self.assertEqual(launch["ctx"], 40960)
        self.assertFalse(launch["ctx_auto"])

    def test_unknown_memory_changes_nothing(self):
        launch = G.resolve_launch("/m.gguf", tune={"cache_type": "f16", "flash_attn": "off"},
                                  decide=_unknown, meta_fn=_meta(131072))
        self.assertEqual(launch["ctx"], 8192)
        self.assertNotIn("lighter", launch)


class SettingsRows(unittest.TestCase):
    def test_choices_go_past_64k_and_include_native(self):
        row = next(o for o in WS.OPTIONS if o["id"] == "chat_window")
        for v in ("65536", "131072", "262144", "native"):
            self.assertIn(v, row["values"])
        self.assertEqual(WS.normalize({"chat_window": "native"})["chat_window"], "native")
        self.assertEqual(WS.normalize({"chat_window": "131072"})["chat_window"], "131072")
        self.assertEqual(row.get("backends"), ("gguf",))

    def test_disabled_sizes_have_plain_reasons(self):
        d = G.disabled_ctx_values("/m.gguf", decide=_decide(budget=9500.0), meta_fn=_meta(131072))
        self.assertIn("262144", d)
        self.assertIn("shorter context (131072)", d["262144"])
        self.assertIn("131072", d)
        self.assertIn("will not fit in memory", d["131072"])
        self.assertNotIn("65536", d)
        self.assertIn("native", d)
        self.assertIn("will not fit", d["native"])
        for text in d.values():
            for word in ("GB", "MiB", "KV", "ctx", "q8_0", "f16"):
                self.assertNotIn(word, text)
        ok = G.disabled_ctx_values("/m.gguf", decide=_decide(), meta_fn=_meta(131072))
        self.assertNotIn("native", ok)
        self.assertNotIn("131072", ok)
        nofile = G.disabled_ctx_values("/m.gguf", decide=_decide(), meta_fn=_meta(None))
        self.assertIn("native", nofile)

    def test_options_for_reports_auto_and_native_in_plain_words(self):
        with mock.patch.object(G, "auto_ctx", return_value=131072), \
             mock.patch.object(G, "native_ctx", return_value=131072), \
             mock.patch.object(G, "disabled_ctx_values", return_value={"262144": "This model was trained for a shorter context (131072)."}):
            rows = WS.options_for("gguf", model_dir="/m.gguf")
        cw = next(o for o in rows if o["id"] == "chat_window")
        self.assertEqual(cw["auto_value"], 131072)
        self.assertEqual(cw["native_value"], 131072)
        self.assertIn("full trained context", cw["help"])
        self.assertIn("262144", cw["disabled_values"])
        with mock.patch.object(G, "auto_ctx", return_value=65536), \
             mock.patch.object(G, "native_ctx", return_value=131072), \
             mock.patch.object(G, "disabled_ctx_values", return_value={}):
            rows = WS.options_for("gguf", model_dir="/m.gguf")
        cw = next(o for o in rows if o["id"] == "chat_window")
        self.assertIn("longest that fits in memory", cw["help"])
        self.assertIn("131072", cw["help"])
        mlx = WS.options_for("mlx")
        self.assertFalse(any(o["id"] == "chat_window" for o in mlx))

    def test_apply_settings_window_pins(self):
        out = WS.apply_gguf_settings({}, {"chat_window": "131072"})
        self.assertEqual(out["ctx"], 131072)
        with mock.patch.object(G, "native_ctx", return_value=40960):
            out = WS.apply_gguf_settings({}, {"chat_window": "native"}, model_path="/m.gguf")
        self.assertEqual(out["ctx"], 40960)
        with mock.patch.object(G, "native_ctx", return_value=None):
            out = WS.apply_gguf_settings({"ctx": 8192}, {"chat_window": "native"}, model_path="/m.gguf")
        self.assertNotIn("ctx", out)
        out = WS.apply_gguf_settings({"ctx": 8192}, {"chat_window": "auto"})
        self.assertNotIn("ctx", out)


class TuningKeepsTheWindow(unittest.TestCase):
    def test_blockers(self):
        b = G.window_blockers("/m.gguf", decide=_decide(), meta_fn=_meta(131072))
        self.assertIn("cache_type=f16", b)
        self.assertIn("flash_attn=off", b)
        self.assertEqual(G.window_blockers("/m.gguf", decide=_decide(), meta_fn=_meta(131072),
                                           pins={"cache_type", "flash_attn", "ubatch"}), set())
        roomy = G.window_blockers("/m.gguf", decide=_decide(budget=10 ** 7), meta_fn=_meta(131072))
        self.assertNotIn("cache_type=f16", roomy)

    def test_autotune_skips_trials_that_need_a_shorter_window(self):
        items = {i["name"]: i for i in G.gguf_schedule(
            {"cache_type": "f16", "flash_attn": "on", "ubatch": 512}, [],
            blocked=["cache_type=f16", "flash_attn=off"])}
        self.assertEqual(items["cache_type"]["skip"], G.WINDOW_SKIP)
        self.assertIsNone(items["cache_type"]["challenger"])
        self.assertEqual(items["flash_attn"]["skip"], G.WINDOW_SKIP)
        self.assertIsNone(items["ubatch"]["skip"])
        # Nothing blocked: same plan as before Day 30.
        plain = {i["name"]: i for i in G.gguf_schedule({}, [])}
        self.assertEqual(plain["cache_type"]["challenger"], "q8_0")
        self.assertEqual(plain["flash_attn"]["challenger"], "off")
        # ubatch 1024 blocked: 256 is still tried.
        ub = {i["name"]: i for i in G.gguf_schedule({}, [], blocked=["ubatch=1024"])}
        self.assertEqual(ub["ubatch"]["challenger"], 256)

    def test_self_tuning_does_not_pick_a_blocked_trial(self):
        losses = ["cache_type=f16", "cache_type=q8_0", "flash_attn=off", "flash_attn=on"]
        t = GST.pick_trial({"flash_attn": "on", "ubatch": 512, "cache_type": "q8_0"}, set(), losses)
        self.assertEqual(t["name"], "ubatch")


class UiTrim(unittest.TestCase):
    def test_web_chat_trims_to_the_real_gguf_window(self):
        html = english_source(ROOT / "proxy" / "web" / "index.html")
        self.assertIn("function chatWindowTokens()", html)
        self.assertIn("chatWindowTokens() - (maxTokens || 768) - 256", html)
        self.assertIn('native: "Native"', html)


class SplitLoadNotes(unittest.TestCase):
    """Day 30: a split load that worked showed "Couldn't start the model on
    the other Mac" because its rpc-server success line names the tunnel."""

    def test_success_line_is_not_turned_into_a_failure(self):
        import web_tunnels as T
        ok = "rpc-server on prf-hays-exo02 up (pid 4242), tunnel 127.0.0.1:50062"
        out = T.plain_load_status(ok, mac="2nd Mac")
        self.assertNotIn("Couldn't", out)
        self.assertIn("up (pid 4242)", out)
        self.assertIn("2nd Mac", out)
        self.assertNotIn("prf-hays", out)
        for line in ("starting rpc-server on prf-hays-exo02 (127.0.0.1:50052, reached over SSH)",
                     "link to prf-hays-exo02: Thunderbolt, en2, 0.44 ms",
                     "switching to Qwen (GGUF, llama.cpp, split across My Mac + prf-hays-exo02)"):
            out = T.plain_load_status(line, mac="2nd Mac")
            self.assertIn("2nd Mac", out)
            self.assertNotIn("prf-hays", out)
            self.assertNotIn("Couldn't", out)

    def test_real_tunnel_failures_still_get_the_plain_failure(self):
        import web_tunnels as T
        bad = "SSH tunnel to prf-hays-exo02 failed: bind [127.0.0.1]:50062: Address already in use"
        self.assertEqual(T.plain_load_status(bad, mac="2nd Mac"),
                         "Couldn't start the model on the 2nd Mac. Try loading again.")
        bad2 = "tunnel to caravan-dcbb9f1b9cd8cab4dcfa61388dffe4ec did not open"
        self.assertTrue(T.plain_load_status(bad2, mac="2nd Mac").startswith("Couldn't"))


class LongReadTimeout(unittest.TestCase):
    """Day 30 live test: a ~116K-token prompt on one Mac (Llama 3.1 8B) was
    cut off by the 30-minute wait for the model's first bytes."""

    def test_chat_wait_is_long_enough_for_a_full_window(self):
        src = (ROOT / "proxy" / "web_server.py").read_text()
        self.assertIn("urlopen(req, timeout=REPLY_TIMEOUT_S)", src)
        self.assertNotIn("urlopen(req, timeout=1800)", src)
        import re
        m = re.search(r'CARAVAN_REPLY_TIMEOUT_S", "(\d+)"', src)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 7200)


class BenchReloadOfLoadedModel(unittest.TestCase):
    """Day 30 live check: `caravan bench` on the model that was already
    loaded measured while it restarted (HTTP 502), then could not put it
    back ("a model switch is already in progress", HTTP 400)."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import caravan_bench as B
        self.B = B
        self.now = [1000.0]

    def _run(self, statuses, load_error=None):
        B = self.B
        seq = list(statuses)
        calls = []

        def urlopen(url, data=None, timeout=30, headers=None):
            calls.append(url)
            if url.endswith("/api/models/load"):
                if load_error:
                    raise load_error
                return {"status": "ready"}
            return {"worker": seq.pop(0) if len(seq) > 1 else seq[0]}

        def sleep(s):
            self.now[0] += s

        got = B.load_model(8190, "gguf/m", urlopen=urlopen, wait=30,
                           clock=lambda: self.now[0], sleep=sleep)
        return got, calls

    def test_waits_past_the_stale_ready_of_the_old_instance(self):
        old = {"status": "ready", "model_id": "gguf/m", "progress": [{"t": 900.0, "msg": "ready"}]}
        stopping = {"status": "stopping", "model_id": "gguf/m", "progress": [{"t": 1000.0, "msg": "switching to m"}]}
        fresh = {"status": "ready", "model_id": "gguf/m", "progress": [{"t": 1000.0, "msg": "switching to m"}, {"t": 1003.0, "msg": "ready"}]}
        got, calls = self._run([old, stopping, stopping, fresh])
        self.assertEqual(got["worker"], fresh)
        self.assertGreaterEqual(sum(1 for c in calls if c.endswith("/api/status")), 4)

    def test_a_switch_already_running_is_waited_for(self):
        import io, urllib.error
        err = urllib.error.HTTPError("u", 400, "Bad Request", {},
                                     io.BytesIO(b'{"error": "a model switch is already in progress"}'))
        loading = {"status": "starting_lead", "model_id": "gguf/m", "progress": [{"t": 990.0, "msg": "starting"}]}
        ready = {"status": "ready", "model_id": "gguf/m", "progress": [{"t": 995.0, "msg": "ready"}]}
        got, _ = self._run([loading, ready], load_error=err)
        self.assertEqual(got["worker"], ready)

    def test_other_load_errors_still_fail(self):
        import io, urllib.error
        err = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b'{"error": "unknown model"}'))
        with self.assertRaises(urllib.error.HTTPError):
            self._run([{"status": "idle"}], load_error=err)

    def test_status_without_notes_keeps_the_old_rule(self):
        got, _ = self._run([{"status": "ready", "model_id": "gguf/m"}])
        self.assertEqual(got["worker"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
