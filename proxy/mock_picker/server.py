#!/usr/bin/env python3
"""Serve the real picker UI with mocked /api/nodes + /api/picker/search.

Usage:
  python3 proxy/mock_picker/server.py --nodes 1 --port 8191
  python3 proxy/mock_picker/server.py --nodes 3 --port 8192
"""
from __future__ import annotations
import argparse, json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
WEB = HERE.parent / "web"
sys.path.insert(0, str(HERE.parent))
import web_picker  # noqa: E402

def fake_nodes(n: int):
    specs = [
        ("exo1", "EXO1", "lead", 24.0, 18.0),
        ("exo2", "EXO2", "packer", 24.0, 16.0),
        ("exo3", "EXO3", "packer", 16.0, 12.0),
    ]
    out = []
    for i in range(n):
        nid, label, role, total, avail = specs[i]
        out.append({
            "id": nid, "label": label, "role": role, "host": "local" if i == 0 else nid,
            "offline": False,
            "ram": {"total_gb": total, "available_gb": avail, "free_gb": avail},
            "disk": {"free_gb": 200},
            "active_gb": 0, "weights_gb": 0,
        })
    return out

class H(BaseHTTPRequestHandler):
    nodes = []
    def log_message(self, fmt, *a):
        sys.stderr.write("[mock] " + (fmt % a) + "\n")
    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def _file(self, path: Path, ctype="text/html"):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            html = (WEB / "index.html").read_text()
            try:
                import caravan_i18n
                html = caravan_i18n.render_page(html)
            except Exception:
                pass
            inject = """
<script>
document.addEventListener('DOMContentLoaded', function(){
  setTimeout(function(){
    var b = document.getElementById('btnOpenPicker');
    if (b) b.click();
  }, 400);
});
</script>
"""
            if "</body>" in html:
                html = html.replace("</body>", inject + "</body>", 1)
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path.startswith("/static/") or u.path.startswith("/web/"):
            rel = u.path.split("/", 2)[-1]
            p = WEB / Path(u.path).name
            if p.exists():
                return self._file(p, "application/javascript" if p.suffix == ".js" else "text/css")
        # Serve any asset next to index by basename
        name = Path(u.path).name
        cand = WEB / name
        if cand.is_file():
            ctype = {".css":"text/css",".js":"application/javascript",".svg":"image/svg+xml",
                     ".png":"image/png",".json":"application/json"}.get(cand.suffix, "application/octet-stream")
            return self._file(cand, ctype)
        if u.path == "/api/nodes":
            return self._json(200, {
                "t": 0, "status": "ready", "nodes": self.nodes,
                "max_split_stages": 2, "configured": len(self.nodes),
                "online": len(self.nodes),
            })
        if u.path == "/api/picker/search":
            qs = parse_qs(u.query)
            q = (qs.get("q") or [""])[0]
            filt = (qs.get("filter") or ["chat"])[0]
            # Build a small synthetic catalog with fit attached
            groups = [
                {
                    "base": "Qwen2.5-Coder-7B-Instruct",
                    "source": "hf-mlx", "likes": 100,
                    "quants": [
                        {"repo_id": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
                         "quant": "4bit", "weights_gb": 4.28, "source": "hf-mlx"},
                        {"repo_id": "mlx-community/Qwen2.5-Coder-7B-Instruct-MLX",
                         "quant": "MLX", "weights_gb": 15.23, "source": "hf-mlx"},
                        {"repo_id": "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit",
                         "quant": "32B-4bit", "weights_gb": 18.5, "source": "hf-mlx"},
                    ],
                },
                {
                    "base": "Flash-Something-Huge",
                    "source": "hf-mlx", "likes": 10,
                    "quants": [
                        {"repo_id": "mlx-community/huge-111",
                         "quant": "4bit", "weights_gb": 111.5, "source": "hf-mlx"},
                    ],
                },
                {
                    "base": "Qwen2.5-7B-Instruct-GGUF",
                    "source": "gguf", "likes": 50,
                    "quants": [
                        {"repo_id": "gguf-pub/Qwen2.5-7B-Instruct-GGUF",
                         "quant": "Q4_K_M", "weights_gb": 4.68, "source": "gguf",
                         "gguf_file": "Qwen2.5-7B-Instruct-Q4_K_M.gguf"},
                        {"repo_id": "gguf-pub/Qwen2.5-7B-Instruct-GGUF",
                         "quant": "Q8_0", "weights_gb": 8.10, "source": "gguf",
                         "gguf_file": "Qwen2.5-7B-Instruct-Q8_0.gguf"},
                    ],
                },
                {
                    "base": "Big-Reasoning-GGUF",
                    "source": "gguf", "likes": 20,
                    "quants": [
                        {"repo_id": "gguf-pub/Big-Reasoning-GGUF",
                         "quant": "Q4_K_M", "weights_gb": 18.5, "source": "gguf",
                         "gguf_file": "Big-Reasoning-Q4_K_M.gguf"},
                    ],
                },
                {
                    "base": "Huge-Does-Not-Fit-GGUF",
                    "source": "gguf", "likes": 5,
                    "quants": [
                        {"repo_id": "gguf-pub/Huge-Does-Not-Fit-GGUF",
                         "quant": "Q8_0", "weights_gb": 111.5, "source": "gguf",
                         "gguf_file": "Huge-Does-Not-Fit-Q8_0.gguf"},
                    ],
                },
            ]
            src = (qs.get("source") or ["all"])[0]
            if src and src not in ("all",):
                groups = [g for g in groups if g.get("source") == src
                          or any((qq.get("source") == src) for qq in g.get("quants") or [])]
            if q:
                groups = [g for g in groups if q.lower() in g["base"].lower()
                          or any(q.lower() in (qq.get("repo_id") or "") for qq in g["quants"])]
                if not groups:
                    groups = [{
                        "base": q or "demo", "source": "hf-mlx", "likes": 0,
                        "quants": [{"repo_id": f"mlx-community/{q or 'demo'}-4bit",
                                    "quant": "4bit", "weights_gb": 8.0, "source": "hf-mlx"}],
                    }]
            groups = web_picker.attach_fit(groups, self.nodes)
            return self._json(200, {
                "groups": groups,
                "nodes_used": len(self.nodes),
                "nodes_configured": len(self.nodes),
                "max_split_stages": 2,
                "node_labels": [n["label"] for n in self.nodes],
                "filter": filt,
            })
        if u.path == "/api/picker/disk":
            return self._json(200, {"models": [], "cleanup": [], "current": None,
                                    "max_split_stages": 2})
        if u.path == "/api/language":
            import caravan_i18n
            return self._json(200, {"language": caravan_i18n.language(),
                                    "languages": caravan_i18n.picker_languages()})
        if u.path.startswith("/api/"):
            return self._json(200, {"ok": True, "mock": True})
        self.send_error(404)

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except ValueError:
            body = {}
        if u.path == "/api/picker/placement":
            import placement as PL
            import gguf_split as GS
            weights = float(body.get("weights_gb") or 0)
            if body.get("source") == "gguf":
                out = GS.placement_options(weights, self.nodes)
            else:
                fit = web_picker.fit_check(weights_gb=weights, nodes=self.nodes, split_ok=True)
                out = PL.placement_options(fit=fit, nodes=self.nodes, max_split_stages=2, weights_gb=weights)
            return self._json(200, out)
        if u.path == "/api/picker/download":
            return self._json(200, {"job": {"id": "mock-job", "status": "queued", "repo_id": body.get("repo_id"),
                                            "placement_id": body.get("placement_id")}})
        if u.path == "/api/language":
            import caravan_i18n
            code = (body or {}).get("language")
            if isinstance(code, str) and caravan_i18n.normalize_language(code):
                # Only persist when CARAVAN_HOME is set, so the mock never
                # writes the developer's real ~/.caravan/prefs.
                import os
                if os.environ.get("CARAVAN_HOME"):
                    caravan_i18n.save_language(code)
                else:
                    os.environ["CARAVAN_LANG"] = caravan_i18n.normalize_language(code)
                caravan_i18n.clear_language_cache()
            return self._json(200, {"language": caravan_i18n.language(),
                                    "languages": caravan_i18n.picker_languages()})
        if u.path.startswith("/api/"):
            return self._json(200, {"ok": True, "mock": True})
        self.send_error(404)

def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--port", type=int, default=8191)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    H.nodes = fake_nodes(args.nodes)
    httpd = ThreadingHTTPServer((args.host, args.port), H)
    print(f"[mock-picker] {args.nodes} nodes on http://{args.host}:{args.port}/", flush=True)
    httpd.serve_forever()

if __name__ == "__main__":
    main()
