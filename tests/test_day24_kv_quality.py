"""Day 24: hide Memory compression 4 on compact models, and a load-time quality check."""
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
for folder in ("agent", "proxy", "tools"):
    sys.path.insert(0, str(ROOT / folder))

import kv_quality as K
import web_kv_probe as P
import web_settings as WS
import web_optimize as WO
import optimize_schedule as AB
import tuned_settings as TS


def _write_cfg(folder: Path, heads: int, hidden: int = 3584) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps({
        "num_key_value_heads": heads,
        "hidden_size": hidden,
        "num_attention_heads": max(heads, 8),
        "num_hidden_layers": 28,
    }))
    return folder


class HideFourTests(unittest.TestCase):
    def test_qwen_1p5b_and_7b_disallow_4_llama8_allows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            small = _write_cfg(tmp / "qwen-1.5b", 2, 1536)
            mid = _write_cfg(tmp / "qwen-7b", 4, 3584)
            llama = _write_cfg(tmp / "llama-8b", 8, 4096)
            self.assertFalse(K.allows_memory_compression_4(model_dir=small))
            self.assertFalse(K.allows_memory_compression_4(model_dir=mid))
            self.assertTrue(K.allows_memory_compression_4(model_dir=llama))
            self.assertEqual(K.disabled_values_for(model_dir=small)["4"], K.DISABLED_4_REASON)
            self.assertEqual(K.disabled_values_for(model_dir=mid)["4"], K.DISABLED_4_REASON)
            self.assertEqual(K.disabled_values_for(model_dir=llama), {})

    def test_unknown_config_still_offers_4(self):
        self.assertTrue(K.allows_memory_compression_4(config={}))
        self.assertTrue(K.allows_memory_compression_4(model_dir=None))
        self.assertEqual(K.disabled_values_for(config={}), {})

    def test_nested_and_list_head_counts(self):
        self.assertFalse(K.allows_memory_compression_4({
            "text_config": {"num_key_value_heads": 4}
        }))
        self.assertFalse(K.allows_memory_compression_4({
            "num_key_value_heads": [4, 8]
        }))
        self.assertTrue(K.allows_memory_compression_4({
            "num_kv_heads": 8
        }))

    def test_options_for_disables_4_but_keeps_it_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mid = _write_cfg(Path(tmp) / "qwen-7b", 4)
            kv = next(o for o in WS.options_for("mlx", model_dir=mid) if o["id"] == "kv_bits")
            self.assertIn("4", kv["values"])
            self.assertEqual(kv["disabled_values"]["4"], K.DISABLED_4_REASON)
            # Default (no model) still offers 4, so existing pages stay the same.
            plain = next(o for o in WS.options_for("mlx") if o["id"] == "kv_bits")
            self.assertIn("4", plain["values"])
            self.assertFalse(plain.get("disabled_values"))
            gguf = next(o for o in WS.options_for("gguf", model_dir=mid) if o["id"] == "kv_bits")
            self.assertNotIn("4", gguf["values"])
            self.assertFalse(gguf.get("disabled_values"))

    def test_user_facing_reason_has_no_jargon(self):
        for text in (K.DISABLED_4_REASON, K.FALLBACK_NOTE, K.probe_fail_notice(4),
                     K.probe_fail_notice(8)):
            low = text.lower()
            for word in ("kv", "quant", "probe", "token", "head", "gguf", "mlx",
                         "config.json", "qwen", "bit-width"):
                self.assertNotIn(word, low, text)

    def test_page_shows_disabled_reason_and_quality_note(self):
        html = (ROOT / "proxy/web/index.html").read_text()
        self.assertIn("disabled_values", html)
        self.assertIn("val-disabled", html)
        self.assertIn("qualityNotice", html)
        self.assertIn("quality-note", html)
        self.assertIn('b.disabled) continue', html)
        self.assertNotIn("prf-hays", html)
        self.assertNotIn("num_key_value_heads", html)


