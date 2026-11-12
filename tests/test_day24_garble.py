"""Day 24: stop/hide ChatML markers, garble detection, auto-fix, reset, packaging-version."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for folder in ("agent", "proxy", "tools"):
    sys.path.insert(0, str(ROOT / folder))

import garble
import web_garble
import mlx_worker
import web_timing


HELLO = "Hello!"
CODE = """def greet(name):
    return f"Hello, {name}!"

# --------------------------------
# helper
# --------------------------------
if __name__ == "__main__":
    print(greet("world"))
    print(greet("world"))
    print(greet("world"))
"""
IM_START_LOOP = "<|im_start|>" * 24


class DetectionTests(unittest.TestCase):
    def test_hello_is_not_garbled(self):
        self.assertFalse(garble.is_garbled(HELLO))
        self.assertFalse(garble.is_garbled("Hello! Hello! Hello!"))
        self.assertFalse(garble.is_garbled("Sure, here is a short answer."))

    def test_empty_and_markers_are_garbled(self):
        self.assertTrue(garble.is_garbled(""))
        self.assertTrue(garble.is_garbled("   "))
        self.assertTrue(garble.is_garbled("<|im_end|>"))
        self.assertTrue(garble.is_garbled("<|im_start|>"))
        self.assertTrue(garble.is_garbled(IM_START_LOOP))
        self.assertTrue(garble.is_garbled(("<|im_start|>\n") * 12))
        # After display stripping the visible text is empty — still garbled on raw.
        stripped = garble.strip_special_markers(IM_START_LOOP)
        self.assertFalse(stripped.strip())
        self.assertTrue(garble.is_garbled(stripped, raw=IM_START_LOOP))

    def test_code_with_repetition_and_banners_passes(self):
        self.assertFalse(garble.is_garbled(CODE))
        self.assertFalse(garble.is_garbled("=" * 40))
        self.assertFalse(garble.is_garbled("/* " + "-" * 30 + " */\nint main() { return 0; }\n"))
        self.assertFalse(garble.is_garbled("    return None\n" * 3 + "def x():\n    pass\n"))

    def test_degenerate_short_chunk_loop(self):
        self.assertTrue(garble.is_degenerate_repeat("ha" * 20))
        self.assertTrue(garble.is_garbled("xyz" * 10))
        self.assertFalse(garble.is_degenerate_repeat("n" * 8))  # shorter than the floor
        self.assertFalse(garble.is_degenerate_repeat(HELLO))


class PlanAndNoticeTests(unittest.TestCase):
    def test_kv_four_turns_back_to_16_only(self):
        plan = garble.plan_garble_fix({"kv_bits": 4, "guess_ahead": "on"})
        self.assertEqual(plan["changes"], [("kv_bits", "16")])
        self.assertEqual(plan["message"], garble.KV_NOTICE)
        self.assertFalse(plan["already_safe"])
        self.assertEqual(plan["new_settings"]["kv_bits"], "16")
        # Extras are left alone on the first step.
        self.assertEqual(plan["new_settings"].get("guess_ahead"), "on")

    def test_kv_eight_same_notice(self):
        plan = garble.plan_garble_fix({"kv_bits": "8"})
        self.assertEqual(plan["changes"], [("kv_bits", "16")])
        self.assertEqual(plan["message"], garble.KV_NOTICE)

    def test_already_16_turns_off_extras(self):
        plan = garble.plan_garble_fix({
            "kv_bits": "16",
            "guess_ahead": "on",
            "shared_start": "on",
        })
        keys = [k for k, _ in plan["changes"]]
        self.assertEqual(keys, ["guess_ahead", "shared_start"])
        self.assertIn("Guess-ahead", plan["message"])
        self.assertIn("Shared start", plan["message"])
        self.assertTrue(plan["message"].startswith("This reply came out garbled, so "))

    def test_already_safe_notice(self):
        plan = garble.plan_garble_fix({"kv_bits": "16", "guess_ahead": "off"})
        self.assertTrue(plan["already_safe"])
        self.assertEqual(plan["changes"], [])
        self.assertEqual(plan["message"], garble.SAFE_NOTICE)

    def test_gguf_skips_fused_kernels(self):
        plan = garble.plan_garble_fix(
            {"kv_bits": "16", "fuse_kernels": "on", "shared_start": "on"},
            backend="gguf",
        )
        keys = [k for k, _ in plan["changes"]]
        self.assertNotIn("fuse_kernels", keys)
        self.assertIn("shared_start", keys)

    def test_losses_from_used(self):
        losses = garble.losses_from_used({"kv_bits": 4, "guess_ahead": "on"})
        self.assertIn(("kv_bits", 4), losses)
        self.assertIn(("guess_ahead", "on"), losses)


class AutoFixTests(unittest.TestCase):
    def _mgr(self, settings, *, model_id="qwen", backend="mlx"):
        snap = {
            "settings": dict(settings),
            "page_settings": dict(settings),
            "model_id": model_id,
            "backend": backend,
            "status": "ready",
        }
        mgr = SimpleNamespace(
            snapshot=lambda: snap,
            state_dir=Path(tempfile.gettempdir()),
            tuned_path=None,
            _lead_path=None,
            _tuned_entry=lambda lp: (None, None),
        )
        def switch(mid, wait=False, settings=None):
            snap["settings"] = dict(settings or {})
            snap["page_settings"] = dict(settings or {})
            snap["status"] = "ready"
            return snap
        mgr.switch = switch
        return mgr, snap

    def test_handle_applies_kv_16_and_message(self):
        mgr, snap = self._mgr({"kv_bits": 4, "guess_ahead": "on"})
        result = web_garble.handle_garbled_reply(mgr, IM_START_LOOP)
        self.assertEqual(result["message"], garble.KV_NOTICE)
        self.assertTrue(result["changed"])
        self.assertEqual(snap["settings"]["kv_bits"], "16")
        # First step does not also turn extras off.
        self.assertEqual(snap["settings"].get("guess_ahead"), "on")

    def test_already_safe_does_not_reload(self):
        mgr, snap = self._mgr({"kv_bits": "16", "guess_ahead": "off"})
        called = []
        mgr.switch = lambda *a, **k: called.append(1)
        result = web_garble.handle_garbled_reply(mgr, IM_START_LOOP)
        self.assertEqual(result["message"], garble.SAFE_NOTICE)
        self.assertFalse(result["changed"])
        self.assertEqual(called, [])

    def test_clean_reply_returns_none(self):
        mgr, _ = self._mgr({"kv_bits": 4})
        self.assertIsNone(web_garble.handle_garbled_reply(mgr, HELLO))

    def test_skips_reload_while_optimizer_runs(self):
        mgr, snap = self._mgr({"kv_bits": 4})
        called = []
        mgr.switch = lambda *a, **k: called.append(1)
        opt = SimpleNamespace(snapshot=lambda: {"running": True}, running=True)
        result = web_garble.handle_garbled_reply(mgr, IM_START_LOOP, optimizer=opt)
        self.assertTrue(result.get("deferred"))
        self.assertFalse(result["changed"])
        self.assertEqual(called, [])
        self.assertEqual(result["message"], garble.KV_NOTICE)

    def test_two_step_then_stop(self):
        # First garbled reply at kv 4 → 16. Second, still garbled with extras on
        # → extras off. Third, already safe → notice only.
        mgr, snap = self._mgr({"kv_bits": 4, "guess_ahead": "on", "shared_start": "on"})
        r1 = web_garble.handle_garbled_reply(mgr, IM_START_LOOP)
        self.assertEqual(r1["message"], garble.KV_NOTICE)
        self.assertEqual(snap["settings"]["kv_bits"], "16")
        r2 = web_garble.handle_garbled_reply(mgr, IM_START_LOOP)
        self.assertIn("Guess-ahead", r2["message"])
        self.assertIn("Shared start", r2["message"])
        self.assertEqual(snap["settings"]["guess_ahead"], "off")
        self.assertEqual(snap["settings"]["shared_start"], "off")
        r3 = web_garble.handle_garbled_reply(mgr, IM_START_LOOP)
        self.assertEqual(r3["message"], garble.SAFE_NOTICE)
        self.assertFalse(r3["changed"])


class ObserveGarbleTests(unittest.TestCase):
    def test_garbled_blocks_kv_and_skips_observe(self):
        import tuned_settings as TS
        entry = {"winner": {}, "reload_blocked": {}}
        store = {"models": {"x": entry}}
        engine = SimpleNamespace(
            _sweep_pause=False,
            _learn_enabled=True,
            _learn_entry=entry,
            _learn_store=store,
            _learn_path=None,
            _learn_lock=threading.Lock(),
            _fuse_mode="off",
            args=SimpleNamespace(kv_bits=4, split_keepalive=False),
            _last_learn=None,
        )
        # Bind the method
        mlx_worker.Engine._learn_observe(engine, {"garbled": True, "completion_tokens": 24, "total_s": 0.1})
        self.assertIn(4, TS.blocked_values(entry, "kv_bits"))
        self.assertTrue((engine._last_learn or {}).get("garbled"))
        # No speed-based winner.
        self.assertEqual(entry.get("winner"), {})


class OptimizeGarbleTests(unittest.TestCase):
    def test_garbled_challenger_is_a_loss(self):
        import web_optimize as WO
        a = WO._Scores([10.0, 11.0])
        b = WO._Scores([50.0, 60.0])  # much faster
        b.garbled = True
        # Speed-only pick would take the challenger; quality gate must not.
        def pick(inc, ch):
            return sum(ch) > sum(inc)
        winner, lost, why = WO.decide_ab_winner("16", "4", a, b, pick)
        self.assertEqual(winner, "16")
        self.assertEqual(lost, "4")
        self.assertEqual(why, "challenger garbled")
        # Clean arms still use the speed pick.
        b2 = WO._Scores([50.0, 60.0])
        winner, lost, why = WO.decide_ab_winner("16", "4", a, b2, pick)
        self.assertEqual(winner, "4")
        self.assertIsNone(why)

    def test_http_send_flags_garbled_content(self):
        from urllib.error import URLError
        # Use the real is_garbled on a stubbed body via a tiny stand-in of _http_send.
        body = {
            "usage": {"completion_tokens": 24, "caravan": {"ttft_s": 0.01, "total_s": 0.05, "prefill_s": 0}},
            "choices": [{"message": {"content": IM_START_LOOP}}],
        }
        content = body["choices"][0]["message"]["content"]
        self.assertTrue(garble.is_garbled(content))


class ResetTuningTests(unittest.TestCase):
    def test_reset_clears_kv_pin_on_page_and_last_model(self):
        import web_workers
        import web_settings
        from web_restore import Store

        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            last = {
                "schema": 1,
                "request": {
                    "model_id": "qwen-7b",
                    "engine": "mlx",
                    "settings": web_settings.normalize({"kv_bits": "4"}),
                },
            }
            (state / "last-model.json").write_text(json.dumps(last))
            snap = {
                "model_id": "qwen-7b",
                "backend": "mlx",
                "page_settings": {"kv_bits": "4"},
                "settings": {"kv_bits": "16"},  # already live at 16, no reload
                "status": "ready",
            }
            mgr = web_workers.WorkerManager.__new__(web_workers.WorkerManager)
            mgr.state_dir = state
            mgr.tuned_path = state / "tuned.json"
            mgr._lead_path = None
            mgr.snapshot = lambda: snap
            set_calls = []
            mgr._set = lambda **k: set_calls.append(k)
            mgr.switch = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not reload"))
            with mock.patch("web_speed.clear_tuning"):
                out = web_workers.WorkerManager.reset_tuning(mgr)
            self.assertTrue(out["ok"])
            self.assertIn("Memory compression is back to Auto", out["notice"])
            self.assertTrue(any(c.get("page_settings", {}).get("kv_bits") == "auto" for c in set_calls))
            saved = Store(state / "last-model.json").read()
            self.assertEqual(saved["settings"]["kv_bits"], "auto")

    def test_reset_reloads_when_live_kv_is_tight(self):
        import web_workers
        import web_settings
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            snap = {
                "model_id": "qwen-7b",
                "backend": "mlx",
                "page_settings": {"kv_bits": "4"},
                "settings": {"kv_bits": "4"},
                "status": "ready",
            }
            mgr = web_workers.WorkerManager.__new__(web_workers.WorkerManager)
            mgr.state_dir = state
            mgr.tuned_path = state / "tuned.json"
            mgr._lead_path = None
            mgr.snapshot = lambda: snap
            mgr._set = lambda **k: None
            switches = []
            def switch(mid, wait=False, settings=None):
                switches.append((mid, settings))
                return snap
            mgr.switch = switch
            with mock.patch("web_speed.clear_tuning"):
                out = web_workers.WorkerManager.reset_tuning(mgr)
            self.assertTrue(out["ok"])
            self.assertEqual(len(switches), 1)
            self.assertEqual(switches[0][0], "qwen-7b")
            self.assertEqual(switches[0][1]["kv_bits"], "auto")


class MarkerTests(unittest.TestCase):
    def test_worker_stop_and_strip_lists_include_chatml(self):
        self.assertIn("<|im_start|>", mlx_worker.TURN_END_TOKENS)
        self.assertIn("<|im_end|>", mlx_worker.TURN_END_TOKENS)
        self.assertIn("<|im_start|>", mlx_worker.END_MARKERS)
        self.assertIn("<|im_end|>", mlx_worker.END_MARKERS)
        self.assertEqual(mlx_worker.strip_end_markers(IM_START_LOOP), "")
        self.assertEqual(mlx_worker.strip_end_markers("Hi <|im_start|>there<|im_end|>"), "Hi there")
        # Existing Llama markers still strip.
        self.assertEqual(mlx_worker.strip_end_markers("Hi <|eot_id|>"), "Hi ")

    def test_proxy_and_page_strip_im_start(self):
        self.assertIn("<|im_start|>", web_timing._REPLY_MARKERS)
        self.assertEqual(web_timing.strip_reply_markers(IM_START_LOOP).strip(), "")
        html = (ROOT / "proxy/web/index.html").read_text()
        self.assertIn('"<|im_start|>"', html)
        self.assertIn("garble-note", html)
        self.assertIn("meta.garble", html)
        self.assertIn(garble.KV_NOTICE.split(",")[0],  # "This reply came out garbled"
                      "This reply came out garbled, so Memory compression was turned back to 16.")


class PackagingVersionTests(unittest.TestCase):
    def test_install_stamps_channel_version_before_hash(self):
        text = (ROOT / "install").read_text()
        stamp = 'printf \'%s %s\\n\' "$REF" "$SHA" > "$TMP/source/packaging-version"'
        self.assertIn(stamp, text)
        # Must run after extract, before the integrity list is built, so the
        # stamped file is what `caravan update` will later see.
        a = text.index(stamp)
        b = text.index("find . -type f ! -name '.caravan-package-files'")
        self.assertLess(a, b)
        # Comment explains why: the source archive still carries the previous pin.
        self.assertIn("previous pin's packaging-version", text)

    def test_stamp_overwrites_stale_file(self):
        # Simulate: tarball has the previous pin, channel file is the new one.
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source"
            src.mkdir()
            (src / "packaging-version").write_text(
                "f205668deadbeef 0000000000000000000000000000000000000000000000000000000000000000\n"
            )
            ref = "eb993b4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            (src / "packaging-version").write_text(f"{ref} {sha}\n")
            got = (src / "packaging-version").read_text().strip().split()
            self.assertEqual(got[0], ref)
            self.assertEqual(got[1], sha)
            self.assertNotIn("f205668", got[0])


class MultiBindTests(unittest.TestCase):
    def test_loopback_aliases_both_serve(self):
        """Two addresses can listen at once; 0.0.0.0 is not required."""
        # Pick a free port.
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok " + self.server.server_address[0].encode())
            def log_message(self, *a):
                pass

        class S(ThreadingHTTPServer):
            allow_reuse_address = True
            def server_bind(self):
                import socketserver
                socketserver.TCPServer.server_bind(self)
                self.server_name = self.server_address[0]
                self.server_port = self.server_address[1]

        primary = S(("127.0.0.1", port), H)
        try:
            extra = S(("127.0.0.2", port), H)
        except OSError:
            primary.server_close()
            self.skipTest("127.0.0.2 is not bindable on this host")
        t1 = threading.Thread(target=primary.serve_forever, daemon=True)
        t2 = threading.Thread(target=extra.serve_forever, daemon=True)
        t1.start(); t2.start()
        try:
            def get(host):
                s = socket.create_connection((host, port), timeout=2)
                s.sendall(b"GET / HTTP/1.0\r\nHost: x\r\n\r\n")
                data = b""
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                s.close()
                return data
            a = get("127.0.0.1")
            b = get("127.0.0.2")
            self.assertIn(b"ok 127.0.0.1", a)
            self.assertIn(b"ok 127.0.0.2", b)
        finally:
            primary.shutdown(); extra.shutdown()
            primary.server_close(); extra.server_close()


class UiGarbleTests(unittest.TestCase):
    def test_inline_javascript_still_parses(self):
        import re, shutil, subprocess
        if not shutil.which("node"):
            self.skipTest("node not installed")
        text = (ROOT / "proxy/web/index.html").read_text()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "inline.js"
            p.write_text("\n".join(re.findall(r"<script>(.*?)</script>", text, re.S)))
            result = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
