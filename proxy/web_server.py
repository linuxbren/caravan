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
import web_optimize  # noqa: E402
import web_picker  # noqa: E402

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
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._nodes_lock = threading.Lock()
        self._nodes_cache = None
        self._nodes_busy = False
        self.optimizer = web_optimize.Optimizer(mgr, inflight=lambda: self._inflight)

    # ---- ROADMAP #14: live node view (GET /api/nodes) -------------------
    NODES_TTL = 0.4

    def nodes(self) -> dict:
        """Cached ~400ms; refreshed in the background so polls stay fast."""
        with self._nodes_lock:
            c = self._nodes_cache
            stale = c is None or time.time() - c["t"] > self.NODES_TTL
            if stale and not self._nodes_busy:
                self._nodes_busy = True
                threading.Thread(target=self._nodes_refresh, daemon=True).start()
        if c is None:
            # First call: wait for the first gather.
            for _ in range(150):
                time.sleep(0.1)
                if self._nodes_cache is not None:
                    break
            c = self._nodes_cache or {"t": time.time(), "nodes": [], "error": "gathering"}
        return c

    def _nodes_refresh(self):
        try:
            import node_stats
            out = {"lead": None, "packer": None}

            def local():
                try:
                    out["lead"] = node_stats.gather()
                except Exception as e:  # noqa: BLE001
                    out["lead"] = {"error": str(e)}

            def remote():
                try:
                    r = self.mgr._ssh("/usr/bin/python3 ~/cv3/proxy/node_stats.py", timeout=25)
                    out["packer"] = (json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0
                                     else {"error": (r.stderr or r.stdout or "ssh failed")[-200:]})
                except Exception as e:  # noqa: BLE001
                    out["packer"] = {"error": str(e)}

            ts = [threading.Thread(target=local), threading.Thread(target=remote)]
            for t in ts:
                t.start()
            snap = self.mgr.snapshot()
            split = self.mgr.lead_split_info() if snap.get("status") == "ready" else None
            for t in ts:
                t.join(30)
            lead_l = (split or {}).get("lead") or {}
            pk = ((split or {}).get("packers") or [{}])[0] if split and not split.get("error") else {}
            model = snap.get("model_name") if snap.get("status") == "ready" else None
            nodes = [
                dict(out["lead"] or {}, role="lead", label="EXO1", model=model,
                     layers=lead_l.get("name"), weights_gb=lead_l.get("weights_gb"),
                     active_gb=lead_l.get("active_gb")),
                dict(out["packer"] or {}, role="packer", label="EXO2", model=model,
                     layers=pk.get("name"), weights_gb=pk.get("weights_gb"),
                     active_gb=pk.get("active_gb"), sessions=pk.get("sessions")),
            ]
            self._nodes_cache = {"t": time.time(), "status": snap.get("status"),
                                 "link": (split or {}).get("peer") or self.mgr.packer_peer,
                                 "nodes": nodes}
        finally:
            self._nodes_busy = False

    def chat_begin(self):
        with self._inflight_lock:
            self._inflight += 1

    def chat_end(self):
        with self._inflight_lock:
            self._inflight = max(0, self._inflight - 1)

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
                return self._api_settings()
            if path == "/api/nodes":
                return self._json(200, app.nodes())
            if path == "/api/optimize":
                return self._json(200, app.optimizer.snapshot())
            if path == "/api/journey":
                return self._json(200, load_journey())
            if path == "/api/split":
                snap = app.mgr.snapshot()
                info = app.mgr.lead_split_info() if snap.get("status") == "ready" else None
                return self._json(200, {"worker": snap, "split": info})
            if path == "/api/picker/search":
                return self._api_picker_search()
            if path == "/api/picker/disk":
                return self._api_picker_disk()
            if path == "/api/picker/jobs":
                return self._json(200, {"jobs": web_picker.list_jobs()})
            if path.startswith("/api/picker/jobs/"):
                jid = path.rsplit("/", 1)[-1]
                job = web_picker.get_job(jid)
                return self._json(200 if job else 404, job or {"error": "not found"})
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
            if path == "/api/optimize/start":
                if app.mgr._switch_thread and app.mgr._switch_thread.is_alive():
                    return self._json(409, {"error": "a model load is in progress"})
                try:
                    return self._json(200, app.optimizer.start((body or {}).get("mode") or "deep"))
                except RuntimeError as e:
                    return self._json(409, {"error": str(e)})
            if path == "/api/optimize/cancel":
                return self._json(200, app.optimizer.cancel())
            if path in ("/api/chat", "/v1/chat/completions"):
                # /v1 path too so tools can hit the UI port.
                app.chat_begin()
                try:
                    return self._api_chat(body=body, openai_shape=(path != "/api/chat"))
                finally:
                    app.chat_end()
            if path == "/api/shutdown":
                app.want_shutdown()
                return self._json(200, {"ok": True})
            if path == "/api/picker/download":
                return self._api_picker_download(body=body)
            if path == "/api/picker/download/cancel":
                jid = (body or {}).get("job_id") or ""
                return self._json(200, web_picker.cancel_job(jid))
            if path == "/api/picker/delete":
                return self._api_picker_delete(body=body)
            if path == "/api/picker/fit":
                return self._api_picker_fit(body=body)
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
            active = app.mgr.lead_active_settings() if healthy else None
            return self._json(200, {
                "tuning": app.mgr.tuning_status(active) if healthy else None,
                "optimize": {k: v for k, v in app.optimizer.snapshot().items()
                             if k in ("running", "mode", "phase", "eta_s")},
                "worker": snap,
                "lead_healthy": healthy,
                "split": split,
                "active": active,
                "uptime_s": round(time.time() - app.started, 1),
                "ports": {"web": DEFAULT_PORT, "lead": app.mgr.lead_port,
                          "packer": app.mgr.packer_peer},
            })

        def _api_settings(self):
            # ?model=<id>: what ~/.caravan/config.toml pins for that model (ROADMAP #13c).
            from urllib.parse import parse_qs, urlparse
            snap = app.mgr.snapshot()
            q = parse_qs(urlparse(self.path).query)
            mid = (q.get("model") or [None])[0] or snap.get("model_id")
            entry = catalog.get_model(mid) if mid else None
            cfg = web_settings.load_config()
            fsets = web_settings.file_settings(mid, (entry or {}).get("lead_path"), cfg) if mid else {}
            return self._json(200, {"options": web_settings.OPTIONS,
                                   "current": snap.get("page_settings") or snap.get("settings"),
                                   "file": {"path": cfg["path"], "exists": cfg["exists"],
                                            "errors": cfg["errors"], "model": mid, "pins": fsets},
                                   "from_file_loaded": snap.get("from_file") or {}})


        def _api_picker_search(self):
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            q = (qs.get("q") or qs.get("query") or [""])[0]
            source = (qs.get("source") or ["all"])[0]
            try:
                limit = int((qs.get("limit") or ["30"])[0])
            except ValueError:
                limit = 30
            cat = web_picker.search_catalog(q, source=source, limit=limit)
            raw = app.nodes() or {}
            nodes = raw.get("nodes") or []
            cat["groups"] = web_picker.attach_fit(cat.get("groups") or [], nodes)
            cat["nodes_used"] = len(nodes)
            return self._json(200, cat)

        def _api_picker_disk(self):
            packer_sizes = {}
            try:
                cmd = (
                    'python3 -c "import json; from pathlib import Path; '
                    "roots=[Path.home()/'.caravan'/'mlx-models', Path.home()/'.exo'/'models']; out={}; "
                    "[out.__setitem__(p.name.replace('--','/'), round(sum(f.stat().st_size for f in p.rglob('*') if f.is_file())/1e9, 2)) "
                    'for root in roots if root.is_dir() for p in root.iterdir() if p.is_dir()]; '
                    'print(json.dumps(out))"'
                )
                r = app.mgr._ssh(cmd, timeout=60)
                if r.returncode == 0 and (r.stdout or "").strip():
                    packer_sizes = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception as e:  # noqa: BLE001
                packer_sizes = {"_error": str(e)}
            return self._json(200, {
                "models": web_picker.list_installed(packer_sizes={
                    k: v for k, v in packer_sizes.items() if not str(k).startswith("_")
                }),
                "packer": packer_sizes,
                "current": app.mgr.snapshot().get("model_id"),
            })

        def _api_picker_delete(self, body=None):
            body = body or {}
            rid = body.get("id") or body.get("repo_id") or ""
            if not body.get("confirm"):
                return self._json(400, {"error": "confirm=true required"})

            def ssh_delete(folder):
                r = app.mgr._ssh(
                    "rm -rf ~/.caravan/mlx-models/%s ~/.exo/models/%s; echo REMOVED" % (folder, folder),
                    timeout=120,
                )
                return {"removed": "REMOVED" in (r.stdout or ""), "rc": r.returncode}

            out = web_picker.delete_model(
                rid,
                current_model_id=app.mgr.snapshot().get("model_id"),
                ssh_delete=ssh_delete,
            )
            return self._json(200 if out.get("ok") else 400, out)

        def _api_picker_fit(self, body=None):
            body = body or {}
            nodes = (app.nodes() or {}).get("nodes") or []
            fit = web_picker.fit_check(
                weights_gb=float(body.get("weights_gb") or 0),
                nodes=nodes,
                cfg=body.get("cfg"),
                n_layers=body.get("n_layers"),
                ctx_tokens=int(body.get("ctx_tokens") or web_picker.DEFAULT_CTX),
                split_ok=bool(body.get("split_ok", True)),
            )
            return self._json(200, fit)

        def _api_picker_download(self, body=None):
            body = body or {}
            repo = (body.get("repo_id") or body.get("id") or "").strip()
            if not repo:
                return self._json(400, {"error": "repo_id required"})
            if body.get("source") == "cloud" or repo.startswith("ollama-cloud/"):
                return self._json(400, {"error": "cloud models are framework-only for now"})
            if body.get("source") == "gguf":
                return self._json(400, {"error": "GGUF download via llama-server is phase 4"})
            packer_layers = body.get("packer_layers")
            try:
                packer_layers = int(packer_layers) if packer_layers is not None else None
            except (TypeError, ValueError):
                packer_layers = None

            def run_lead(repo_id, dest, pk, prog):
                web_picker.local_download_mlx(repo_id, dest, pk, prog, role="lead")

            def run_packer(repo_id, dest, pk, prog):
                dest_q = dest.replace("'", "")
                script = (
                    "mkdir -p %s; "
                    "~/.caravan/venvs/mlx/bin/python ~/cv3/agent/mlx_split_fetch.py "
                    "%s %s --role packer "
                    % (dest_q, repo_id, dest_q)
                )
                if pk:
                    script += "--packer-layers %d " % int(pk)
                script += "&& echo PACKER_DL_DONE"
                prog(10, "ssh packer")
                r = app.mgr._ssh(script, timeout=3600)
                if r.returncode != 0 or "PACKER_DL_DONE" not in (r.stdout or ""):
                    raise RuntimeError((r.stderr or r.stdout or "packer download failed")[-400:])
                prog(100, "done")

            job = web_picker.start_download(
                repo,
                packer_layers=packer_layers,
                run_lead=run_lead,
                run_packer=run_packer,
            )
            return self._json(200, {"job": job})


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
                "memory_guard": (stats or {}).get("memory_guard"),
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
    try:
        if mgr.adopt_running():
            print("[caravan-web] adopted running lead from before restart", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[caravan-web] adopt skipped: {e}", flush=True)
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