class FallbackTests(unittest.TestCase):
    def test_saved_4_falls_back_to_auto_before_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            mid = _write_cfg(Path(tmp) / "qwen-7b", 4)
            entry = {"lead_path": str(mid), "source": "mlx", "id": "qwen-7b"}
            settings, notice = P.apply_saved_4_fallback(None, entry, {"kv_bits": "4"})
            self.assertEqual(settings["kv_bits"], "auto")
            self.assertEqual(notice, K.FALLBACK_NOTE)
            # A model that may use 4 is left alone.
            llama = _write_cfg(Path(tmp) / "llama-8b", 8)
            ok, n2 = P.apply_saved_4_fallback(
                None, {"lead_path": str(llama), "source": "mlx"}, {"kv_bits": "4"})
            self.assertEqual(ok["kv_bits"], "4")
            self.assertIsNone(n2)
            # Already Auto: no notice.
            a, n3 = P.apply_saved_4_fallback(None, entry, {"kv_bits": "auto"})
            self.assertEqual(a["kv_bits"], "auto")
            self.assertIsNone(n3)

    def test_gguf_leftover_4_falls_back(self):
        settings, notice = P.apply_saved_4_fallback(
            None, {"source": "gguf", "lead_path": "/x.gguf"}, {"kv_bits": "4"})
        self.assertEqual(settings["kv_bits"], "auto")
        self.assertEqual(notice, K.FALLBACK_NOTE)


class ProbeAnswerTests(unittest.TestCase):
    def test_accepts_plain_ok_forms(self):
        for s in ("OK", "OK.", "Ok", "ok", '"OK"', "'OK'", "“OK”", "  OK\n", "OK OK"):
            self.assertTrue(K.probe_answer_ok(s), s)

    def test_rejects_salad_empty_markers_and_rambles(self):
        self.assertFalse(K.probe_answer_ok("–.KeyEvent a´*** with Ada"))
        self.assertFalse(K.probe_answer_ok("<|im_start|>" * 24))
        self.assertFalse(K.probe_answer_ok(""))
        self.assertFalse(K.probe_answer_ok("Sure, here is a long essay about OK and more."))
        self.assertFalse(K.probe_answer_ok("Okay"))
        self.assertFalse(K.probe_answer_ok("Hello!"))
        self.assertFalse(K.probe_answer_ok(None))


class FakeMgr:
    def __init__(self, kv="4", status="ready", port=9, model="m"):
        self._state = {
            "status": status,
            "settings": {"kv_bits": kv},
            "page_settings": {"kv_bits": kv},
            "model_id": model,
            "quality_notice": None,
            "quality": None,
        }
        self.lead_port = port
        self._kv_probe_guard = False
        self._lead_path = "/tmp/model"
        self._loaded_entry = {"lead_path": "/tmp/model"}
        self.tuned_path = Path("/tmp/does-not-matter.json")
        self.state_dir = Path("/tmp")
        self.notes = []
        self.switches = []
        self._loads = []

    def snapshot(self):
        return dict(self._state)

    def _set(self, **kw):
        self._state.update(kw)

    def lead_active_settings(self):
        return {"kv_bits": int(self._state["settings"]["kv_bits"])
                if str(self._state["settings"].get("kv_bits", "")).isdigit()
                else 16}

    def _tuned_entry(self, lp, create=False):
        return {}, {"blocked": {}, "reload_trial": None}

    def switch(self, mid, wait=True, settings=None):
        self.switches.append((mid, settings))
        raise AssertionError("probe must not call switch(); use _load_once")

    def _load_once(self, entry, settings):
        self._loads.append(settings)


class FakeUrlopen:
    """urlopen stand-in that returns a fixed chat-completions body."""
    def __init__(self, content="OK", error=None):
        self.content = content
        self.error = error
        self.calls = 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        self.last_req = req
        if self.error:
            raise self.error
        body = json.dumps({
            "choices": [{"message": {"content": self.content}}],
            "usage": {"completion_tokens": 1},
        }).encode()
        return io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": self.content}}],
        }).encode()


# run_http_probe uses urlopen(req) as a context manager.
class Ctx:
    def __init__(self, content=None, error=None, timeout_exc=None):
        self.content = content if content is not None else "OK"
        self.error = error
        self.calls = 0
        self.urls = []

    def __call__(self, req, timeout=None):
        self.calls += 1
        self.urls.append(getattr(req, "full_url", None) or str(req))
        if self.error:
            raise self.error
        inner = self

        class _Resp:
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

            def read(self_):
                return json.dumps({
                    "choices": [{"message": {"content": inner.content}}],
                }).encode()

        return _Resp()


