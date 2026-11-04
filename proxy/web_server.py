"""Caravan web UI (Day 15) — chat, model switch, live Mini view, honest timing.

Serves a single static page plus a small JSON/SSE API. Binds LAN/Tailscale
(default 0.0.0.0:8190). Proxies chat to the local lead worker (8194) and
orchestrates lead+packer restarts when you switch models.

  python3 proxy/web_server.py --host 0.0.0.0 --port 8190

Stop with Ctrl-C or:  curl -X POST http://HOST:8190/api/shutdown
(only our own web process + the test workers we started).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "agent"))

import web_catalog as catalog
import web_settings  # noqa: E402
import web_timing as timing  # noqa: E402
from web_workers import WorkerManager  # noqa: E402

DEFAULT_HOST = os.environ.get("CARAVAN_WEB_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("CARAVAN_WEB_PORT", "8190"))


def load_journey() -> dict:
    p = WEB_DIR / "journey.json"
    if not p.exists():
        return {"versions": [], "series": {}}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {"versions": [], "series": {}, "error": "unreadable journey.json"}


class App:
    def __init__(self, mgr: WorkerManager):
        self.mgr = mgr
        self.started = time.time()
        self._shutdown = threading.Event()
        self.httpd = None

    def want_shutdown(self):
        self._shutdown.set()
        if self.httpd is not None:
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *a):
            sys.stderr.write("[web] " + (fmt % a) + "\n")

        # ---- helpers ----
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, X-Caravan-Session, X-Caravan-Sent")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _json(self, code, obj):
            data = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return None

        def _read_static(self, rel: str):
            # Safe join under WEB_DIR only.
            rel = rel.lstrip("/") or "index.html"
            if ".." in rel or rel.startswith("/"):
                return None, None
            path = (WEB_DIR / rel).resolve()
            if not str(path).startswith(str(WEB_DIR.resolve())):
                return None, None
            if not path.is_file():
                return None, None
            data = path.read_bytes()
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".ico": "image/x-icon",
            }.get(path.suffix.lower(), "application/octet-stream")
            return data, ctype

        # ---- routing ----
        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._serve_file("index.html")
            if path.startswith("/assets/") or path.startswith("/static/"):
                return self._serve_file(path.split("/", 2)[-1])
            if path == "/api/time":
                return self._api_time()
            if path == "/api/status":
                return self._api_status()
            if path == "/api/models":
                return self._json(200, {"models": catalog.list_models(),
                                       "current": app.mgr.snapshot().get("model_id")})
            if path == "/api/settings":
                return self._json(200, {"options": web_settings.OPTIONS,
                                       "current": app.mgr.snapshot().get("settings")})
            if path == "/api/journey":
                return self._json(200, load_journey())
            if path == "/api/split":
                snap = app.mgr.snapshot()
                info = app.mgr.lead_split_info() if snap.get("status") == "ready" else None
                return self._json(200, {"worker": snap, "split": info})
            if path.startswith("/api/"):
                return self._json(404, {"error": "not found"})
            # fall through to static
            rel = path.lstrip("/")
            data, ctype = self._read_static(rel)
            if data is None:
                return self._json(404, {"error": "not found"})
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            # Always drain Content-Length before any early return. Skipping
            # that on HTTP/1.1 keep-alive leaves the JSON body on the socket;
            # the next request then looks like `{"messages":...}GET /api/...`
            # (Bad request syntax) and the UI looks "stuck".
            path = self.path.split("?", 1)[0]
            body = self._body()
            if path == "/api/time":
                return self._api_time(post=True, body=body)
            if path == "/api/models/load":
                return self._api_load(body=body)
            if path == "/api/models/stop":
                app.mgr.stop(reason="ui")
                return self._json(200, app.mgr.snapshot())
            if path == "/api/chat":
                return self._api_chat(body=body)
            if path in ("/v1/chat/completions",):
                # Also accept the OpenAI path so tools can hit the UI port.
                return self._api_chat(body=body, openai_shape=True)
            if path == "/api/shutdown":
                app.want_shutdown()
                return self._json(200, {"ok": True})
            return self._json(404, {"error": "not found"})

        def _serve_file(self, rel):
            data, ctype = self._read_static(rel)
            if data is None:
                return self._json(404, {"error": "not found"})
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        # ---- API impl ----
        def _api_time(self, post=False, body=None):
            """NTP-style sample. Client may send {client_send} (seconds)."""
            server_recv = time.time()
            if post:
                if body is None:
                    body = {}
            else:
                body = {}
            if body is None:
                body = {}
            # Also accept ?t= query for GET.
            if not post and "?" in self.path:
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                if "t" in q:
                    try:
                        body = {"client_send": float(q["t"][0])}
                    except ValueError:
                        body = {}
            out = {
                "server_recv": server_recv,
                "server_send": time.time(),
                "client_send": body.get("client_send"),
            }
            return self._json(200, out)

        def _api_status(self):
            snap = app.mgr.snapshot()
            healthy = app.mgr.lead_healthy() if snap.get("status") == "ready" else False
            split = app.mgr.lead_split_info() if healthy else None
            return self._json(200, {
                "worker": snap,
                "lead_healthy": healthy,
                "split": split,
                "active": app.mgr.lead_active_settings() if healthy else None,
                "uptime_s": round(time.time() - app.started, 1),
                "ports": {"web": DEFAULT_PORT, "lead": app.mgr.lead_port,
                          "packer": app.mgr.packer_peer},
            })

        def _api_load(self, body=None):
            body = body or {}
            mid = body.get("model_id") or body.get("id")
            if not mid:
                return self._json(400, {"error": "model_id required"})
            try:
                snap = app.mgr.switch(mid, wait=False, settings=body.get("settings"))
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, snap)

        def _api_chat(self, body=None, openai_shape=False):
            # body already drained in do_POST (keep-alive safe).
            snap = app.mgr.snapshot()
            if snap.get("status") != "ready":
                return self._json(409, {"error": "no model loaded", "worker": snap})
            if not isinstance(body, dict):
                return self._json(400, {"error": "bad json"})
            # Stamp: Caravan received this request (Mini wall clock).
            t_received = time.time()
            sent_hdr = self.headers.get("X-Caravan-Sent")
            try:
                sent_browser = float(sent_hdr) if sent_hdr else None
            except ValueError:
                sent_browser = None

            body.setdefault("stream", True)
            # Ask the worker for usage on the stream so we get real caravan stats.
            so = body.get("stream_options") or {}
            if not isinstance(so, dict):
                so = {}
            so["include_usage"] = True
            body["stream_options"] = so

            session = self.headers.get("X-Caravan-Session") or uuid.uuid4().hex[:16]
            raw = json.dumps(body).encode()
            url = f"http://127.0.0.1:{app.mgr.lead_port}/v1/chat/completions"
            req = Request(url, data=raw, headers={
                "Content-Type": "application/json",
                "X-Caravan-Session": session,
            }, method="POST")

            stream = bool(body.get("stream"))
            try:
                upstream = urlopen(req, timeout=1800)
            except HTTPError as e:
                err = e.read().decode(errors="replace")[:500]
                return self._json(e.code, {"error": err})
            except URLError as e:
                return self._json(502, {"error": f"lead unreachable: {e}"})

            if not stream:
                try:
                    data = json.loads(upstream.read().decode())
                finally:
                    upstream.close()
                t_done = time.time()
                usage = (data.get("usage") or {})
                stats = timing.reply_stats(usage, wall_s=t_done - t_received)
                data["caravan_web"] = {
                    "timestamps": {
                        "sent_browser": sent_browser,
                        "received_mini": t_received,
                        "first_word_mini": t_received + float(stats["ttft_s"] or 0),
                        "done_mini": t_done,
                    },
                    "stats": stats, "settings": app.mgr.snapshot().get("settings"),
                    "session": session,
                }
                return self._json(200, data)

            # Streamed: re-emit SSE, inject a caravan-meta event at the end.
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Transfer-Encoding", "chunked")
            self._cors()
            self.end_headers()

            def send_chunk(payload: bytes):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(payload), payload))
                self.wfile.flush()

            def _scrub_frame(frame: bytes) -> bytes:
                """Strip end/channel markers from delta.content before forward."""
                out_lines = []
                changed = False
                for line in frame.split(b"\n"):
                    if not line.startswith(b"data: "):
                        out_lines.append(line)
                        continue
                    payload = line[6:].strip()
                    if payload == b"[DONE]":
                        out_lines.append(line)
                        continue
                    try:
                        obj = json.loads(payload)
                    except ValueError:
                        out_lines.append(line)
                        continue
                    chs = obj.get("choices") or []
                    if chs:
                        delta = (chs[0].get("delta") or {})
                        for key in ("content", "reasoning_content", "reasoning"):
                            if key in delta and isinstance(delta[key], str) and delta[key]:
                                scrubbed = timing.strip_reply_markers(delta[key])
                                if scrubbed != delta[key]:
                                    delta[key] = scrubbed
                                    changed = True
                        chs[0]["delta"] = delta
                        obj["choices"] = chs
                    out_lines.append(b"data: " + json.dumps(obj, ensure_ascii=False).encode())
                return b"\n".join(out_lines) if changed else frame

            t_first = None
            usage = None
            buf = b""
            try:
                while True:
                    chunk = upstream.read(1024)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n\n" in buf:
                        frame, buf = buf.split(b"\n\n", 1)
                        # Parse data lines for first content + usage.
                        for line in frame.split(b"\n"):
                            if not line.startswith(b"data: "):
                                continue
                            payload = line[6:].strip()
                            if payload == b"[DONE]":
                                continue
                            try:
                                obj = json.loads(payload)
                            except ValueError:
                                continue
                            # First content?
                            if t_first is None:
                                ch0 = (obj.get("choices") or [{}])[0]
                                delta = ch0.get("delta") or {}
                                if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                                    t_first = time.time()
                            if obj.get("usage"):
                                usage = obj["usage"]
                        # Forward scrubbed frame (with blank line).
                        send_chunk(_scrub_frame(frame) + b"\n\n")
            except (BrokenPipeError, ConnectionResetError):
                return
            finally:
                try:
                    upstream.close()
                except Exception:
                    pass

            t_done = time.time()
            if t_first is None:
                # No content tokens (e.g. empty) — treat first == done.
                t_first = t_done
            stats = timing.reply_stats(usage or {}, wall_s=t_done - t_received)
            # Prefer worker's own ttft when present for first_word estimate.
            if stats.get("ttft_s") is not None:
                first_mini = t_received + float(stats["ttft_s"])
            else:
                first_mini = t_first
            meta = {
                "id": "caravan-meta",
                "object": "caravan.meta",
                "timestamps": {
                    "sent_browser": sent_browser,
                    "received_mini": round(t_received, 6),
                    "first_word_mini": round(first_mini, 6),
                    "first_word_proxy": round(t_first, 6),
                    "done_mini": round(t_done, 6),
                },
                "stats": stats,
                "settings": app.mgr.snapshot().get("settings"),
                "session": session,
            }
            try:
                send_chunk(f"data: {json.dumps(meta)}\n\n".encode())
                send_chunk(b"data: [DONE]\n\n")
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--lead-port", type=int, default=int(os.environ.get("CARAVAN_WEB_LEAD_PORT", "8194")))
    ap.add_argument("--packer-peer", default=catalog.DEFAULT_PACKER_PEER)
    ap.add_argument("--packer-ssh", default=catalog.DEFAULT_PACKER_SSH)
    ap.add_argument("--repo", default=str(HERE.parent))
    args = ap.parse_args(argv)

    mgr = WorkerManager(
        lead_port=args.lead_port,
        packer_peer=args.packer_peer,
        packer_ssh=args.packer_ssh,
        repo=Path(args.repo),
    )
    app = App(mgr)
    # Skip getfqdn reverse-DNS (same issue as health_server on the Minis).
    class _Server(ThreadingHTTPServer):
        def server_bind(self):
            import socketserver
            socketserver.TCPServer.server_bind(self)
            self.server_name = self.server_address[0]
            self.server_port = self.server_address[1]

    httpd = _Server((args.host, args.port), make_handler(app))
    httpd.daemon_threads = True
    app.httpd = httpd
    print(f"[caravan-web] listening on http://{args.host}:{args.port}", flush=True)
    print(f"[caravan-web] open http://<EXO1-tailscale-or-LAN>:{args.port}/", flush=True)
    print(f"[caravan-web] lead worker port {args.lead_port}; packer {args.packer_peer}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("[caravan-web] shutting down; stopping test workers", flush=True)
        try:
            mgr.stop(reason="web-server exit")
        except Exception as e:
            print(f"[caravan-web] stop warn: {e}", flush=True)
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
