"""Tests for slot_pin_proxy's 2026-10-30 performance changes, against a
fake llama-server on localhost (no real llama.cpp, no network beyond
127.0.0.1, temp dirs only).

    python3 -m unittest discover -s tests -v      # from the repo root
"""
import contextlib
import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))


class FakeLlama:
    """Minimal llama-server: /slots, /slots/N?action=save|restore, and
    completions (streamed chunked SSE, or JSON with Content-Length)."""

    def __init__(self, n_slots=4):
        self.lock = threading.Lock()
        self.calls = []          # (method, path)
        self.tokens = {i: None for i in range(n_slots)}  # n_prompt_tokens per slot
        self.grow = 100          # tokens added per completion
        self.stream_gap = 0.0    # pause between SSE events
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, obj, status=200):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                with fake.lock:
                    fake.calls.append(("GET", self.path))
                if self.path == "/slots":
                    out = []
                    for i, t in fake.tokens.items():
                        d = {"id": i, "n_ctx": 65536, "is_processing": False}
                        if t is not None:
                            d["n_prompt_tokens"] = t
                        out.append(d)
                    return self._json(out)
                self._json({"status": "ok"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                with fake.lock:
                    fake.calls.append(("POST", self.path))
                if self.path.startswith("/slots/"):
                    slot = int(self.path.split("/")[2].split("?")[0])
                    if "action=save" in self.path:
                        return self._json({"id_slot": slot, "n_saved": fake.tokens[slot] or 0})
                    if "action=restore" in self.path:
                        with fake.lock:
                            fake.tokens[slot] = None  # restore doesn't set task_prev
                        return self._json({"id_slot": slot, "n_restored": 500})
                slot = body.get("id_slot", -1)
                with fake.lock:
                    if slot in fake.tokens:
                        fake.tokens[slot] = (fake.tokens[slot] or 0) + fake.grow
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for i in range(3):
                        ev = f"data: {{\"i\": {i}}}\n\n".encode()
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(ev), ev))
                        self.wfile.flush()
                        time.sleep(fake.stream_gap)
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                    return
                self._json({"id_slot": slot, "choices": [{"text": "ok"}]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def count(self, method, prefix, contains=""):
        with self.lock:
            return sum(1 for m, p in self.calls if m == method and p.startswith(prefix) and contains in p)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _clean_env(tmp: Path) -> dict:
    env = {k: "" for k in ("CARAVAN_N_SLOTS", "CARAVAN_SLOT_SAVE_EVERY",
                           "CARAVAN_SLOT_IDLE_SAVE_SECONDS", "CARAVAN_PROMPT_FINGERPRINT_CHARS",
                           "CARAVAN_MLX_SAVE_MIN_TURNS")}
    env.update(CARAVAN_CONFIG=str(tmp / "config.json"),
               CARAVAN_PROXY_STATE_FILE=str(tmp / "session_slots.json"),
               CARAVAN_SLOT_SAVE_DIR=str(tmp / "slots"))
    return env


def _fresh_proxy(tmp: Path):
    sys.modules.pop("slot_pin_proxy", None)
    with contextlib.redirect_stderr(io.StringIO()):
        import slot_pin_proxy
    return slot_pin_proxy


class ProxyTestBase(unittest.TestCase):
    n_slots = 4

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        (self.tmp / "slots").mkdir()
        self.env = mock.patch.dict(os.environ, _clean_env(self.tmp))
        self.env.start()
        self.spp = _fresh_proxy(self.tmp)
        self.fake = FakeLlama(self.n_slots)
        self.spp.UPSTREAM_PORT = self.fake.port
        self.stderr = io.StringIO()
        self._err = contextlib.redirect_stderr(self.stderr)
        self._err.__enter__()
        self.configure()
        self.proxy = ThreadingHTTPServer(("127.0.0.1", 0), self.spp.ProxyHandler)
        self.proxy_port = self.proxy.server_address[1]
        threading.Thread(target=self.proxy.serve_forever, daemon=True).start()

    def configure(self, **kw):
        base = dict(n_slots=self.n_slots, save_every_n_turns=1, idle_save_seconds=0.0,
                    prompt_fingerprint_chars=64)
        base.update(kw)
        self.spp.configure(self.spp.ProxySettings(**base))

    def tearDown(self):
        self.proxy.shutdown()
        self.proxy.server_close()
        self.fake.close()
        self._err.__exit__(None, None, None)
        self.env.stop()
        sys.modules.pop("slot_pin_proxy", None)
        self.tmpdir.cleanup()

    def chat(self, first_msg, stream=False, conn=None):
        body = {"messages": [{"role": "system", "content": "sys"},
                             {"role": "user", "content": first_msg}], "stream": stream}
        c = conn or http.client.HTTPConnection("127.0.0.1", self.proxy_port, timeout=10)
        c.request("POST", "/v1/chat/completions", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        self.settle()
        return r, data

    def settle(self):
        """The inline save runs after the response is written, still under
        the FIFO gate -- wait for the gate so counts are deterministic."""
        with self.spp._exclusive_slot_io():
            pass

    def fp(self, msg):
        return self.spp.session_fingerprint({"messages": [{"role": "user", "content": msg}]})


class StreamingTest(ProxyTestBase):
    def test_sse_streams_promptly_and_is_chunk_framed(self):
        self.fake.stream_gap = 0.6
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "stream": True})
        s = socket.create_connection(("127.0.0.1", self.proxy_port), timeout=10)
        s.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                  b"Content-Length: %d\r\n\r\n%s" % (len(body), body.encode()))
        t0 = time.monotonic()
        buf = b""
        while b"data: {\"i\": 0}" not in buf:
            buf += s.recv(4096)
        first_event_after = time.monotonic() - t0
        s.close()
        # With read(4096) the proxy held everything until 4 KB or EOF (~1.8s).
        self.assertLess(first_event_after, 0.5)
        head = buf.split(b"\r\n\r\n", 1)[0].lower()
        self.assertIn(b"transfer-encoding: chunked", head)

    def test_keepalive_reuse_after_streamed_and_sized_responses(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.proxy_port, timeout=10)
        r1, d1 = self.chat("conv-a", stream=True, conn=conn)
        self.assertEqual(r1.status, 200)
        self.assertEqual(d1.count(b"data:"), 3)
        r2, d2 = self.chat("conv-a", stream=False, conn=conn)  # same socket
        self.assertEqual(r2.status, 200)
        self.assertEqual(r2.getheader("Content-Length"), str(len(d2)))
        self.assertIn(b"choices", d2)

    def test_http10_client_gets_connection_close(self):
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "stream": True})
        s = socket.create_connection(("127.0.0.1", self.proxy_port), timeout=10)
        s.sendall(b"POST /v1/chat/completions HTTP/1.0\r\nContent-Type: application/json\r\n"
                  b"Content-Length: %d\r\n\r\n%s" % (len(body), body.encode()))
        buf = b""
        while True:
            d = s.recv(4096)
            if not d:
                break
            buf += d
        s.close()
        head, payload = buf.split(b"\r\n\r\n", 1)
        self.assertIn(b"connection: close", head.lower())
        self.assertNotIn(b"transfer-encoding", head.lower())
        self.assertEqual(payload.count(b"data:"), 3)


