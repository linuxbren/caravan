"""MLX step (a): proxy routing to mlx_lm.server (proxy/backends.py +
slot_pin_proxy.py) and the launch side (agent/mlx_backend.py,
render_mlx_plist.py). Fake upstreams on 127.0.0.1, temp dirs only.
"""
import http.client
import json
import os
import plistlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
sys.path.insert(0, str(REPO / "agent"))
sys.path.insert(0, str(REPO / "tests"))

import backends  # noqa: E402
from test_proxy_perf import ProxyTestBase  # noqa: E402

MLX_ENV = ("CARAVAN_MLX_ENABLED", "CARAVAN_MLX_HOST", "CARAVAN_MLX_PORT", "CARAVAN_MLX_PREFIXES",
           "CARAVAN_MLX_MODEL_DIRS", "CARAVAN_MLX_PYTHON", "CARAVAN_MLX_EXTRA_ARGS")


class FakeMlx:
    """Stands in for mlx_lm.server: records request bodies, answers JSON
    or SSE. Knows nothing about slots (404s them, like the real one)."""

    def __init__(self):
        self.bodies, self.paths = [], []
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                fake.paths.append(self.path)
                if not self.path.startswith("/v1/"):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                fake.bodies.append(body)
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for ev in (b'data: {"mlx": 1}\n\n', b"data: [DONE]\n\n"):
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(ev), ev))
                    self.wfile.write(b"0\r\n\r\n")
                    return
                out = json.dumps({"model": body.get("model"), "choices": [{"message": {"content": "mlx"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _mlx_model_dir(root: Path, repo_id: str) -> Path:
    d = root / repo_id.replace("/", "--")
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    return d


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {k: "" for k in MLX_ENV})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_precedence_flag_env_config_default(self):
        s = backends.resolve_mlx_settings({})
        self.assertEqual((s.enabled, s.host, s.port, s.model_prefixes),
                         (True, "127.0.0.1", 8092, ("mlx-community/",)))
        cfg = {"mlx": {"port": 9000, "model_prefixes": ["mine/"], "models": {"alias": "/x"}}}
        self.assertEqual(backends.resolve_mlx_settings(cfg).port, 9000)
        with mock.patch.dict(os.environ, {"CARAVAN_MLX_PORT": "9100", "CARAVAN_MLX_PREFIXES": "a/,b/"}):
            s = backends.resolve_mlx_settings(cfg)
            self.assertEqual((s.port, s.model_prefixes), (9100, ("a/", "b/")))
            self.assertEqual(backends.resolve_mlx_settings(cfg, {"port": 9200}).port, 9200)
        with self.assertRaises(ValueError):
            backends.resolve_mlx_settings({"mlx": {"port": "nope"}})
        self.assertFalse(backends.resolve_mlx_settings({}, {"enabled": False}).enabled)

    def test_routing_and_paths(self):
        d = _mlx_model_dir(self.root, "mlx-community/Qwen3-30B-A3B-4bit")
        s = backends.resolve_mlx_settings({"mlx": {"model_dirs": [str(self.root)],
                                                   "models": {"qwen-mlx": str(d)}}})
        self.assertTrue(backends.is_mlx_model("mlx-community/Qwen3-30B-A3B-4bit", s))
        self.assertTrue(backends.is_mlx_model("qwen-mlx", s))
        for gguf in ("qwen3:30b", "gemma-4-26B_q4_0-it.gguf", None, ""):
            self.assertFalse(backends.is_mlx_model(gguf, s))
        self.assertEqual(backends.resolve_mlx_model_path("mlx-community/Qwen3-30B-A3B-4bit", s), str(d))
        self.assertEqual(backends.resolve_mlx_model_path("qwen-mlx", s), str(d))
        self.assertIsNone(backends.resolve_mlx_model_path("mlx-community/absent", s))
        off = s._replace(enabled=False)
        self.assertFalse(backends.is_mlx_model("mlx-community/Qwen3-30B-A3B-4bit", off))

    def test_launch_command_and_plist(self):
        import mlx_backend
        import render_mlx_plist
        d = _mlx_model_dir(self.root, "mlx-community/gemma-4-26b-a4b-it-4bit")
        cfg = {"mlx": {"model_dirs": [str(self.root)], "python": "/venv/bin/python",
                       "extra_args": ["--prompt-cache-size", "4"]}}
        cmd = mlx_backend.build_mlx_command("mlx-community/gemma-4-26b-a4b-it-4bit", cfg, {"port": 8192})
        self.assertEqual(cmd, ["/venv/bin/python", "-m", "mlx_lm", "server", "--model", str(d),
                               "--host", "127.0.0.1", "--port", "8192", "--prompt-cache-size", "4"])
        with self.assertRaises(FileNotFoundError):  # never lets mlx_lm download
            mlx_backend.build_mlx_command("mlx-community/not-here", cfg)
        out = self.root / "p.plist"
        with mock.patch.object(render_mlx_plist.config, "load_config_file", return_value=cfg):
            with mock.patch("sys.stdout"):
                render_mlx_plist.main(["mlx-community/gemma-4-26b-a4b-it-4bit", "-o", str(out)])
        pl = plistlib.loads(out.read_bytes())
        self.assertEqual(pl["Label"], "com.caravan.mlx-server")
        self.assertEqual(pl["ProgramArguments"][:4], ["/venv/bin/python", "-m", "mlx_lm", "server"])


class ProxyRoutingTest(ProxyTestBase):
    def setUp(self):
        self._mlxenv = mock.patch.dict(os.environ, {k: "" for k in MLX_ENV})
        self._mlxenv.start()
        super().setUp()
        self.mlx = FakeMlx()
        self.model_dir = _mlx_model_dir(self.tmp / "mlxmodels", "mlx-community/Qwen3-30B-A3B-4bit")
        self.spp.configure_mlx({"port": self.mlx.port, "model_dirs": [str(self.tmp / "mlxmodels")]})

    def tearDown(self):
        self.mlx.close()
        super().tearDown()
        self._mlxenv.stop()

    def post(self, body):
        c = http.client.HTTPConnection("127.0.0.1", self.proxy_port, timeout=10)
        c.request("POST", "/v1/chat/completions", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        self.settle()
        return r, data

    def msgs(self, text):
        return [{"role": "system", "content": "sys"}, {"role": "user", "content": text}]

    def test_mlx_model_goes_to_mlx_without_slot_io(self):
        r, data = self.post({"model": "mlx-community/Qwen3-30B-A3B-4bit", "id_slot": 3,
                             "cache_prompt": True, "messages": self.msgs("x" * 200)})
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(data)["choices"][0]["message"]["content"], "mlx")
        sent = self.mlx.bodies[-1]
        self.assertEqual(sent["model"], str(self.model_dir))  # local copy, not a download
        self.assertNotIn("id_slot", sent)
        self.assertNotIn("cache_prompt", sent)
        # llama-server untouched: no completion, no /slots, no save/restore
        self.assertEqual(self.fake.calls, [])
        log = self.stderr.getvalue()
        self.assertIn("backend=mlx", log)
        self.assertIn("cache=mlx-noop", log)
        self.assertIn("slot save mlx-noop", log)
        # same session again -> still pinned by fingerprint, now "warm"
        self.post({"model": "mlx-community/Qwen3-30B-A3B-4bit", "messages": self.msgs("x" * 200)})
        self.assertIn("(warm;", self.stderr.getvalue())

    def test_gguf_model_still_goes_to_llama(self):
        r, _ = self.post({"model": "qwen3:30b", "messages": self.msgs("y" * 200)})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.mlx.bodies, [])
        self.assertEqual(self.fake.count("POST", "/v1/chat/completions"), 1)
        self.assertGreaterEqual(self.fake.count("POST", "/slots/", "action=save"), 1)

    def test_mlx_streaming_passthrough(self):
        r, data = self.post({"model": "mlx-community/Qwen3-30B-A3B-4bit", "stream": True,
                             "messages": self.msgs("z" * 200)})
        self.assertEqual(r.status, 200)
        self.assertIn(b"[DONE]", data)

    def test_mlx_down_is_502_naming_mlx(self):
        self.mlx.close()
        self.spp.configure_mlx({"port": self.mlx.port, "model_dirs": [str(self.tmp / "mlxmodels")]})
        r, data = self.post({"model": "mlx-community/Qwen3-30B-A3B-4bit", "messages": self.msgs("q" * 200)})
        self.assertEqual(r.status, 502)
        self.assertIn(b"mlx_lm.server", data)
        self.mlx = FakeMlx()  # for tearDown

    def test_no_mlx_routes_everything_to_llama(self):
        self.spp.configure_mlx({"enabled": False})
        self.post({"model": "mlx-community/Qwen3-30B-A3B-4bit", "messages": self.msgs("w" * 200)})
        self.assertEqual(self.mlx.bodies, [])
        self.assertEqual(self.fake.count("POST", "/v1/chat/completions"), 1)


if __name__ == "__main__":
    unittest.main()