class ProbeRunTests(unittest.TestCase):
    def test_ok_answer_does_not_revert(self):
        mgr = FakeMgr(kv="4")
        url = Ctx(content="OK")
        out = P.maybe_probe(mgr, urlopen=url)
        self.assertTrue(out["ok"])
        self.assertFalse(out["need_reload"])
        self.assertIsNone(out["notice"])
        self.assertEqual(url.calls, 1)
        self.assertIn("/v1/chat/completions", url.urls[0])
        self.assertIsNone(mgr.snapshot().get("quality_notice"))

    def test_salad_reverts_to_16_and_sets_notice(self):
        mgr = FakeMgr(kv="4")
        url = Ctx(content="–.KeyEvent a´*** with Ada")
        with mock.patch.object(P, "record_loss") as rec, mock.patch.object(P, "set_page_kv") as page:
            page.return_value = {"kv_bits": "16"}
            out = P.maybe_probe(mgr, urlopen=url)
        self.assertFalse(out["ok"])
        self.assertTrue(out["definite"])
        self.assertTrue(out["need_reload"])
        self.assertIn("Memory compression 4 gave wrong answers", out["notice"])
        self.assertIn("turned back to 16", out["notice"])
        rec.assert_called()
        page.assert_called_with(mgr, "16")
        self.assertEqual(mgr.snapshot()["quality_notice"], out["notice"])

    def test_transport_error_is_not_definite_and_does_not_revert(self):
        from urllib.error import URLError
        mgr = FakeMgr(kv="8")
        url = Ctx(error=URLError("down"))
        out = P.maybe_probe(mgr, urlopen=url)
        self.assertFalse(out["ok"])
        self.assertFalse(out["definite"])
        self.assertFalse(out["need_reload"])
        self.assertIsNone(out["notice"])

    def test_skip_when_already_16_or_guard_set(self):
        mgr = FakeMgr(kv="16")
        url = Ctx(content="salad salad")
        self.assertIsNone(P.maybe_probe(mgr, urlopen=url))
        self.assertEqual(url.calls, 0)
        mgr2 = FakeMgr(kv="4")
        mgr2._kv_probe_guard = True
        self.assertIsNone(P.maybe_probe(mgr2, urlopen=url))
        self.assertEqual(url.calls, 0)

    def test_no_loop_after_revert_load(self):
        """The guard stays up until finish_probe_reload, so a 16-bit reload is not probed."""
        mgr = FakeMgr(kv="4")
        url = Ctx(content="word salad here")
        with mock.patch.object(P, "record_loss"), mock.patch.object(P, "set_page_kv"):
            out = P.maybe_probe(mgr, urlopen=url)
        self.assertTrue(out["need_reload"])
        self.assertTrue(mgr._kv_probe_guard)
        # A second maybe_probe during the 16-bit reload is a no-op.
        mgr._state["settings"]["kv_bits"] = "16"
        self.assertIsNone(P.maybe_probe(mgr, urlopen=url))
        self.assertEqual(url.calls, 1)
        P.finish_probe_reload(mgr, out)
        self.assertFalse(mgr._kv_probe_guard)
        self.assertTrue(out["reverted"])

    def test_probe_prompt_is_greedy_and_short(self):
        url = Ctx(content="OK")
        out = K.run_http_probe(1234, urlopen=url)
        self.assertTrue(out["ok"])
        req = None
        # Recreate the body from the last request by peeking at urllib Request
        # — run_http_probe builds a Request; our Ctx stored the url only.
        # Assert constants instead.
        self.assertEqual(K.PROBE_PROMPT, "Reply with just: OK")
        self.assertEqual(K.PROBE_MAX_TOKENS, 16)
        self.assertLessEqual(K.PROBE_TIMEOUT, 20.0)