class SaveRestoreTest(ProxyTestBase):
    def test_save_every_turn_by_default_and_skip_when_unchanged(self):
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 1)
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 2)
        # Upstream token count doesn't grow (e.g. an identical retry) -> no save.
        self.fake.grow = 0
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 2)
        self.assertIn("skip save", self.stderr.getvalue())

    def test_save_every_n_turns(self):
        self.configure(save_every_n_turns=3)
        for _ in range(5):
            self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 1)
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 2)

    def test_no_slots_query_per_request_when_nothing_due(self):
        # Perf review #12: no per-request GET /slots any more.
        self.configure(save_every_n_turns=100)
        for _ in range(3):
            self.chat("conv-a")
        self.assertEqual(self.fake.count("GET", "/slots"), 0)
        self.assertEqual(self.fake.count("POST", "/slots/"), 0)

    def test_restore_when_cold_skip_when_warm(self):
        fp = self.fp("conv-a")
        (self.tmp / "slots" / f"{fp}.bin").write_bytes(b"kv")
        # New to this proxy -> LRU slot, restore from disk.
        self.configure(save_every_n_turns=100)
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=restore"), 1)
        # Same session again -> warm, no restore.
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=restore"), 1)

    def test_proxy_restart_with_warm_llama_server_skips_restore(self):
        fp = self.fp("conv-a")
        (self.tmp / "slots" / f"{fp}.bin").write_bytes(b"kv")
        self.configure(save_every_n_turns=100)
        self.spp.session_slots.mark_used(2, fp)   # persisted occupancy from a previous run
        self.spp._warm_this_run.clear()            # ...but a fresh proxy process
        self.fake.tokens[2] = 4000                 # llama-server still holds it
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=restore"), 0)
        # llama-server restarted (slot empty) -> restore.
        self.spp._warm_this_run.clear()
        self.fake.tokens[2] = None
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=restore"), 1)

    def test_ephemeral_short_prompt_never_saved(self):
        c = http.client.HTTPConnection("127.0.0.1", self.proxy_port, timeout=10)
        for _ in range(3):
            c.request("POST", "/completion", body=json.dumps({"prompt": "short one-shot"}),
                      headers={"Content-Type": "application/json"})
            c.getresponse().read()
            self.settle()
        self.assertEqual(self.fake.count("POST", "/slots/"), 0)
        self.assertNotIn("content_preview", self.stderr.getvalue())


