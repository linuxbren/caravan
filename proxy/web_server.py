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
import web_nodes  # noqa: E402

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

    def configured_nodes(self) -> list:
        """Node list from ~/.caravan/config.toml [web.nodes.*] (defaults EXO1/EXO2)."""
        return web_nodes.nodes_from_config()

    def _ssh_fn(self):
        return web_nodes.make_ssh_fn(self.mgr)

    def _nodes_refresh(self):
        try:
            cfg_nodes = self.configured_nodes()
            snap = self.mgr.snapshot()
            split = self.mgr.lead_split_info() if snap.get("status") == "ready" else None
            model = snap.get("model_name") if snap.get("status") == "ready" else None
            nodes = web_nodes.gather_all(
                cfg_nodes,
                ssh_fn=self._ssh_fn(),
                model=model,
                split=split,
            )
            # link: first packer's peer or mgr default
            peer = None
            for n in cfg_nodes:
                if n.get("role") != "lead" and n.get("peer"):
                    peer = n["peer"]
                    break
            self._nodes_cache = {
                "t": time.time(),
                "status": snap.get("status"),
                "link": (split or {}).get("peer") or peer or self.mgr.packer_peer,
                "nodes": nodes,
                "max_split_stages": web_nodes.MAX_SPLIT_STAGES,
                "configured": len(cfg_nodes),
                "online": len(web_nodes.online_nodes(nodes)),
            }
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

    def picker_kill_node(self, node: dict, repo_id: str, job=None) -> dict:
        """SIGTERM/KILL mlx_split_fetch for repo on one node (local or SSH)."""
        if not repo_id:
            return {"ok": False, "error": "no repo"}
        folder = repo_id.replace("/", "--")
        pid_file = f"/tmp/caravan-fetch-{folder}.pid"
        script = (
            "pkill -TERM -f 'mlx_split_fetch.py %s' 2>/dev/null; "
            "if [ -f %s ]; then kill -TERM $(cat %s) 2>/dev/null; fi; "
            "sleep 0.5; "
            "pkill -9 -f 'mlx_split_fetch.py %s' 2>/dev/null; "
            "if [ -f %s ]; then kill -9 $(cat %s) 2>/dev/null; rm -f %s; fi; "
            "echo KILLED"
            % (repo_id, pid_file, pid_file, repo_id, pid_file, pid_file, pid_file)
        )
        try:
            if web_nodes.is_local(node):
                import subprocess
                r = subprocess.run(["bash", "-lc", script], capture_output=True, text=True, timeout=30)
            else:
                r = self._ssh_fn()(node, script, timeout=30)
            return {
                "ok": "KILLED" in (getattr(r, "stdout", "") or ""),
                "rc": getattr(r, "returncode", -1),
                "out": (getattr(r, "stdout", "") or "")[-200:],
                "node": node.get("id") or node.get("label"),
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e), "node": node.get("id")}

    def picker_kill_all(self, repo_id: str, job=None) -> dict:
        """Kill fetch on every configured node that participates in download."""
        nodes = web_nodes.split_stage_nodes(self.configured_nodes())
        results = []
        for n in nodes:
            results.append(self.picker_kill_node(n, repo_id, job))
        return {"ok": any(r.get("ok") for r in results) or not results, "nodes": results}

    # Back-compat alias used by older cancel paths
    def picker_kill_packer(self, repo_id: str, job=None) -> dict:
        return self.picker_kill_all(repo_id, job)

    def picker_measure_node(self, node: dict, dest: str, *, repo_id: str = "",
                              prev=None) -> dict:
        """Truthful progress on a node: hook/disk/nettop (hf_xet-safe)."""
        if web_nodes.is_local(node):
            try:
                from download_progress import combine_progress
                return combine_progress(
                    dest=str(Path(dest).expanduser()),
                    repo_id=repo_id or Path(dest).name.replace("--", "/"),
                    total_bytes=(prev or {}).get("total_bytes"),
                    pid=(prev or {}).get("pid"),
                    prev=prev,
                )
            except Exception:
                pass
        remote = (
            "import json,sys,re,subprocess\n"
            "from pathlib import Path\n"
            "dest=sys.argv[1]; repo=sys.argv[2] if len(sys.argv)>2 else ''\n"
            "baseline=int(sys.argv[3]) if len(sys.argv)>3 and str(sys.argv[3]).isdigit() else None\n"
            "d=Path(dest).expanduser()\n"
            "done=inc=n=xet=0\n"
            "if d.exists():\n"
            "  for p in d.glob('*.safetensors'):\n"
            "    try: done+=p.stat().st_size\n"
            "    except OSError: pass\n"
            "  c=d/'.cache'/'huggingface'/'download'\n"
            "  if c.is_dir():\n"
            "    for p in c.rglob('*'):\n"
            "      if p.is_file() and p.name.endswith('.incomplete'):\n"
            "        try:\n"
            "          inc+=p.stat().st_size; n+=1\n"
            "        except OSError: pass\n"
            "  x=d/'.cache'/'huggingface'/'xet'\n"
            "  if x.is_dir():\n"
            "    for p in x.rglob('*'):\n"
            "      if p.is_file():\n"
            "        try: xet+=p.stat().st_size\n"
            "        except OSError: pass\n"
            "have=done+inc\n"
            "if have < 1000000 and xet > have: have=xet\n"
            "hook_have=None\n"
            "folder=(repo or d.name).replace('/','--')\n"
            "hp=Path('/tmp')/('caravan-progress-%s.jsonl'%folder)\n"
            "if hp.is_file():\n"
            "  try:\n"
            "    lines=hp.read_text().strip().splitlines()\n"
            "    if lines:\n"
            "      blob=json.loads(lines[-1]); hook_have=int(blob.get('have_bytes') or 0)\n"
            "  except Exception: pass\n"
            "net_raw=None; pid=None\n"
            "try:\n"
            "  pat=('mlx_split_fetch.py %s'%repo) if repo else 'mlx_split_fetch.py'\n"
            "  r=subprocess.run(['pgrep','-f',pat],capture_output=True,text=True,timeout=3)\n"
            "  pids=[int(x) for x in (r.stdout or '').split() if x.strip().isdigit()]\n"
            "  for pid in pids:\n"
            "    r2=subprocess.run(['nettop','-P','-L','1','-p',str(pid),'-J','bytes_in'],\n"
            "                      capture_output=True,text=True,timeout=4)\n"
            "    nums=re.findall(r'\\d+', (r2.stdout or '').replace(',',''))\n"
            "    if nums:\n"
            "      net_raw=max(int(x) for x in nums); break\n"
            "except Exception:\n"
            "  pass\n"
            "net_have=None\n"
            "if net_raw is not None:\n"
            "  if baseline is None: baseline=net_raw\n"
            "  net_have=max(0, net_raw-int(baseline))\n"
            "source='starting'; out_have=0\n"
            "if hook_have: out_have=hook_have; source='hook'\n"
            "elif inc>0 or done>0: out_have=have; source='disk'\n"
            "elif net_have and net_have>0: out_have=net_have; source='nettop'\n"
            "elif have>0: out_have=have; source='disk'\n"
            "print(json.dumps({'have_bytes':out_have,'n_incomplete':n,'done_bytes':done,"
            "'source':source,'pid':pid,'net_raw':net_raw,'net_baseline':baseline,"
            "'disk_have':have,'xet_bytes':xet}))\n"
        )
        try:
            import subprocess
            dest_q = dest if not web_nodes.is_local(node) else str(Path(dest).expanduser())
            base = ""
            if prev and prev.get("net_baseline") is not None:
                base = str(int(prev["net_baseline"]))
            if web_nodes.is_local(node):
                r = subprocess.run(
                    [sys.executable, "-c", remote, dest_q, repo_id or "", base],
                    capture_output=True, text=True, timeout=25,
                )
            else:
                script = "python3 -c %s %s %s %s" % (
                    repr(remote), repr(dest), repr(repo_id or ""), repr(base),
                )
                r = self._ssh_fn()(node, script, timeout=25)
            line = (getattr(r, "stdout", "") or "").strip().splitlines()
            if not line:
                return {"have_bytes": 0, "n_incomplete": 0, "source": "starting"}
            return json.loads(line[-1])
        except Exception:
            return {"have_bytes": 0, "n_incomplete": 0, "source": "starting"}

    def picker_measure_packer(self, dest: str) -> dict:
        """Back-compat: measure default packer (first non-lead configured node)."""
        nodes = self.configured_nodes()
        pack = next((n for n in nodes if n.get("role") != "lead"), None)
        if not pack:
            return {"have_bytes": 0, "n_incomplete": 0}
        return self.picker_measure_node(pack, dest)


    def list_orphan_fetch_jobs(self) -> list:
        """Progress for mlx_split_fetch processes not tracked in web_picker jobs.

        Used so a web restart still shows truthful progress for an in-flight
        download (e.g. JevK5) via hook/disk/nettop.
        """
        import re
        import subprocess
        known = {(j.get("repo_id") or "") for j in web_picker.list_jobs()
                 if j.get("status") in ("queued", "running", "cancelling")}
        found = {}  # repo -> {node_id: snap}
        cfg = self.configured_nodes()

        def scan_local():
            try:
                r = subprocess.run(
                    ["ps", "-ax", "-o", "pid=,command="],
                    capture_output=True, text=True, timeout=5,
                )
            except Exception:
                return
            for line in (r.stdout or "").splitlines():
                # pid ... python ... mlx_split_fetch.py REPO DEST --role ...
                m = re.search(r"(\d+).*mlx_split_fetch\.py\s+(\S+)\s+(\S+)", line)
                if not m:
                    continue
                pid, repo, dest = int(m.group(1)), m.group(2), m.group(3)
                if repo in known:
                    continue
                local = next((n for n in cfg if web_nodes.is_local(n)), cfg[0] if cfg else {"id": "local", "label": "local", "role": "lead"})
                nid = local.get("id") or "local"
                snap = self.picker_measure_node(local, dest, repo_id=repo)
                snap["label"] = local.get("label") or nid
                snap["role"] = local.get("role") or "lead"
                snap["pid"] = pid
                found.setdefault(repo, {})[nid] = {"dest": dest, "snap": snap, "node": local}

        def scan_remote(n):
            try:
                r = self._ssh_fn()(n, "ps -ax -o pid=,command= | grep mlx_split_fetch.py | grep -v grep || true", timeout=10)
            except Exception:
                return
            for line in (getattr(r, "stdout", "") or "").splitlines():
                m = re.search(r"(\d+).*mlx_split_fetch\.py\s+(\S+)\s+(\S+)", line)
                if not m:
                    continue
                pid, repo, dest = int(m.group(1)), m.group(2), m.group(3)
                if repo in known:
                    continue
                nid = n.get("id") or n.get("label")
                snap = self.picker_measure_node(n, dest, repo_id=repo)
                snap["label"] = n.get("label") or nid
                snap["role"] = n.get("role") or "packer"
                snap["pid"] = pid
                found.setdefault(repo, {})[nid] = {"dest": dest, "snap": snap, "node": n}

        scan_local()
        for n in cfg:
            if not web_nodes.is_local(n):
                scan_remote(n)

        jobs = []
        for repo, nodes in found.items():
            progress = {}
            runners = []
            for nid, info in nodes.items():
                progress[nid] = info["snap"]
                runners.append({
                    "id": nid,
                    "label": info["snap"].get("label") or nid,
                    "role": info["snap"].get("role"),
                    "dest": info["dest"],
                })
            # Best-effort total for % / ETA (sizes file, else HF blob estimate)
            total_b = None
            try:
                est = self.picker_role_totals(repo, 24, n_stages=1)
                total_b = est.get("full") or est.get("lead")
            except Exception:
                total_b = None
            for info in nodes.values():
                sizes_p = Path(str(info.get("dest") or "")).expanduser() / "caravan-split-sizes.json"
                if sizes_p.is_file():
                    try:
                        import json as _json
                        blob = _json.loads(sizes_p.read_text())
                        total_b = sum(int(v) for v in (blob.get("sizes") or {}).values())
                        if total_b:
                            break
                    except Exception:
                        pass
            if total_b:
                for nid, snap in progress.items():
                    if isinstance(snap, dict) and not snap.get("total_bytes"):
                        snap["total_bytes"] = total_b
                        have = int(snap.get("have_bytes") or 0)
                        if have > 0 and total_b > 0:
                            snap["pct"] = max(0, min(99, int(have * 100 / total_b)))
                            # refresh msg with total
                            mb_s = float(snap.get("mb_s") or 0)
                            have_gb = have / 1e9
                            total_gb = total_b / 1e9
                            msg = f"{have_gb:.2f}/{total_gb:.2f} GB · {mb_s:.1f} MB/s"
                            if snap.get("n_incomplete"):
                                msg += f" · {snap['n_incomplete']} active"
                            if snap.get("source") == "nettop":
                                msg += " · via network"
                            if snap.get("stalled"):
                                msg += " · stalled?"
                            snap["msg"] = msg
            jobs.append({
                "id": "live-" + repo.replace("/", "--")[:24],
                "status": "running",
                "repo_id": repo,
                "progress": progress,
                "runners": runners,
                "orphan": True,
                "totals": {nid: total_b for nid in progress} if total_b else {},
                "note": "adopted live fetch (web restarted or started outside UI)",
            })
        return jobs

    def picker_role_totals(self, repo_id: str, packer_layers: int, n_stages: int = 2) -> dict:
        """Fast per-role byte estimate from HF blobs; refined by fetch JSON later."""
        out = {"lead": None, "packer": None, "by_id": {}}
        try:
            info = web_picker._fetch_repo_blobs(repo_id)
            full = int(info.get("weight_bytes") or 0)
            if full and n_stages >= 1:
                # Rough equal split across stages until fetch plan reports my_gb.
                each = full // max(1, n_stages)
                rem = full - each * (n_stages - 1) if n_stages > 1 else full
                out["lead"] = rem if n_stages == 1 else each
                out["packer"] = rem if n_stages > 1 else None
                out["each"] = each
                out["full"] = full
        except Exception:
            pass
        return out

    def picker_disk_blob(self, node: dict) -> dict:
        """Run picker_disk_sizes.py on one node."""
        try:
            if web_nodes.is_local(node):
                import subprocess
                py = str(Path(self.mgr.repo) / "proxy" / "picker_disk_sizes.py")
                r = subprocess.run(
                    [sys.executable, py], capture_output=True, text=True, timeout=90,
                )
            else:
                repo = (node.get("repo") or "~/cv3").rstrip("/")
                r = self._ssh_fn()(node, f"python3 {repo}/proxy/picker_disk_sizes.py", timeout=90)
            if getattr(r, "returncode", 1) == 0 and (getattr(r, "stdout", "") or "").strip():
                return json.loads(r.stdout.strip().splitlines()[-1])
            return {"models": {}, "cleanup": {}, "_error": (getattr(r, "stderr", "") or "")[-200:]}
        except Exception as e:  # noqa: BLE001
            return {"models": {}, "cleanup": {}, "_error": str(e)}



    def gather_model_inventories(self) -> list:
        """Per configured node: MLX tree completeness (local + SSH)."""
        import concurrent.futures
        cfg_nodes = self.configured_nodes()

        def one(n):
            nid = n.get("id") or n.get("label")
            label = n.get("label") or nid
            role = n.get("role") or "packer"
            models, err = {}, None
            try:
                if web_nodes.is_local(n):
                    import model_inventory as inv
                    models = (inv.inventory_payload().get("models") or {})
                else:
                    repo = (n.get("repo") or "~/cv3").rstrip("/")
                    r = self._ssh_fn()(
                        n,
                        f"python3 {repo}/proxy/picker_disk_sizes.py --inventory",
                        timeout=25,
                    )
                    if getattr(r, "returncode", 1) == 0 and (getattr(r, "stdout", "") or "").strip():
                        blob = json.loads(r.stdout.strip().splitlines()[-1])
                        models = blob.get("models") or {}
                    else:
                        err = (getattr(r, "stderr", "") or getattr(r, "stdout", "") or "ssh inventory failed")[-200:]
            except Exception as e:  # noqa: BLE001
                err = str(e)
            if isinstance(models, dict) and "_error" in models:
                err = models.pop("_error", err)
            return {
                "id": nid, "label": label, "role": role,
                "models": {k: v for k, v in (models or {}).items() if k != "_error"},
                "error": err,
            }

        out = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(cfg_nodes))) as pool:
            futs = [pool.submit(one, n) for n in cfg_nodes]
            for f in concurrent.futures.as_completed(futs, timeout=40):
                try:
                    out.append(f.result())
                except Exception as e:  # noqa: BLE001
                    out.append({"id": "?", "label": "?", "role": "packer", "models": {}, "error": str(e)})
        # stable order: lead first
        out.sort(key=lambda r: (0 if r.get("role") == "lead" else 1, r.get("id") or ""))
        return out

    def list_loadable_models(self) -> list:
        """Settings dropdown: disk-backed usable MLX models (N-node aware)."""
        snap = self.mgr.snapshot()
        current = snap.get("model_id")
        # Prefer HF id if present on snap
        current_hf = snap.get("model_hf") or None
        live = (self.nodes() or {}).get("nodes") or []
        invs = self.gather_model_inventories()
        return catalog.build_entries_from_inventories(
            node_inventories=invs,
            nodes=live or self.configured_nodes(),
            current_id=current,
            current_hf=current_hf,
            fit_nodes=[n for n in live if isinstance(n, dict) and not n.get("offline") and not n.get("error")],
            max_split_stages=web_nodes.MAX_SPLIT_STAGES,
            include_unusable=True,
        )



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
                models = app.list_loadable_models()
                snap = app.mgr.snapshot()
                return self._json(200, {
                    "models": models,
                    "current": snap.get("model_id"),
                    "source": "disk",
                    "max_split_stages": web_nodes.MAX_SPLIT_STAGES,
                })
            if path == "/api/optimize":
                return self._json(200, app.optimizer.snapshot())
            if path == "/api/journey":
                return self._json(200, load_journey())
            if path == "/api/split":
                snap = app.mgr.snapshot()
                info = app.mgr.lead_split_info() if snap.get("status") == "ready" else None
                return self._json(200, {"worker": snap, "split": info})
            if path == "/api/settings":
                return self._api_settings()
            if path == "/api/hf-token":
                return self._api_hf_token_get()
            if path == "/api/picker/search":
                return self._api_picker_search()
            if path == "/api/picker/disk":
                return self._api_picker_disk()
            if path == "/api/picker/jobs":
                return self._json(200, {"jobs": web_picker.list_jobs() + app.list_orphan_fetch_jobs()})
            if path.startswith("/api/picker/jobs/"):
                jid = path.rsplit("/", 1)[-1]
                job = web_picker.get_job(jid)
                if not job:
                    for oj in app.list_orphan_fetch_jobs():
                        if oj.get("id") == jid:
                            job = oj
                            break
                return self._json(200 if job else 404, job or {"error": "not found"})
            if path == "/api/picker/live-fetches":
                return self._json(200, {"jobs": app.list_orphan_fetch_jobs()})
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
                return self._json(200, web_picker.cancel_job(jid, kill_procs=app.picker_kill_all))
            if path == "/api/picker/delete":
                return self._api_picker_delete(body=body)
            if path == "/api/picker/fit":
                return self._api_picker_fit(body=body)
            if path == "/api/picker/placement":
                return self._api_picker_placement(body=body)
            if path == "/api/hf-token":
                return self._api_hf_token_set(body=body)
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
            try:
                from hf_auth import token_status
                hf = token_status()
            except Exception:
                hf = {"configured": False, "source": None}
            return self._json(200, {"options": web_settings.OPTIONS,
                                   "current": snap.get("page_settings") or snap.get("settings"),
                                   "file": {"path": cfg["path"], "exists": cfg["exists"],
                                            "errors": cfg["errors"], "model": mid, "pins": fsets},
                                   "from_file_loaded": snap.get("from_file") or {},
                                   "hf_token": hf})


        def _api_picker_search(self):
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            q = (qs.get("q") or qs.get("query") or [""])[0]
            source = (qs.get("source") or ["all"])[0]
            filt = (qs.get("filter") or qs.get("filt") or [""])[0]
            newer = (qs.get("newer") or qs.get("new") or ["0"])[0] in ("1", "true", "yes")
            try:
                limit = int((qs.get("limit") or ["30"])[0])
            except ValueError:
                limit = 30
            cat = web_picker.search_catalog(q, source=source, limit=limit, filt=filt, newer=newer)
            raw = app.nodes() or {}
            nodes = raw.get("nodes") or []
            online = [n for n in nodes if isinstance(n, dict) and not n.get("offline") and not n.get("error")]
            cat["groups"] = web_picker.attach_fit(cat.get("groups") or [], online)
            cat["nodes_used"] = len(online)
            cat["nodes_configured"] = len(nodes)
            cat["max_split_stages"] = web_nodes.MAX_SPLIT_STAGES
            cat["node_labels"] = [n.get("label") or n.get("id") for n in online]
            return self._json(200, cat)

        def _api_picker_disk(self):
            current = app.mgr.snapshot().get("model_id")
            cfg_nodes = app.configured_nodes()
            # Gather disk blobs for every configured node (local + SSH).
            blobs = {}
            for n in cfg_nodes:
                nid = n.get("id") or n.get("label")
                blobs[nid] = app.picker_disk_blob(n)

            by_id = {}
            models = []
            for n in cfg_nodes:
                nid = n.get("id") or n.get("label")
                role = n.get("role") or "packer"
                label = n.get("label") or nid
                blob = blobs.get(nid) or {}
                for rid, gb in (blob.get("models") or {}).items():
                    e = by_id.get(rid)
                    if e is None:
                        e = {
                            "id": rid, "name": rid.split("/")[-1], "source": "hf-mlx",
                            "paths": {}, "size_gb": {}, "size_by_label": {},
                        }
                        models.append(e)
                        by_id[rid] = e
                    e.setdefault("size_gb", {})[role if role == "lead" else nid] = gb
                    # keep legacy lead/packer keys for 2-Mini UI
                    if role == "lead":
                        e["size_gb"]["lead"] = gb
                    else:
                        # first packer also fills "packer"
                        e["size_gb"].setdefault("packer", gb)
                        e["size_gb"][nid] = gb
                    e.setdefault("size_by_label", {})[label] = gb

            # Also include any lead-local walk via list_installed for completeness
            first_pack = next((blobs[n.get("id") or n.get("label")].get("models") or {}
                               for n in cfg_nodes if n.get("role") != "lead"), {})
            try:
                walked = web_picker.list_installed(packer_sizes=first_pack)
                for m in walked:
                    e = by_id.setdefault(m["id"], m)
                    if e not in models:
                        models.append(e)
                    for k, v in (m.get("size_gb") or {}).items():
                        e.setdefault("size_gb", {}).setdefault(k, v)
            except Exception:
                pass

            # Cleanup: merge across nodes
            cleanup_kinds = ("hf-cache", "drafts")
            cleanup = []
            for kind in cleanup_kinds:
                sizes = {}
                sizes_by_label = {}
                for n in cfg_nodes:
                    nid = n.get("id") or n.get("label")
                    label = n.get("label") or nid
                    role = n.get("role") or "packer"
                    c = (blobs.get(nid) or {}).get("cleanup") or {}
                    gb = c.get(kind)
                    if gb is None:
                        continue
                    sizes[nid] = gb
                    sizes_by_label[label] = gb
                    if role == "lead":
                        sizes["lead"] = gb
                    else:
                        sizes.setdefault("packer", gb)
                if any(isinstance(v, (int, float)) and v > 0 for v in sizes.values()):
                    cleanup.append({
                        "id": f"cleanup:{kind}",
                        "kind": kind,
                        "name": "HF download cache" if kind == "hf-cache" else "Guess-ahead drafts",
                        "note": "Shared Hugging Face cache" if kind == "hf-cache"
                                else "Helper models used for guess-ahead",
                        "size_gb": sizes,
                        "size_by_label": sizes_by_label,
                    })

            # Attach placement + held_on from inventories when available
            try:
                invs = app.gather_model_inventories()
                place_by = {}
                held_by = {}
                for ni in invs:
                    label = ni.get("label") or ni.get("id")
                    for rid, st in (ni.get("models") or {}).items():
                        held_by.setdefault(rid, []).append(label)
                        if st.get("placement") and rid not in place_by:
                            place_by[rid] = st["placement"]
                for e in models:
                    rid = e.get("id")
                    e["held_on"] = held_by.get(rid) or list((e.get("size_by_label") or {}).keys())
                    if rid in place_by:
                        e["placement"] = place_by[rid]
            except Exception:
                pass

            return self._json(200, {
                "models": sorted(models, key=lambda x: x["name"].lower()),
                "cleanup": cleanup,
                "nodes": [
                    {"id": n.get("id"), "label": n.get("label"), "role": n.get("role"),
                     "blob": {k: blobs.get(n.get("id") or n.get("label"), {}).get(k)
                              for k in ("models", "cleanup", "_error")}}
                    for n in cfg_nodes
                ],
                "current": current,
                "max_split_stages": web_nodes.MAX_SPLIT_STAGES,
            })

        def _api_picker_delete(self, body=None):
            body = body or {}
            rid = body.get("id") or body.get("repo_id") or body.get("kind") or ""
            kind = (body.get("kind") or "").strip().lower()
            if not body.get("confirm"):
                return self._json(400, {"error": "confirm=true required"})
            current = app.mgr.snapshot().get("model_id")
            cfg_nodes = app.configured_nodes()

            if kind in ("hf-cache", "drafts") or str(rid).startswith("cleanup:"):
                k = kind or str(rid).split(":", 1)[-1]
                results = []
                for n in cfg_nodes:
                    kn = "hf-cache" if k in ("hf-cache", "hf_cache", "cache") else "drafts"
                    cur = (current or "").replace("'", "")
                    try:
                        if web_nodes.is_local(n):
                            import subprocess
                            py = str(Path(app.mgr.repo) / "proxy" / "picker_disk_sizes.py")
                            r = subprocess.run(
                                [sys.executable, py, "--delete", kn, "--current", cur],
                                capture_output=True, text=True, timeout=300,
                            )
                        else:
                            repo = (n.get("repo") or "~/cv3").rstrip("/")
                            script = (
                                "python3 %s/proxy/picker_disk_sizes.py --delete %s --current %s"
                                % (repo, kn, cur)
                            )
                            r = app._ssh_fn()(n, script, timeout=300)
                        try:
                            blob = json.loads((r.stdout or "").strip().splitlines()[-1])
                        except Exception:
                            blob = {"ok": False, "raw": (getattr(r, "stdout", "") or "")[-200:]}
                        blob["rc"] = getattr(r, "returncode", -1)
                        blob["node"] = n.get("id") or n.get("label")
                        results.append(blob)
                    except Exception as e:  # noqa: BLE001
                        results.append({"ok": False, "error": str(e), "node": n.get("id")})
                ok = any(r.get("ok") for r in results)
                return self._json(200 if ok else 400, {"ok": ok, "kind": k, "nodes": results})

            # Stop any running fetch for this model BEFORE deleting folders.
            stopped = web_picker.stop_jobs_for_repo(rid, kill_procs=app.picker_kill_all)

            def ssh_delete(folder):
                # Delete on every non-local node
                outs = []
                for n in cfg_nodes:
                    if web_nodes.is_local(n):
                        continue
                    repo = (n.get("repo") or "~/cv3").rstrip("/")
                    r = app._ssh_fn()(n,
                        "pkill -f 'mlx_split_fetch.py %s' 2>/dev/null; sleep 0.5; "
                        "pkill -9 -f 'mlx_split_fetch.py %s' 2>/dev/null; "
                        "rm -rf ~/.caravan/mlx-models/%s ~/.exo/models/%s; echo REMOVED"
                        % (rid, rid, folder, folder),
                        timeout=120,
                    )
                    outs.append({
                        "node": n.get("id"),
                        "removed": "REMOVED" in (getattr(r, "stdout", "") or ""),
                        "rc": getattr(r, "returncode", -1),
                    })
                return {"removed": any(o.get("removed") for o in outs), "nodes": outs,
                        "rc": 0 if any(o.get("removed") for o in outs) else 1}

            out = web_picker.delete_model(
                rid, current_model_id=current, ssh_delete=ssh_delete,
            )
            out["stopped_jobs"] = stopped
            return self._json(200 if out.get("ok") else 400, out)

        def _api_hf_token_get(self):
            try:
                from hf_auth import token_status
                return self._json(200, token_status())
            except Exception as e:
                return self._json(500, {"error": str(e), "configured": False})

        def _api_hf_token_set(self, body=None):
            """Store or clear HF token on each Mini. Never echoes the secret."""
            body = body or {}
            try:
                from hf_auth import save_caravan_token, clear_caravan_token
            except Exception as e:
                return self._json(500, {"error": str(e)})
            clear = bool(body.get("clear") or body.get("token") == "")
            tok = "" if clear else (body.get("token") or "").strip()
            if not clear and not tok:
                return self._json(400, {"error": "token required (or clear:true)"})
            st = clear_caravan_token() if clear else save_caravan_token(tok)
            nodes_out = [{"node": "local", "ok": True}]
            for n in app.configured_nodes():
                if web_nodes.is_local(n):
                    continue
                try:
                    if clear:
                        r = app._ssh_fn()(n, "rm -f ~/.caravan/hf_token; echo DONE", timeout=20)
                    else:
                        import base64
                        b64 = base64.b64encode(tok.encode()).decode()
                        py = (
                            "import pathlib,base64; "
                            "p=pathlib.Path.home()/'.caravan'/'hf_token'; "
                            "p.parent.mkdir(parents=True, exist_ok=True); "
                            "p.write_bytes(base64.b64decode('%s')); "
                            "p.chmod(0o600)"
                        ) % b64
                        r = app._ssh_fn()(
                            n,
                            "mkdir -p ~/.caravan && umask 077 && python3 -c %s && echo DONE"
                            % repr(py),
                            timeout=20,
                        )
                    nodes_out.append({
                        "node": n.get("id"),
                        "ok": "DONE" in (getattr(r, "stdout", "") or ""),
                    })
                except Exception as e:
                    nodes_out.append({"node": n.get("id"), "ok": False, "error": str(e)})
            return self._json(200, {**st, "nodes": nodes_out})

        def _api_picker_placement(self, body=None):
            body = body or {}
            nodes = (app.nodes() or {}).get("nodes") or []
            online = [n for n in nodes if isinstance(n, dict) and not n.get("offline") and not n.get("error")]
            if not online:
                online = app.configured_nodes()
            weights = float(body.get("weights_gb") or 0)
            fit = web_picker.fit_check(
                weights_gb=weights,
                nodes=online,
                cfg=body.get("cfg"),
                n_layers=body.get("n_layers"),
                ctx_tokens=int(body.get("ctx_tokens") or web_picker.DEFAULT_CTX),
                split_ok=bool(body.get("split_ok", True)),
                max_split_stages=web_nodes.MAX_SPLIT_STAGES,
            )
            from placement import placement_options
            opts = placement_options(
                fit=fit, nodes=online,
                max_split_stages=web_nodes.MAX_SPLIT_STAGES,
                weights_gb=weights,
            )
            return self._json(200, {"fit": fit, **opts})

        def _api_picker_fit(self, body=None):
            body = body or {}
            nodes = (app.nodes() or {}).get("nodes") or []
            online = [n for n in nodes if isinstance(n, dict) and not n.get("offline") and not n.get("error")]
            fit = web_picker.fit_check(
                weights_gb=float(body.get("weights_gb") or 0),
                nodes=online,
                cfg=body.get("cfg"),
                n_layers=body.get("n_layers"),
                ctx_tokens=int(body.get("ctx_tokens") or web_picker.DEFAULT_CTX),
                split_ok=bool(body.get("split_ok", True)),
                max_split_stages=web_nodes.MAX_SPLIT_STAGES,
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
                packer_layers = int(packer_layers) if packer_layers is not None else 24
            except (TypeError, ValueError):
                packer_layers = 24

            live = (app.nodes() or {}).get("nodes") or []
            online = [n for n in live if isinstance(n, dict) and not n.get("offline") and not n.get("error")]
            if not online:
                online = app.configured_nodes()
            cfg_by_id = {(n.get("id") or n.get("label")): n for n in (live or app.configured_nodes())}
            for n in app.configured_nodes():
                cfg_by_id.setdefault(n.get("id") or n.get("label"), n)

            weights = float(body.get("weights_gb") or 0)
            if not weights:
                try:
                    info = web_picker._fetch_repo_blobs(repo)
                    weights = float(info.get("weight_bytes") or 0) / 1e9
                except Exception:
                    weights = 0.0
            fit = web_picker.fit_check(
                weights_gb=weights, nodes=online, split_ok=True,
                max_split_stages=web_nodes.MAX_SPLIT_STAGES,
            )
            from placement import placement_options, resolve_option
            opts = placement_options(
                fit=fit, nodes=online,
                max_split_stages=web_nodes.MAX_SPLIT_STAGES,
                weights_gb=weights,
            )
            place = resolve_option(opts, body=body)
            if not place:
                return self._json(400, {"error": "no placement option available", "options": opts})
            if not place.get("enabled"):
                return self._json(400, {
                    "error": place.get("reason") or "placement disabled",
                    "placement": place, "options": opts,
                })

            mode = place.get("mode") or "split"
            full_copy = bool(place.get("full_copy"))
            target_ids = list(place.get("node_ids") or [])
            target_nodes = []
            for tid in target_ids:
                n = cfg_by_id.get(tid)
                if n:
                    target_nodes.append(n)
            if not target_nodes:
                return self._json(400, {"error": "placement nodes not found", "placement": place})

            n_stages = len(target_nodes) if mode == "split" else 1
            note = place.get("label") or ""
            if mode == "split" and len(target_nodes) > web_nodes.MAX_SPLIT_STAGES:
                note = (
                    f"{len(target_nodes)}-Mini split coming later; "
                    f"downloading for {web_nodes.MAX_SPLIT_STAGES}-stage runtime"
                )
                target_nodes = target_nodes[: web_nodes.MAX_SPLIT_STAGES]
                n_stages = len(target_nodes)

            totals = app.picker_role_totals(repo, packer_layers, n_stages=max(1, n_stages))
            if full_copy:
                # Full model bytes for each target
                full = totals.get("full") or totals.get("lead")
                totals = {"lead": full, "packer": full, "each": full, "full": full}
            folder = repo.replace("/", "--")

            def fetch_role_for(node):
                if full_copy:
                    return "all"
                return "lead" if node.get("role") == "lead" else "packer"

            def make_run_local(node):
                role = fetch_role_for(node)
                def run_local(repo_id, dest, pk, prog):
                    import subprocess
                    dest_q = str(Path(dest).expanduser())
                    Path(dest_q).mkdir(parents=True, exist_ok=True)
                    py = str(Path("~/.caravan/venvs/mlx/bin/python").expanduser())
                    fetch = str(Path(app.mgr.repo) / "agent" / "mlx_split_fetch.py")
                    cmd = [py, fetch, repo_id, dest_q, "--role", role]
                    if pk and role != "all":
                        cmd += ["--packer-layers", str(int(pk))]
                    prog(1, f"starting {node.get('label') or node.get('id')} fetch ({role})")
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    )
                    for j in web_picker.list_jobs():
                        if j.get("repo_id") == repo_id and j.get("status") == "running":
                            web_picker._job_set(j["id"], lead_proc=proc)
                            break
                    out_lines = []
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        out_lines.append(line)
                        if len(out_lines) == 1:
                            try:
                                rep = json.loads(line.strip())
                                if isinstance(rep, dict) and rep.get("my_gb"):
                                    for j in web_picker.list_jobs():
                                        if j.get("repo_id") == repo_id and j.get("status") == "running":
                                            nid = node.get("id") or node.get("label")
                                            totals_now = dict(j.get("totals") or {})
                                            totals_now[nid] = int(float(rep["my_gb"]) * 1e9)
                                            web_picker._job_set(j["id"], totals=totals_now,
                                                               total_bytes_lead=totals_now[nid])
                                            break
                            except (ValueError, TypeError):
                                pass
                    rc = proc.wait()
                    if rc != 0:
                        blob = "".join(out_lines)[-500:]
                        raise RuntimeError(blob or f"{role} download failed")
                    prog(100, "done")
                return run_local

            def make_run_remote(node):
                role = fetch_role_for(node)
                def run_remote(repo_id, dest, pk, prog):
                    dest_q = dest.replace("'", "").replace(";", "")
                    pid_file = f"/tmp/caravan-fetch-{repo_id.replace('/', '--')}.pid"
                    repo_path = (node.get("repo") or "~/cv3").rstrip("/")
                    script = (
                        "mkdir -p %s; rm -f %s; "
                        "( ~/.caravan/venvs/mlx/bin/python %s/agent/mlx_split_fetch.py "
                        "%s %s --role %s "
                        % (dest_q, pid_file, repo_path, repo_id, dest_q, role)
                    )
                    if pk and role != "all":
                        script += "--packer-layers %d " % int(pk)
                    script += (
                        "> /tmp/caravan-fetch-%s.log 2>&1 & echo $! > %s; echo FETCH_STARTED )"
                        % (node.get("id") or "node", pid_file)
                    )
                    prog(1, f"starting {node.get('label') or node.get('id')} fetch ({role})")
                    r = app._ssh_fn()(node, script, timeout=60)
                    if r.returncode != 0 or "FETCH_STARTED" not in (r.stdout or ""):
                        raise RuntimeError((r.stderr or r.stdout or "remote start failed")[-400:])
                    import time as _t
                    while True:
                        for j in web_picker.list_jobs():
                            if j.get("repo_id") == repo_id and j.get("cancel"):
                                app.picker_kill_node(node, repo_id, j)
                                raise RuntimeError("cancelled")
                        check = app._ssh_fn()(node,
                            "if [ -f %s ]; then pid=$(cat %s); "
                            "if kill -0 $pid 2>/dev/null; then echo RUNNING; "
                            "else echo DONE; fi; else echo DONE; fi" % (pid_file, pid_file),
                            timeout=30,
                        )
                        st = (check.stdout or "").strip().splitlines()
                        last = st[-1] if st else "DONE"
                        if last == "DONE":
                            break
                        _t.sleep(1.5)
                    prog(100, "done")
                return run_remote

            runners = []
            prev_state = {}
            for i, n in enumerate(target_nodes):
                nid = n.get("id") or n.get("label") or f"n{i}"
                role = n.get("role") or ("lead" if i == 0 else "packer")
                if web_nodes.is_local(n):
                    dest = str(Path("~/.caravan/mlx-models").expanduser() / folder)
                    if role == "lead" and web_picker.MLX_MODEL_ROOTS:
                        dest = str(web_picker.MLX_MODEL_ROOTS[0] / folder)
                    run = make_run_local(n)
                    def _mk_local_measure(nn, dd, rid=repo, key=nid):
                        def _m():
                            prev = prev_state.get(key)
                            snap = app.picker_measure_node(nn, dd, repo_id=rid, prev=prev)
                            prev_state[key] = snap
                            return snap
                        return _m
                    measure = _mk_local_measure(n, dest)
                else:
                    dest = "~/.caravan/mlx-models/%s" % folder
                    run = make_run_remote(n)
                    def _mk_measure(nn, dd, rid=repo, key=nid):
                        def _m():
                            prev = prev_state.get(key)
                            snap = app.picker_measure_node(nn, dd, repo_id=rid, prev=prev)
                            prev_state[key] = snap
                            return snap
                        return _m
                    measure = _mk_measure(n, dest)
                tb = totals.get("each") if full_copy else (
                    totals.get("lead") if role == "lead" else totals.get("packer")
                )
                if tb is None:
                    tb = totals.get("each") or totals.get("full")
                runners.append({
                    "id": nid,
                    "label": n.get("label") or nid,
                    "role": role,
                    "dest": dest,
                    "run": run,
                    "measure": measure,
                    "total_bytes": tb,
                })

            job = web_picker.start_download(
                repo,
                packer_layers=packer_layers,
                runners=runners,
                note=note,
                placement=place,
                total_bytes_lead=totals.get("lead"),
                total_bytes_packer=totals.get("packer"),
            )
            return self._json(200, {
                "job": job,
                "totals": totals,
                "stages": len(runners),
                "max_split_stages": web_nodes.MAX_SPLIT_STAGES,
                "note": note,
                "placement": place,
                "nodes": [{"id": r["id"], "label": r["label"], "role": r["role"]} for r in runners],
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
        keep = os.environ.get("CARAVAN_WEB_KEEP_WORKERS", "").strip() in ("1", "true", "yes")
        if keep:
            print("[caravan-web] shutting down; keeping workers (CARAVAN_WEB_KEEP_WORKERS=1)", flush=True)
        else:
            print("[caravan-web] shutting down; stopping test workers", flush=True)
            try:
                mgr.stop(reason="web-server exit")
            except Exception as e:
                print(f"[caravan-web] stop warn: {e}", flush=True)
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
