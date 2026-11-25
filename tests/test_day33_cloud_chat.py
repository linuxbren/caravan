"""Day 33 (CAR-8): chat with Ollama Cloud models through Caravan.

Everything here runs against a local mock of Ollama's documented cloud API
(POST /api/chat with a Bearer key, NDJSON streaming, GET /api/tags). No test
touches the network or a real key.
"""
from __future__ import annotations

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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "tools"))
import cloud_chat as CC  # noqa: E402
import cloud_keys as CK  # noqa: E402
import caravan_lan as LAN  # noqa: E402
import web_picker  # noqa: E402
import web_server  # noqa: E402
from web_workers import WorkerManager  # noqa: E402
from i18n_check import english_source  # noqa: E402

KEY = "olk-test-SECRETSECRET-1234wxyz"
ENV_NAMES = [n for p in CK.PROVIDERS.values() for n in p["env"]]
HTML = english_source(ROOT / "proxy/web/index.html")


class MockOllama:
    """A tiny stand-in for https://ollama.com (only what Caravan uses)."""

    def __init__(self):
        self.mode = "ok"
        self.seen = []  # (path, headers, body)
        self.release = threading.Event()
        self.closed = threading.Event()
        mock_ = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _send_json(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                mock_.seen.append((self.path, dict(self.headers), None))
                if self.path == "/api/tags":
                    if mock_.mode == "tags_down":
                        return self._send_json(500, {"error": "down"})
                    return self._send_json(200, {"models": [
                        {"name": "zeta-coder", "model": "zeta-coder", "capabilities": ["completion", "tools"]},
                        {"name": "gpt-oss:20b", "model": "gpt-oss:20b", "capabilities": ["completion", "thinking"]},
                        {"name": "gpt-oss:120b", "model": "gpt-oss:120b", "capabilities": ["completion", "thinking", "tools"]},
                        {"name": "bad name with spaces"},
                    ]})
                self._send_json(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                mock_.seen.append((self.path, dict(self.headers), body))
                if self.path != "/api/chat":
                    return self._send_json(404, {"error": "not found"})
                if self.headers.get("Authorization") != "Bearer " + KEY:
                    return self._send_json(401, {"error": "unauthorized"})
                m = mock_.mode
                if m == "401":
                    # A server that echoes the key must not get it to the page.
                    return self._send_json(401, {"error": "bad key " + KEY})
                if m == "404":
                    return self._send_json(404, {"error": f"model '{body.get('model')}' not found"})
                if m == "429":
                    return self._send_json(429, {"error": "too many requests"})
                if m == "500":
                    return self._send_json(500, {"error": "internal"})
                if m == "nothink" and "think" in body:
                    return self._send_json(400, {"error": f'"{body.get("model")}" does not support thinking'})
                if not body.get("stream", True):
                    return self._send_json(200, {
                        "model": body["model"], "message": {"role": "assistant", "content": "Hello there."},
                        "done": True, "done_reason": "stop", "prompt_eval_count": 11, "eval_count": 3,
                        "eval_duration": 30_000_000, "prompt_eval_duration": 5_000_000})
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()

                def line(obj):
                    self.wfile.write((json.dumps(obj) + "\n").encode())
                    self.wfile.flush()
                try:
                    if m == "slow":
                        line({"message": {"role": "assistant", "content": "Once"}, "done": False})
                        for _ in range(200):
                            if mock_.release.wait(0.05):
                                break
                            line({"message": {"role": "assistant", "content": ""}, "done": False})
                        line({"message": {"role": "assistant", "content": " more"}, "done": True,
                              "done_reason": "stop", "eval_count": 2})
                        return
                    line({"message": {"role": "assistant", "content": "", "thinking": "Let me think."}, "done": False})
                    line({"message": {"role": "assistant", "content": "Hello"}, "done": False})
                    if m == "midstream_error":
                        line({"error": "an error was encountered while running the model " + KEY})
                        return
                    if m == "cut":
                        return
                    line({"message": {"role": "assistant", "content": " there."}, "done": False})
                    line({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                          "prompt_eval_count": 12, "prompt_eval_duration": 6_000_000,
                          "eval_count": 4, "eval_duration": 40_000_000})
                except (BrokenPipeError, ConnectionResetError):
                    mock_.closed.set()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()

    def chats(self):
        return [b for p, _h, b in self.seen if p == "/api/chat"]


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.ollama = MockOllama()
        self.addCleanup(self.ollama.close)
        env = {k: "" for k in ENV_NAMES}
        env.update({"CARAVAN_CLOUD_KEYS_PATH": "", "CARAVAN_OLLAMA_CLOUD_URL": self.ollama.url,
                    "CARAVAN_JOBS_DIR": str(self.home / "jobs"),
                    "CARAVAN_CONFIG_TOML": str(self.home / "config.toml")})
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        CC.clear_catalog_cache()
        self.addCleanup(CC.clear_catalog_cache)
        mgr = WorkerManager(lead_port=_closed_port(), packer_peer="127.0.0.1:5560",
                            packer_ssh="nobody@127.0.0.1", state_dir=self.home / "state", repo=ROOT)
        app = web_server.App(mgr)
        app.nodes = lambda: {"nodes": []}
        app.configured_nodes = lambda: []
        app.update_inspect = lambda: {}
        app.cloud_keys_home = self.home
        self.app = app
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.out, self.err = io.StringIO(), io.StringIO()
        r1 = contextlib.redirect_stdout(self.out)
        r2 = contextlib.redirect_stderr(self.err)
        r1.__enter__(); r2.__enter__()
        self.addCleanup(r1.__exit__, None, None, None)
        self.addCleanup(r2.__exit__, None, None, None)
        self.addCleanup(self.assert_key_never_logged)

    def assert_key_never_logged(self):
        for text in (self.out.getvalue(), self.err.getvalue()):
            self.assertNotIn(KEY, text)
            self.assertNotIn(KEY[:-4], text)

    def save_key(self):
        CK.save("ollama", KEY, home=self.home)

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        r = Request(self.base + path, data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            with urlopen(r, timeout=10) as resp:
                return resp.status, resp.read().decode(), dict(resp.headers)
        except HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)

    def get(self, path):
        with urlopen(self.base + path, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def use(self, model="gpt-oss:120b"):
        self.save_key()
        code, raw, _ = self.post("/api/cloud/use", {"provider": "ollama", "model": "ollama-cloud/" + model})
        self.assertEqual(code, 200, raw)
        return json.loads(raw)["cloud"]

    def chat(self, **extra):
        body = {"messages": [{"role": "user", "content": "hi"}], "stream": True, "temperature": 0.7,
                "max_tokens": 64, "stream_options": {"include_usage": True}}
        body.update(extra)
        return self.post("/api/chat", body, headers={"X-Caravan-Request": "req12345abcd"})

    @staticmethod
    def frames(raw):
        out = []
        for line in raw.split("\n"):
            if line.startswith("data: ") and line[6:].strip() != "[DONE]":
                out.append(json.loads(line[6:]))
        return out

    def assert_no_key(self, text):
        self.assertNotIn(KEY, text)
        self.assertNotIn(KEY[:-4], text)


class Payload(unittest.TestCase):
    def test_page_body_becomes_ollama_chat_body(self):
        body = {"messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"},
                             {"role": "bogus", "content": "x"}, {"role": "user", "content": None},
                             {"role": "user", "content": [{"type": "text", "text": "part"}]}],
                "temperature": 0.7, "max_tokens": 768, "thinking": True, "stream_options": {"include_usage": True}}
        out = CC.build_payload(body, "gpt-oss:120b", True)
        self.assertEqual(out["model"], "gpt-oss:120b")
        self.assertEqual([m["role"] for m in out["messages"]], ["system", "user", "user"])
        self.assertEqual(out["messages"][-1]["content"], "part")
        self.assertEqual(out["options"], {"temperature": 0.7, "num_predict": 768})
        self.assertIs(out["think"], True)
        self.assertIs(out["stream"], True)
        self.assertNotIn("stream_options", out)

    def test_thinking_effort_and_off(self):
        eff = CC.build_payload({"messages": [], "chat_template_kwargs": {"reasoning_effort": "high"}}, "m", True)
        self.assertEqual(eff["think"], "high")
        off = CC.build_payload({"messages": [], "thinking": False}, "m", False)
        self.assertIs(off["think"], False)
        self.assertNotIn("think", CC.build_payload({"messages": [], "thinking": True}, "m", True, with_think=False))
        self.assertNotIn("think", CC.build_payload({"messages": []}, "m", True))

    def test_direct_names(self):
        self.assertEqual(CC.direct_name("ollama-cloud/gpt-oss:120b-cloud"), "gpt-oss:120b")
        self.assertEqual(CC.direct_name("ollama-cloud/glm-4.6:cloud"), "glm-4.6")
        self.assertEqual(CC.direct_name("ollama-cloud/gemma4:31b"), "gemma4:31b")
        self.assertTrue(CC.is_cloud_id("ollama-cloud/x"))
        self.assertFalse(CC.is_cloud_id("mlx-community/x"))
        for bad in ("", "a b", "../etc", "x" * 200):
            self.assertFalse(CC.valid_name(bad), bad)

    def test_scrub_never_lets_the_key_out(self):
        s = CC.scrub(f"bad {KEY} and Bearer {KEY} and {KEY[:-4]}", KEY)
        self.assertNotIn(KEY, s)
        self.assertNotIn(KEY[:-4], s)

    def test_usage_keeps_missing_numbers_missing(self):
        u = CC.usage_from_done({"done": True}, ttft_s=None, total_s=1.5)
        self.assertNotIn("prompt_tokens", u)
        self.assertNotIn("completion_tokens", u)
        self.assertNotIn("write_tok_s", u["caravan"])
        u = CC.usage_from_done({"eval_count": 10, "eval_duration": 500_000_000, "prompt_eval_count": 5}, ttft_s=0.2, total_s=1.0)
        self.assertEqual((u["prompt_tokens"], u["completion_tokens"]), (5, 10))
        self.assertEqual(u["caravan"]["write_tok_s"], 20.0)


class Choose(Base):
    def test_use_needs_a_key_then_status_shows_cloud_and_never_the_key(self):
        code, raw, _ = self.post("/api/cloud/use", {"provider": "ollama", "model": "gpt-oss:120b"})
        self.assertEqual(code, 400)
        self.assertEqual(json.loads(raw)["code"], "cloud_key_missing")
        self.assertIn("Settings → Cloud API keys", json.loads(raw)["error"])
        self.assertIsNone(self.get("/api/status")["cloud"])
        cur = self.use()
        self.assertEqual((cur["model"], cur["model_id"], cur["cloud_label"]), ("gpt-oss:120b", "ollama-cloud/gpt-oss:120b", "CLOUD"))
        st = self.get("/api/status")
        self.assertEqual(st["cloud"]["model"], "gpt-oss:120b")
        self.assert_no_key(json.dumps(st))
        code, raw, _ = self.post("/api/cloud/stop", {})
        self.assertEqual((code, json.loads(raw)["stopped"]), (200, True))
        self.assertIsNone(self.get("/api/status")["cloud"])

    def test_bad_model_name_and_unknown_provider(self):
        self.save_key()
        code, raw, _ = self.post("/api/cloud/use", {"provider": "ollama", "model": "a b c"})
        self.assertEqual((code, json.loads(raw)["code"]), (400, "cloud_bad_model"))
        code, _raw, _ = self.post("/api/cloud/use", {"provider": "openai", "model": "gpt-4o"})
        self.assertEqual(code, 400)

    def test_local_network_needs_the_ok_before_cloud(self):
        self.save_key()
        lan = {"Host": "192.168.1.20:8190"}
        code, raw, _ = self.post("/api/cloud/use", {"model": "gpt-oss:120b"}, headers=lan)
        self.assertEqual(code, 403, raw)
        j = json.loads(raw)
        self.assertEqual(j["code"], "cloud_lan_needs_ok")
        # The real risk, said plainly (Claude's review point).
        for words in ("same Wi-Fi", "Ollama Cloud account", "plan and its limits", "Ollama's servers", "Tailscale"):
            self.assertIn(words, j["warning"])
        self.assertIn("Tailscale", j["warning"])
        self.assert_no_key(raw)
        self.use()
        code, raw, _ = self.post("/api/chat", {"messages": [{"role": "user", "content": "hi"}]}, headers=lan)
        self.assertEqual(code, 403)
        self.assertEqual(json.loads(raw)["code"], "cloud_lan_needs_ok")
        self.assertEqual(self.ollama.chats(), [])
        self.assertFalse(LAN.cloud_ok_in_config())

    def test_ok_from_the_local_network_is_saved_and_cloud_works(self):
        self.save_key()
        lan = {"Host": "192.168.1.20:8190"}
        code, raw, _ = self.post("/api/lan", {"cloud_ok": True}, headers=lan)
        self.assertEqual(code, 200, raw)
        j = json.loads(raw)
        self.assertTrue(j["cloud_ok"])
        self.assertFalse(j["enabled"])  # the OK alone never turns the local network on
        self.assertTrue(LAN.cloud_ok_in_config())
        cfg = (self.home / "config.toml").read_text()
        self.assertIn("cloud_ok = true", cfg)
        self.assert_no_key(cfg)
        code, raw, _ = self.post("/api/cloud/use", {"model": "gpt-oss:120b"}, headers=lan)
        self.assertEqual(code, 200, raw)
        self.assert_no_key(raw)
        code, raw, _ = self.post("/api/chat", {"messages": [{"role": "user", "content": "hi"}], "stream": True},
                                 headers=dict(lan, **{"X-Caravan-Request": "req12345lan1"}))
        self.assertEqual(code, 200, raw)
        self.assert_no_key(raw)
        self.assertEqual(len(self.ollama.chats()), 1)
        # The key itself still stays hidden from the local network.
        r = Request(self.base + "/api/cloud-keys", headers=lan)
        try:
            with urlopen(r, timeout=10) as resp:
                body = resp.read().decode()
        except HTTPError as e:
            body = e.read().decode()
        self.assert_no_key(body)
        self.assertIn('"show": false', body)

    def test_status_tells_a_local_network_viewer_to_ask(self):
        self.use()
        r = Request(self.base + "/api/status", headers={"Host": "192.168.1.20:8190"})
        with urlopen(r, timeout=10) as resp:
            cloud = json.loads(resp.read().decode())["cloud"]
        self.assertTrue(cloud["lan_needs_ok"])
        self.assertIn("Tailscale", cloud["lan_warning"])
        self.assertFalse(self.get("/api/status")["cloud"]["lan_needs_ok"])
        LAN.set_cloud_ok(True)
        with urlopen(Request(self.base + "/api/status", headers={"Host": "192.168.1.20:8190"}), timeout=10) as resp:
            cloud = json.loads(resp.read().decode())["cloud"]
        self.assertFalse(cloud["lan_needs_ok"])
        self.assertNotIn("lan_warning", cloud)

    def test_turning_the_local_network_off_takes_back_the_ok(self):
        path = self.home / "config.toml"
        LAN.turn_on(port=8190, path=path)
        LAN.set_cloud_ok(True, path)
        info = LAN.inspect(port=8190, path=path)
        self.assertTrue(info["enabled"] and info["cloud_ok"])
        self.assertIn("Tailscale", info["cloud_warning"])
        info = LAN.turn_off(port=8190, path=path)
        self.assertFalse(info["cloud_ok"])
        self.assertFalse(LAN.cloud_ok_in_config(path))
        # Turning it on again asks again.
        self.assertFalse(LAN.turn_on(port=8190, path=path)["cloud_ok"])

    def test_turning_off_with_an_ok_does_not_save_it(self):
        self.app.rebind_listen = lambda wanted: True  # never re-exec the test process
        code, raw, _ = self.post("/api/lan", {"enabled": False, "cloud_ok": True})
        self.assertEqual(code, 200, raw)
        self.assertFalse(LAN.cloud_ok_in_config())

    def test_loading_a_mac_model_clears_cloud(self):
        src = (ROOT / "proxy/web_server.py").read_text()
        fn = src[src.index("        def _api_load(self"):src.index("        def _api_jobs(self")]
        tail = fn[fn.rindex("snap = dict(snap, balance_note=balanced_msg)"):]
        self.assertIn("app.cloud.clear()", tail)
        self.assertLess(tail.index("app.cloud.clear()"), tail.index("return self._json(200, snap)"))


class Stream(Base):
    def test_streams_like_a_mac_reply_with_cloud_label_and_stats(self):
        self.use()
        code, raw, headers = self.chat(thinking=True)
        self.assertEqual(code, 200, raw)
        self.assert_no_key(raw)
        self.assertNotIn("X-Caravan-Job", headers)  # not journaled: a replay would go to the Macs
        fr = self.frames(raw)
        text = "".join((f.get("choices") or [{}])[0].get("delta", {}).get("content") or "" for f in fr)
        think = "".join((f.get("choices") or [{}])[0].get("delta", {}).get("reasoning_content") or "" for f in fr)
        self.assertEqual(text, "Hello there.")
        self.assertEqual(think, "Let me think.")
        meta = [f for f in fr if f.get("object") == "caravan.meta"][0]
        self.assertEqual(meta["cloud"]["model"], "gpt-oss:120b")
        self.assertEqual(meta["cloud"]["cloud_label"], "CLOUD")
        st = meta["stats"]
        self.assertEqual((st["prompt_tokens"], st["completion_tokens"]), (12, 4))
        self.assertEqual(st["write_tok_s"], 100.0)  # 4 tokens / 0.04 s, Ollama's own eval_duration
        self.assertIsNotNone(st["ttft_s"])
        finish = [f for f in fr if (f.get("choices") or [{}])[0].get("finish_reason")]
        self.assertEqual(finish[0]["choices"][0]["finish_reason"], "stop")
        sent = self.ollama.chats()[0]
        self.assertEqual(sent["model"], "gpt-oss:120b")
        self.assertEqual(sent["options"], {"temperature": 0.7, "num_predict": 64})
        self.assertIs(sent["think"], True)
        auth = [h for p, h, _b in self.ollama.seen if p == "/api/chat"][0]
        self.assertEqual(auth.get("Authorization"), "Bearer " + KEY)

    def test_works_with_no_model_on_the_macs(self):
        self.assertNotEqual(self.app.mgr.snapshot().get("status"), "ready")
        code, _raw, _ = self.chat()
        self.assertEqual(code, 409)  # no cloud picked: the Macs answer "no model loaded"
        self.use()
        code, raw, _ = self.chat()
        self.assertEqual(code, 200, raw)

    def test_not_streamed(self):
        self.use()
        code, raw, _ = self.chat(stream=False)
        self.assertEqual(code, 200, raw)
        data = json.loads(raw)
        self.assertEqual(data["choices"][0]["message"]["content"], "Hello there.")
        self.assertEqual(data["usage"], {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14})
        self.assertEqual(data["caravan_web"]["cloud"]["model"], "gpt-oss:120b")
        self.assert_no_key(raw)

    def test_model_without_thinking_is_asked_again_without_it(self):
        self.use()
        self.ollama.mode = "nothink"
        code, raw, _ = self.chat(thinking=True)
        self.assertEqual(code, 200, raw)
        chats = self.ollama.chats()
        self.assertEqual(len(chats), 2)
        self.assertIn("think", chats[0])
        self.assertNotIn("think", chats[1])


class Errors(Base):
    def check(self, mode, status, code_word, words):
        self.use()
        self.ollama.mode = mode
        code, raw, _ = self.chat()
        self.assertEqual(code, status, raw)
        data = json.loads(raw)
        self.assertEqual(data["code"], code_word)
        self.assertIn(words, data["error"])
        self.assert_no_key(raw)
        return data

    def test_bad_key(self):
        self.check("401", 401, "cloud_key_rejected", "didn't accept the API key")

    def test_unknown_model(self):
        self.check("404", 404, "cloud_model_not_found", "no model named gpt-oss:120b")

    def test_rate_limited(self):
        self.check("429", 429, "cloud_rate_limited", "too many requests")

    def test_server_error(self):
        self.check("500", 502, "cloud_unavailable", "HTTP 500")

    def test_network_down(self):
        self.use()
        with mock.patch.dict(os.environ, {"CARAVAN_OLLAMA_CLOUD_URL": f"http://127.0.0.1:{_closed_port()}"}):
            code, raw, _ = self.chat()
        self.assertEqual(code, 502)
        self.assertEqual(json.loads(raw)["code"], "cloud_unreachable")
        self.assertIn("Couldn't reach Ollama Cloud", json.loads(raw)["error"])

    def test_key_removed_after_picking(self):
        self.use()
        CK.remove("ollama", home=self.home)
        code, raw, _ = self.chat()
        self.assertEqual((code, json.loads(raw)["code"]), (400, "cloud_key_missing"))
        self.assertEqual(self.ollama.chats(), [])

    def test_error_mid_stream_keeps_words_and_says_so(self):
        self.use()
        self.ollama.mode = "midstream_error"
        code, raw, _ = self.chat()
        self.assertEqual(code, 200)
        self.assert_no_key(raw)
        fr = self.frames(raw)
        self.assertEqual("".join((f.get("choices") or [{}])[0].get("delta", {}).get("content") or "" for f in fr), "Hello")
        err = [f for f in fr if f.get("error")][0]
        self.assertIn("Ollama Cloud stopped mid-reply", err["error"]["message"])
        self.assertTrue(err["partial"])

    def test_cut_stream(self):
        self.use()
        self.ollama.mode = "cut"
        code, raw, _ = self.chat()
        err = [f for f in self.frames(raw) if f.get("error")][0]
        self.assertIn("ended the reply early", err["error"]["message"])


class StopAndQueue(Base):
    def test_stop_ends_a_cloud_reply_and_keeps_words(self):
        self.use()
        self.ollama.mode = "slow"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "stream": True})
        conn.request("POST", "/api/chat", body=body, headers={"Content-Type": "application/json",
                                                                "X-Caravan-Request": "stopme12345"})
        resp = conn.getresponse()
        got = b""
        t0 = time.time()
        while b"Once" not in got and time.time() - t0 < 10:
            got += resp.read1(4096) if hasattr(resp, "read1") else resp.read(64)
        self.assertIn(b"Once", got)
        code, raw, _ = self.post("/api/chat/stop", {"request": "stopme12345"})
        self.assertEqual(code, 200, raw)
        rest = resp.read()
        conn.close()
        fr = self.frames((got + rest).decode())
        meta = [f for f in fr if f.get("object") == "caravan.meta"][0]
        self.assertTrue(meta["stopped"])
        self.assertEqual(meta["cloud"]["model"], "gpt-oss:120b")
        self.assertNotIn("more", "".join((f.get("choices") or [{}])[0].get("delta", {}).get("content") or "" for f in fr))
        self.assertEqual(self.app.live_chats, {})

    def test_two_chats_one_after_another(self):
        # The page's queue sends the next message after a reply ends.
        self.use()
        for _ in range(2):
            code, raw, _ = self.chat()
            self.assertEqual(code, 200, raw)
        self.assertEqual(len(self.ollama.chats()), 2)