class EvictionAndIdleTest(ProxyTestBase):
    n_slots = 1

    def test_dirty_session_saved_before_eviction(self):
        self.configure(save_every_n_turns=10)
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 0)
        self.chat("conv-b")  # needs the only slot -> conv-a flushed first
        self.assertEqual(self.fake.count("POST", "/slots/0", "action=save"), 1)
        self.assertEqual(self.spp.session_slots.occupant(0), self.fp("conv-b"))

    def test_idle_saver(self):
        self.configure(idle_save_seconds=0.3)
        self.spp.start_idle_saver(0.3, poll_seconds=0.05)
        self.chat("conv-a")
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 0)  # not inline
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and self.fake.count("POST", "/slots/", "action=save") == 0:
            time.sleep(0.05)
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 1)
        time.sleep(0.4)  # saved once, not again while unchanged
        self.assertEqual(self.fake.count("POST", "/slots/", "action=save"), 1)


class AssignerAndFingerprintTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.env = mock.patch.dict(os.environ, _clean_env(self.tmp))
        self.env.start()
        self.spp = _fresh_proxy(self.tmp)

    def tearDown(self):
        self.env.stop()
        sys.modules.pop("slot_pin_proxy", None)
        self.tmpdir.cleanup()

    def test_lru_assignment_and_persistence(self):
        now = [100.0]
        state = self.tmp / "s.json"
        a = self.spp.SessionSlotAssigner(2, state, clock=lambda: now[0])

        def use(fp):
            slot, there, evicted = a.slot_for(fp)
            a.mark_used(slot, fp)
            now[0] += 1
            return slot, there, evicted

        self.assertEqual(use("A"), (0, False, None))
        self.assertEqual(use("B"), (1, False, None))
        self.assertEqual(use("A"), (0, True, None))
        self.assertEqual(use("C"), (1, False, "B"))   # B is least recently used
        self.assertEqual(use("B"), (0, False, "A"))
        with contextlib.redirect_stderr(io.StringIO()):
            b = self.spp.SessionSlotAssigner(2, state)
        self.assertEqual((b.occupant(0), b.occupant(1)), ("B", "C"))
        self.assertEqual(json.loads(state.read_text())["assignments"], {"B": 0, "C": 1})
        self.assertEqual(b.forget(["C", "zzz"]), ["C"])
        self.assertEqual(b.lru_slot(), 1)  # freed slot is preferred

    def test_standalone_prune_handles_v2_state(self):
        sys.path.insert(0, str(REPO / "proxy"))
        import slot_cleanup
        state = self.tmp / "s.json"
        a = self.spp.SessionSlotAssigner(2, state)
        a.mark_used(0, "A")
        a.mark_used(1, "B")
        self.assertEqual(slot_cleanup.prune_state_file(state, ["A"]), ["A"])
        with contextlib.redirect_stderr(io.StringIO()):
            b = self.spp.SessionSlotAssigner(2, state)
        self.assertEqual((b.occupant(0), b.occupant(1)), (None, "B"))

    def test_legacy_state_file(self):
        state = self.tmp / "s.json"
        state.write_text(json.dumps({"assignments": {"x": 0, "y": 1, "z": 0}, "next_slot": 3}))
        with contextlib.redirect_stderr(io.StringIO()):
            a = self.spp.SessionSlotAssigner(4, state)
        self.assertEqual([a.occupant(i) for i in range(4)], ["z", "y", None, None])
        self.assertEqual(a.lru_slot(), 2)

    def test_fingerprints(self):
        fpf = self.spp.session_fingerprint
        self.spp.SETTINGS = self.spp.SETTINGS._replace(prompt_fingerprint_chars=64)
        boot = {"role": "user", "content": "[Sun 2026-09-06 10:34 CDT] (session bootstrap)"}
        m1 = {"messages": [{"role": "system", "content": "s"}, boot, {"role": "user", "content": "q1"}]}
        m2 = {"messages": m1["messages"] + [{"role": "assistant", "content": "a"},
                                            {"role": "user", "content": "q2"}]}
        self.assertEqual(fpf(m1), fpf(m2))
        self.assertIsNone(fpf({"messages": [{"role": "system", "content": "s"}]}))
        long = "x" * 100
        self.assertIsNone(fpf({"prompt": "short"}))
        self.assertIsNotNone(fpf({"prompt": long}))
        self.assertEqual(fpf({"prompt": long}), fpf({"prompt": long + " more turns"}))
        self.assertNotEqual(fpf({"prompt": long}), fpf({"prompt": "y" * 100}))
        toks = list(range(40))
        self.assertEqual(fpf({"prompt": toks}), fpf({"prompt": toks + [1, 2, 3]}))
        self.assertIsNone(fpf({"prompt": ["a" * 100, "b" * 100]}))  # batched -> ephemeral
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            fpf(m1)
        self.assertEqual(err.getvalue(), "")  # TEMP debug logging removed

    def test_settings_precedence(self):
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps({"llama_server": {"n_slots": 6},
                                   "proxy": {"slot_save_every": 4, "slot_idle_save_seconds": 60}}))
        s = self.spp.resolve_proxy_settings()
        self.assertEqual((s.n_slots, s.save_every_n_turns, s.idle_save_seconds,
                          s.prompt_fingerprint_chars), (6, 4, 60.0, 2048))
        with mock.patch.dict(os.environ, {"CARAVAN_N_SLOTS": "2", "CARAVAN_SLOT_SAVE_EVERY": "2"}):
            s = self.spp.resolve_proxy_settings()
            self.assertEqual((s.n_slots, s.save_every_n_turns), (2, 2))
            s = self.spp.resolve_proxy_settings({"n_slots": 8})
            self.assertEqual(s.n_slots, 8)
        with self.assertRaises(ValueError):
            self.spp.resolve_proxy_settings({"save_every_n_turns": 0})


if __name__ == "__main__":
    unittest.main()
