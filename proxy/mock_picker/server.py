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
            ]
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