class Catalog(Base):
    def rows(self, **kw):
        web_picker._cache.clear()
        out = web_picker.search_catalog("", source="cloud", **kw)
        return [q for g in out["groups"] for q in (g.get("quants") or [g]) if q.get("cloud")]

    def test_live_list_from_api_tags(self):
        with mock.patch.dict(os.environ, {"CARAVAN_OLLAMA_CLOUD_CATALOG": "live"}):
            rows, live = CC.catalog()
            self.assertTrue(live)
            self.assertEqual([r["name"] for r in rows], ["gpt-oss:120b", "gpt-oss:20b", "zeta-coder"])
            pick = self.rows()
        ids = {r["repo_id"] for r in pick}
        self.assertEqual(ids, {"ollama-cloud/gpt-oss:120b", "ollama-cloud/gpt-oss:20b", "ollama-cloud/zeta-coder"})
        coder = [r for r in pick if r["repo_id"].endswith("zeta-coder")][0]
        self.assertIn("coding", coder["filters"])
        self.assertIn("tools", coder["filters"])
        self.assertTrue(all(r["cloud_label"] == "CLOUD" and r["provider"] == "ollama" for r in pick))
        self.assertTrue(all(r["weights_gb"] is None for r in pick))

    def test_fallback_when_the_list_cant_be_read(self):
        with mock.patch.dict(os.environ, {"CARAVAN_OLLAMA_CLOUD_CATALOG": "live"}):
            self.ollama.mode = "tags_down"
            rows, live = CC.catalog()
        self.assertFalse(live)
        self.assertEqual([r["name"] for r in rows], list(CC.FALLBACK_MODELS))
        with mock.patch.dict(os.environ, {"CARAVAN_OLLAMA_CLOUD_URL": f"http://127.0.0.1:{_closed_port()}",
                                          "CARAVAN_OLLAMA_CLOUD_CATALOG": "live"}):
            rows, live = CC.catalog()
        self.assertFalse(live)

    def test_tests_never_reach_the_network_by_default(self):
        self.assertEqual(os.environ.get("CARAVAN_OLLAMA_CLOUD_CATALOG"), "static")
        seen = len(self.ollama.seen)
        CC.catalog()
        self.assertEqual(len(self.ollama.seen), seen)

    def test_download_route_still_refuses_cloud(self):
        code, raw, _ = self.post("/api/picker/download", {"repo_id": "ollama-cloud/gpt-oss:120b", "source": "cloud"})
        self.assertEqual(code, 400)
        self.assertIn("Press Load", json.loads(raw)["error"])