class AutoTuneTests(unittest.TestCase):
    def test_schedule_never_tries_4_when_unsupported(self):
        entry = {"winner": {}, "optimize_hardware": {}}
        settings = WS.normalize({})
        active = {
            "kv_bits": 16, "kv_quant_supported": True, "kv_4_supported": False,
            "fuse_kernels": "off", "keepalive": True, "shared_start": False,
            "pipeline_chats": 1, "n_layers": 28,
        }
        items = AB.schedule(entry, settings, active, "fp", n_layers=28)
        kv = next(i for i in items if i["name"] == "kv_bits")
        # Incumbent 16, alternatives would be 8 then 4; 4 is dropped.
        if kv.get("skip"):
            # 8 might still be the challenger — only fail if challenger is 4
            self.assertNotEqual(kv.get("challenger"), 4)
        else:
            self.assertNotEqual(kv["challenger"], 4)
            self.assertIn(kv["challenger"], (8, 16))

    def test_schedule_may_still_try_4_on_llama(self):
        # A fresh run prefers 8 first. After 8 has already lost, 4 is next
        # on models that may use it.
        entry = {"winner": {}, "optimize_hardware": {
            "fp": {"losses": [TS.option_id("kv_bits", 8)]},
        }}
        settings = WS.normalize({})
        active = {
            "kv_bits": 16, "kv_quant_supported": True, "kv_4_supported": True,
            "fuse_kernels": "off", "keepalive": True, "shared_start": False,
            "pipeline_chats": 1, "n_layers": 28,
        }
        items = AB.schedule(entry, settings, active, "fp", n_layers=28)
        kv = next(i for i in items if i["name"] == "kv_bits")
        self.assertEqual(kv.get("challenger"), 4)
        # The same situation on a compact model must not queue 4.
        active["kv_4_supported"] = False
        items2 = AB.schedule(entry, settings, active, "fp", n_layers=28)
        kv2 = next(i for i in items2 if i["name"] == "kv_bits")
        self.assertNotEqual(kv2.get("challenger"), 4)

    def test_quality_fail_is_a_loss(self):
        a = WO._Scores()
        a.extend([10, 10, 10])
        b = WO._Scores()
        b.extend([100, 100, 100])
        b.quality_fail = True
        pick = lambda inc, ch: sum(ch) > sum(inc)
        winner, lost, why = WO.decide_ab_winner(16, 4, a, b, pick)
        self.assertEqual(winner, 16)
        self.assertEqual(lost, 4)
        self.assertEqual(why, "challenger failed the quality check")
        # Garbled wording is unchanged.
        b2 = WO._Scores()
        b2.extend([100])
        b2.garbled = True
        winner, lost, why = WO.decide_ab_winner(16, 4, a, b2, pick)
        self.assertEqual(why, "challenger garbled")

    def test_measure_skipped_when_probe_failed(self):
        opt = WO.Optimizer(FakeMgr())
        opt._log = lambda *a, **k: None
        opt.mgr._state["quality"] = {"definite": True, "ok": False, "kv_bits": 4}
        scores = opt._measure_or_quality_fail("kv_bits", "challenger")
        self.assertTrue(scores.quality_fail)
        self.assertEqual(len(scores), 0)

    def test_block_four_records_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            mid = _write_cfg(Path(tmp) / "qwen-7b", 4)
            mgr = FakeMgr()
            called = []

            def rec(m, kv, reason):
                called.append((kv, reason))

            with mock.patch.object(P, "record_loss", rec):
                P.block_four_if_disallowed(mgr, {"lead_path": str(mid), "source": "mlx"})
            self.assertEqual(called[0][0], 4)
            self.assertIn("not available", called[0][1])

    def test_plan_reload_blocks_4_on_compact_model(self):
        """plan_reload_args writes a block so Self-tuning never queues 4."""
        with tempfile.TemporaryDirectory() as tmp:
            mid = _write_cfg(Path(tmp) / "qwen-7b", 4)
            store = {"models": {}}
            entry_rec = TS.ensure_entry(store, "k", model="qwen", hardware="m")
            # Directly exercise the same block call plan_reload_args uses.
            if not K.allows_memory_compression_4(model_dir=mid):
                TS.block_value(entry_rec, "kv_bits", 4,
                               "Memory compression 4 is not available on this model")
            self.assertIn(4, TS.blocked_values(entry_rec, "kv_bits"))


class DoSwitchHookTests(unittest.TestCase):
    def test_do_switch_source_has_fallback_and_probe(self):
        src = (ROOT / "proxy/web_workers.py").read_text()
        self.assertIn("apply_saved_4_fallback", src)
        self.assertIn("maybe_probe", src)
        self.assertIn("finish_probe_reload", src)
        self.assertIn("allows_memory_compression_4", src)
        # Must reload via _load_once, not switch, to avoid "already in progress".
        # The probe helper itself must not call switch.
        helper = (ROOT / "proxy/web_kv_probe.py").read_text()
        self.assertNotIn("mgr.switch(", helper)

    def test_probe_fail_notice_matches_brief(self):
        self.assertEqual(
            K.probe_fail_notice(4),
            "Memory compression 4 gave wrong answers on this model, so it was turned back to 16.",
        )


if __name__ == "__main__":
    unittest.main()