class Page(unittest.TestCase):
    def test_status_and_send_follow_the_cloud_pick(self):
        self.assertIn("setStatus(j.worker, j.cloud);", HTML)
        fn = HTML[HTML.index("  function setStatus(snap, cloud) {"):HTML.index("  async function refreshStatus()")]
        self.assertIn('text.dataset.status = state.cloud ? "ready" : st;', fn)
        self.assertIn('const chatOk = st === "ready" || !!state.cloud;', fn)
        self.assertIn('dot.classList.add("ok", "cloud")', fn)

    def test_first_chat_notice_and_cloud_label(self):
        send = HTML[HTML.index("  async function sendChat(queuedText) {"):HTML.index("  async function loadJourney()")]
        self.assertIn("if (state.cloud && !cloudNoticeSeen()) {", send)
        self.assertIn("This message leaves your Macs.", HTML)
        self.assertIn("if (!meta.cloud) showStats(", send)
        add = HTML[HTML.index("  function addMsg(role, text) {"):HTML.index("  // Follow streaming text only")]
        self.assertIn('tag.className = "cloud-tag";', add)

    def test_load_in_models_switches_chats_and_unload_goes_back(self):
        fn = HTML[HTML.index("    async function continueCloudLoad(q, p) {"):HTML.index("    function escapeHtml(s)")]
        self.assertIn("await window.caravanUseCloud(q);", fn)
        self.assertNotIn("isn't built yet", HTML)
        self.assertIn('api("/api/cloud/stop"', HTML)
        self.assertIn("if (state.cloud) return stopCloudChats();", HTML)

    def test_local_network_viewer_gets_the_warning_and_an_ok(self):
        main = HTML[HTML.index("  async function askLanCloudOk(warning) {"):HTML.index("  window.caravanUseCloud = useCloudModel;")]
        self.assertIn("Allow cloud chats from the local network?", main)
        self.assertIn('JSON.stringify({ cloud_ok: true })', main)
        self.assertIn('e.code === "cloud_lan_needs_ok"', main)
        send = HTML[HTML.index("  async function sendChat(queuedText) {"):HTML.index("  async function loadJourney()")]
        self.assertIn("if (state.cloud && state.cloud.lan_needs_ok) {", send)
        self.assertLess(send.index("state.cloud.lan_needs_ok"), send.index("cloudNoticeSeen()"))
        load = HTML[HTML.index("      if (!keys || keys.show === false) {"):]
        self.assertIn("continueCloudLoad(q,", load[:400])
        lanbtn = HTML[HTML.index("  function cloudMayBeUsed() {"):]
        self.assertIn("req.cloud_ok = window.confirm(", lanbtn)
        self.assertIn("(_lanInfo && _lanInfo.cloud_warning)", lanbtn)

    def test_page_never_sees_the_key(self):
        use = HTML[HTML.index("  async function useCloudModel(q) {"):HTML.index("  window.caravanUseCloud = useCloudModel;")]
        self.assertNotIn("key", use.replace("cloudNotice", ""))
        self.assertNotIn("framework only", HTML)


class Restart(Base):
    """Brenden (2026-11-24): "on restart, caravan needs to go back to how it
    was. If it was cloud, it should be cloud." """

    def restart(self):
        """A fresh App and page server on the same state folder, as after a
        restart of the Caravan service."""
        self.httpd.shutdown()
        self.httpd.server_close()
        mgr = WorkerManager(lead_port=_closed_port(), packer_peer="127.0.0.1:5560",
                            packer_ssh="nobody@127.0.0.1", state_dir=self.home / "state", repo=ROOT)
        app = web_server.App(mgr)
        app.nodes = lambda: {"nodes": []}
        app.configured_nodes = lambda: []
        app.update_inspect = lambda: {}
        app.cloud_keys_home = self.home
        self.app = app
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def choice_file(self):
        return self.home / "state" / CC.CHOICE_FILE

    def test_cloud_pick_is_saved_beside_last_model_without_the_key(self):
        self.use()
        path = self.choice_file()
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        raw = path.read_text()
        self.assert_no_key(raw)
        blob = json.loads(raw)
        self.assertEqual(blob["schema"], 1)
        self.assertEqual(blob["choice"], {"provider": "ollama", "model": "gpt-oss:120b", "label": "Ollama Cloud"})
        self.assertEqual(sorted(x.name for x in path.parent.iterdir() if x.name.startswith(".cloud-choice")), [])

    def test_restart_after_cloud_goes_back_to_cloud(self):
        self.use()
        self.restart()
        st = self.get("/api/status")["cloud"]
        self.assertEqual((st["model"], st["restored"], st["key_set"], st["problem"]), ("gpt-oss:120b", True, True, None))
        code, raw, _ = self.chat()
        self.assertEqual(code, 200, raw)
        self.assertEqual(self.ollama.chats()[-1]["model"], "gpt-oss:120b")

    def test_restart_after_macs_stays_on_macs(self):
        self.use()
        code, _raw, _ = self.post("/api/cloud/stop", {})
        self.assertEqual(code, 200)
        self.assertIsNone(json.loads(self.choice_file().read_text())["choice"])
        self.restart()
        self.assertIsNone(self.get("/api/status")["cloud"])
        code, _raw, _ = self.chat()
        self.assertEqual(code, 409)  # the Macs answer (nothing loaded in this test)
        self.assertEqual(self.ollama.chats(), [])

    def test_never_picked_is_macs(self):
        self.restart()
        self.assertFalse(self.choice_file().exists())
        self.assertIsNone(self.get("/api/status")["cloud"])

    def test_missing_key_after_restart_says_so_and_does_not_fall_back(self):
        self.use()
        CK.remove("ollama", home=self.home)
        self.restart()
        st = self.get("/api/status")["cloud"]
        self.assertEqual((st["model"], st["key_set"]), ("gpt-oss:120b", False))
        self.assertIn("Settings → Cloud API keys", st["problem"])
        code, raw, _ = self.chat()
        self.assertEqual((code, json.loads(raw)["code"]), (400, "cloud_key_missing"))
        self.assertEqual(self.ollama.chats(), [])
        # Saving the key again is all it takes; the pick was kept.
        self.save_key()
        self.assertIsNone(self.get("/api/status")["cloud"]["problem"])
        code, raw, _ = self.chat()
        self.assertEqual(code, 200, raw)

    def test_bad_key_after_restart_says_so_and_stays_cloud(self):
        self.use()
        self.restart()
        self.ollama.mode = "401"
        code, raw, _ = self.chat()
        self.assertEqual((code, json.loads(raw)["code"]), (401, "cloud_key_rejected"))
        self.assert_no_key(raw)
        self.assertEqual(self.get("/api/status")["cloud"]["model"], "gpt-oss:120b")

    def test_broken_or_odd_choice_files_mean_macs(self):
        path = self.choice_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        for text in ("{not json", json.dumps({"schema": 2, "choice": {"provider": "ollama", "model": "m"}}),
                     json.dumps({"schema": 1, "choice": {"provider": "openai", "model": "gpt-4o"}}),
                     json.dumps({"schema": 1, "choice": {"provider": "ollama", "model": "a b"}}),
                     json.dumps({"schema": 1, "choice": "x"}), "x" * (70 * 1024)):
            path.write_text(text)
            self.assertIsNone(CC.Choice(path).get(), text[:40])

    def test_mac_restore_at_start_keeps_cloud_but_a_user_load_clears_it(self):
        src = (ROOT / "proxy/web_server.py").read_text()
        fn = src[src.index("        def _api_load(self"):src.index("        def _api_jobs(self")]
        self.assertIn('if getattr(app, "cloud", None) is not None and not body.get("_restore_token"):', fn)
        self.assertIn("_restore_token=token", (ROOT / "proxy/web_restore.py").read_text())

    def test_in_memory_choice_without_a_folder(self):
        c = CC.Choice()
        c.set("gpt-oss:20b", "Ollama Cloud")
        self.assertEqual(c.get()["model"], "gpt-oss:20b")
        self.assertTrue(c.clear())
        self.assertIsNone(c.get())

    def test_page_says_why_a_restored_pick_cannot_chat(self):
        fn = HTML[HTML.index("  function setStatus(snap, cloud) {"):HTML.index("  async function refreshStatus()")]
        self.assertIn("if (state.cloud && state.cloud.problem) {", fn)
        self.assertIn('dot.classList.add("err", "cloud")', fn)


if __name__ == "__main__":
    unittest.main()
