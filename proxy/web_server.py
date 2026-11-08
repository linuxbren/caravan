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
import http.client
import json
import os
import shlex
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
from web_workers import WorkerManager, ManagedServiceError  # noqa: E402
import web_optimize  # noqa: E402
import web_picker  # noqa: E402
import web_nodes  # noqa: E402
import web_alert  # noqa: E402
import web_gguf_optimize  # noqa: E402

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
        self.mlx_optimizer = web_optimize.Optimizer(mgr, inflight=lambda: self._inflight)
        self.gguf_optimizer = web_gguf_optimize.GgufOptimizer(mgr, inflight=lambda: self._inflight)
        self.optimizer = self.mlx_optimizer

    # ---- ROADMAP #14: live node view (GET /api/nodes) -------------------
    NODES_TTL = 0.4

    def nodes(self) -> dict:
        """Cached ~400ms; refreshed in the background so polls stay fast."""
        try:
            key = self._nodes_key(self.mgr.snapshot())
        except Exception:
            key = None
        with self._nodes_lock:
            c = self._nodes_cache
            changed = c is not None and key is not None and c.get("key") != key
            stale = c is None or changed or time.time() - c["t"] > self.NODES_TTL
            if stale and not self._nodes_busy:
                self._nodes_busy = True
                threading.Thread(target=self._nodes_refresh, daemon=True).start()
        if changed:
            # Model/mode changed since last gather: wait for a fresh one so
            # the per-node model label doesn't lag a gather behind.
            for _ in range(50):
                time.sleep(0.1)
                cc = self._nodes_cache
                if cc is not None and cc.get("key") == key:
                    return cc
        if c is None:
            # First call: wait for the first gather.
            for _ in range(150):
                time.sleep(0.1)
                if self._nodes_cache is not None:
                    break
            c = self._nodes_cache or {"t": time.time(), "nodes": [], "error": "gathering"}
        return c

    def balance(self, body, *, fresh=False):
        """Read-only preview. Client supplies counts/IDs, never RAM or file claims."""
        import split_balance as SB
        if not isinstance(body, dict):
            raise ValueError("Balance request must be an object")
        mid = body.get("model_id") or self.mgr.snapshot().get("model_id")
        entry = next((m for m in self.list_loadable_models() if m.get("id") == mid or m.get("hf") == mid), None)
        if not entry:
            raise ValueError("Balance needs an installed model")
        if entry.get("source") == "gguf":
            import web_gguf_files
            return web_gguf_files.preview(self, entry, body, fresh=fresh)
        configured = self.configured_nodes()
        ids = body.get("node_ids")
        if ids is not None:
            if not isinstance(ids, list) or len(set(ids)) != len(ids) or not set(ids) <= {n["id"] for n in configured}:
                raise ValueError("unknown or duplicate Mini IDs")
            configured = [n for n in configured if n["id"] in ids]
        if fresh:
            live = {n["id"]: web_nodes.gather_node_stats(n, ssh_fn=self._ssh_fn()) for n in configured}
            split = self.mgr.lead_split_info() if self.mgr.snapshot().get("status") == "ready" else {}
            if split:
                ids = (self.mgr.snapshot().get("balance") or {}).get("node_ids")
                ids = ids or [n["id"] for n in SB.pipeline_order(configured)]
                stage_by_id = dict(zip(ids[:-1], split.get("packers") or []))
                if ids:
                    stage_by_id[ids[-1]] = split.get("lead") or {}
                for n in configured:
                    stage = stage_by_id.get(n["id"]) or {}
                    if stage.get("active_gb") is not None:
                        live[n["id"]]["active_gb"] = stage["active_gb"]
        else:
            live = {n["id"]: n for n in (self.nodes().get("nodes") or [])}
        nodes = SB.pipeline_order([dict(n, **{k: v for k, v in live.get(n["id"], {}).items()
                                            if k in ("ram", "active_gb", "weights_gb", "model", "offline", "error")})
                                   for n in configured])
        d = Path(entry.get("lead_path") or "").expanduser()
        cfg = json.loads((d / "config.json").read_text())
        idx = json.loads((d / "model.safetensors.index.json").read_text())
        from mlx_split_fetch import n_layers_of
        inventories = {n["id"]: ((entry.get("nodes") or {}).get(n.get("label") or n["id"]) or {}) for n in nodes}
        import web_files
        for n in nodes:
            inv = inventories[n['id']]
            if not inv.get('path'):
                inv['path'] = web_files.model_dest(n,entry['hf'])
            if fresh or inv.get('storage') is None:
                try:
                    inv['storage'] = web_files.inspect_node(self, n, inv['path'])
                    actual = inv['storage'].get('files')
                    if actual is not None:
                        inv['has_config'] = 'config.json' in actual
                        inv['has_index'] = 'model.safetensors.index.json' in actual
                        inv['has_tokenizer'] = any(f in actual for f in ('tokenizer.json','tokenizer.model','tokenizer.tiktoken','vocab.json','spiece.model'))
                except (ValueError, OSError, RuntimeError):
                    inv['storage'] = {'files': None}
        weights = (idx.get("metadata") or {}).get("total_size")
        weights = float(weights) / 1e9 if weights else None
        if weights is None and any(v.get("full_ok") for v in inventories.values()):
            weights = entry.get("weights_gb")
        sizes = {}
        try:
            sizes = json.loads((d / "caravan-split-sizes.json").read_text()).get("sizes") or {}
            if sizes:
                weights = sum(sizes[f] for f in set(idx["weight_map"].values())) / 1e9
        except (OSError, ValueError, KeyError):
            pass
        out = SB.preview(n_layers_of(cfg), weights, nodes, body.get("counts"),
                         config=cfg, index=idx, inventories=inventories, sizes=sizes)
        from model_files import plan_digest
        out['repo_id'] = entry['hf']
        revision = None
        try:
            origin = json.loads((d/'caravan-source.json').read_text())
            if origin.get('repo') == entry['hf']: revision = origin.get('revision')
        except (OSError,ValueError): pass
        out['file_requests'] = [dict(format='mlx', revision=revision, repo_id=entry['hf'], dest=inventories[n['id']]['path'],
                                     counts=out['counts'], stage_index=i,
                                     metadata_digest=plan_digest(cfg, idx), required_files=out['stages'][i].get('required_files') or [])
                                for i, n in enumerate(nodes)]
        out["model_id"] = entry["id"]
        out["node_ids"] = [n["id"] for n in nodes]
        out["entry"] = dict(entry, split_counts=out["counts"],
                             pipeline_nodes=[dict(n, model_path=inventories[n["id"]].get("path")) for n in nodes],
                             run_mode="split", need_split=True, available_lead=out["ready"], usable=out["ready"],
                             placement={"mode": "split", "node_ids": out["node_ids"]})
        return out

    def configured_nodes(self) -> list:
        """Node list from ~/.caravan/config.toml [web.nodes.*] (defaults EXO1/EXO2)."""
        return web_nodes.nodes_from_config()

    def _ssh_fn(self):
        return web_nodes.make_ssh_fn(self.mgr)

    @staticmethod
    def _nodes_key(snap: dict):
        ready = snap.get("status") == "ready"
        return (bool(ready), snap.get("model_name") if ready else None, bool(snap.get("split")))

    def _nodes_refresh(self):
        try:
            cfg_nodes = self.configured_nodes()
            snap = self.mgr.snapshot()
            split = self.mgr.lead_split_info() if snap.get("status") == "ready" else None
            model = snap.get("model_name") if snap.get("status") == "ready" else None
            running_on = None
            gg = snap.get("gguf") or {}
            if model and gg.get("nodes"):
                running_on = list(gg["nodes"])
                split = None  # llama.cpp split: no MLX layer ranges
            elif model and (snap.get("balance") or {}).get("node_ids"):
                running_on = snap["balance"]["node_ids"]
            elif model and not snap.get("split"):
                wn = getattr(self.mgr, "_worker_node", None)
                if wn and wn.get("id"):
                    running_on = [wn["id"]]
                else:
                    running_on = [n.get("id") for n in cfg_nodes if n.get("role") == "lead"][:1]
                split = None  # single Mini: no packer layer ranges
            elif not model:
                running_on = []
            nodes = web_nodes.gather_all(
                cfg_nodes,
                ssh_fn=self._ssh_fn(),
                model=model,
                split=split,
                running_on=running_on,
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
                "key": self._nodes_key(snap),
                "link": (split or {}).get("peer") or peer or self.mgr.packer_peer,
                "nodes": nodes,
                "max_split_stages": web_nodes.stage_limit(self.configured_nodes()),
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
        if job and job.get('file_mode'):
            import web_files
            return web_files.cancel(self, job)
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
        if False:  # local uses the same process-tree/nettop script as remote (xet-safe)
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
            "  for p in list(d.glob('*.safetensors'))+list(d.rglob('*.gguf')):\n"
            "    try: done+=p.stat().st_size\n"
            "    except OSError: pass\n"
            "  c=d/'.cache'/'huggingface'/'download'\n"
            "  if c.is_dir():\n"
            "    for p in c.rglob('*'):\n"
            "      if p.is_file() and p.name.endswith('.incomplete'):\n"
            "        f=p.relative_to(c).as_posix()[:-11]\n"
            "        if (d/f).is_file() or (d/p.name[:-11]).is_file(): continue\n"
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
            "  ps=subprocess.run(['ps','-axo','pid=,ppid=,command='],capture_output=True,text=True,timeout=3).stdout\n"
            "  rows=[]\n"
            "  for ln in ps.splitlines():\n"
            "    f=ln.split(None,2)\n"
            "    if len(f)==3 and f[0].isdigit() and f[1].isdigit(): rows.append((int(f[0]),int(f[1]),f[2]))\n"
            "  root={r[0] for r in rows if 'mlx_split_fetch' in r[2] and 'import json' not in r[2] and (not repo or repo in r[2])}\n"
            "  tree=set(root); grew=True\n"
            "  while grew:\n"
            "    grew=False\n"
            "    for a,b,_c in rows:\n"
            "      if b in tree and a not in tree: tree.add(a); grew=True\n"
            "  if root:\n"
            "    pid=min(root)\n"
            "    r2=subprocess.run(['nettop','-P','-x','-L','1','-J','bytes_in'],capture_output=True,text=True,timeout=6)\n"
            "    tot=0\n"
            "    for ln in (r2.stdout or '').splitlines():\n"
            "      m=re.match(r'^.*\\.(\\d+),(\\d+),?$', ln.strip())\n"
            "      if m and int(m.group(1)) in tree: tot+=int(m.group(2))\n"
            "    net_raw=tot\n"
            "except Exception:\n"
            "  pass\n"
            "net_have=None\n"
            "if net_raw is not None:\n"
            "  if baseline is None: baseline=0\n"
            "  net_have=max(0, net_raw-int(baseline))\n"
            "source='starting'; out_have=0\n"
            "cands=[(hook_have or 0,'hook'),(net_have or 0,'nettop'),(have if (inc>0 or done>0) else 0,'disk')]\n"
            "best=max(cands,key=lambda c:c[0])\n"
            "if best[0]>0: out_have,source=best\n"
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
                # shlex.quote, not repr(): repr() of a script containing quotes is not
                # valid shell, so every remote measure failed and progress sat at 0.
                import shlex
                rdest = dest
                if rdest.startswith("~/"):
                    rdest = "$HOME/" + rdest[2:]
                script = "python3 -c %s \"%s\" %s %s" % (
                    shlex.quote(remote), rdest.replace('"', ''), shlex.quote(repo_id or ""), shlex.quote(base),
                )
                r = self._ssh_fn()(node, script, timeout=25)
            line = (getattr(r, "stdout", "") or "").strip().splitlines()
            if not line:
                err = ((getattr(r, "stderr", "") or "").strip().splitlines() or ["no output"])[-1]
                return {"have_bytes": 0, "n_incomplete": 0, "source": "starting",
                        "measure_error": err[-200:]}
            return json.loads(line[-1])
        except Exception as e:  # noqa: BLE001
            return {"have_bytes": 0, "n_incomplete": 0, "source": "starting",
                    "measure_error": str(e)[-200:]}

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
        import web_files
        return jobs + web_files.orphans(self,known)

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
                    models = (inv.inventory_payload(roots=[n['model_root']] if n.get('model_root') else None).get("models") or {})
                else:
                    repo = (n.get("repo") or "~/cv3").rstrip("/")
                    import web_files
                    inventory_cmd = web_files.rp(n.get('python') or '~/.caravan/venvs/mlx/bin/python') + ' ' + web_files.rp(repo+'/proxy/picker_disk_sizes.py') + ' --inventory'
                    if n.get('model_root'): inventory_cmd += ' --model-root ' + web_files.rp(n['model_root'])
                    r = self._ssh_fn()(
                        n,
                        inventory_cmd,
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
        rows = catalog.build_entries_from_inventories(
            node_inventories=invs,
            nodes=live or self.configured_nodes(),
            current_id=current,
            current_hf=current_hf,
            fit_nodes=[n for n in live if isinstance(n, dict) and not n.get("offline") and not n.get("error")],
            max_split_stages=web_nodes.stage_limit(self.configured_nodes()),
            include_unusable=True,
        )
        return rows + self.gguf_entries(live or self.configured_nodes(), current)

    def gguf_entries(self, nodes: list, current=None) -> list:
        """GGUF files on the lead Mini. llama.cpp RPC ships each peer its share
        at load, so only the lead needs the file; any online Mini can join."""
        import gguf_split
        out = []
        for g in gguf_split.scan_local():
            place = gguf_split.placement_options(g["size_gb"], nodes)
            out.append({
                "id": g["id"], "name": g["name"] + " (GGUF)", "hf": g["id"],
                "source": "gguf", "backend": "llama", "lead_path": g["path"],
                "size_gb": g["size_gb"], "usable": bool(place["default_id"]),
                "available_lead": True,
                "disabled_reason": "" if place["default_id"] else "won't fit on the online Minis",
                "placement_options": place["options"],
                "default_placement": place["default_id"],
                "current": g["id"] == current,
            })
        return out



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
                ".webp": "image/webp",
                ".avif": "image/avif",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
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
            if path.startswith("/assets/"):
                return self._serve_file(path.lstrip("/"))  # proxy/web/assets/...
            if path.startswith("/static/"):
                return self._serve_file(path.split("/", 2)[-1])
            if path == "/api/time":
                return self._api_time()
            if path == "/api/status":
                return self._api_status()
            if path == "/api/models":
                models = app.list_loadable_models()
                snap = app.mgr.snapshot()
                try:
                    web_alert.maybe_alert_async(models)
                except Exception:  # noqa: BLE001
                    pass
                return self._json(200, {
                    "models": models,
                    "caravan_version": web_alert.caravan_version(),
                    "current": snap.get("model_id"),
                    "source": "disk",
                    "max_split_stages": web_nodes.stage_limit(app.configured_nodes()),
                })
            if path == "/api/optimize":
                return self._json(200, app.optimizer.snapshot())
            if path == "/api/journey":
                return self._json(200, load_journey())
            if path == "/api/nodes":
                return self._json(200, app.nodes())
            if path == "/api/split":
                snap = app.mgr.snapshot()
                info = app.mgr.lead_split_info() if snap.get("status") == "ready" else None
                return self._json(200, {"worker": snap, "split": info})
            if path == "/api/settings":
                return self._api_settings()
            if path == "/api/hf-token":
                return self._api_hf_token_get()
            if path == "/api/helpers":
                import web_helpers
                return self._json(200, {"offer": web_helpers.offer(app.mgr.snapshot())})
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
            if path in ("/api/balance", "/api/files/preview") :
                try:
                    out = app.balance(body)
                    out.pop("entry", None)
                    out.pop("file_requests", None)
                    return self._json(200, out)
                except Exception as e:
                    return self._json(400, {"error": str(e)})
            if path == "/api/files/fetch":
                try:
                    import web_files
                    plan = app.balance(body, fresh=True)
                    return self._json(200, {"job": web_files.start(app, plan)})
                except Exception as e:
                    return self._json(400, {"error": str(e)})
            if path == "/api/time":
                return self._api_time(post=True, body=body)
            if path == "/api/models/load":
                return self._api_load(body=body)
            if path == "/api/models/stop":
                if app.optimizer.snapshot().get("running"):
                    return self._json(409, {"error": "Cancel Optimize now and wait before unloading"})
                try:
                    app.mgr.stop(reason="ui")
                except ManagedServiceError as e:
                    return self._json(409, {"error":str(e),"worker":app.mgr.snapshot()})
                except Exception as e:  # noqa: BLE001 — answer, don't drop the socket
                    msg = f"{type(e).__name__}: {e}"
                    try:
                        app.mgr._set(status="error", error=msg)
                        app.mgr._note(f"stop failed: {e}")
                    except Exception:
                        pass
                    return self._json(502, {"error": msg, "worker": app.mgr.snapshot()})
                return self._json(200, app.mgr.snapshot())
            if path in ("/api/optimize/start", "/api/optimize/gguf/start"):
                try:
                    if isinstance(app.mgr, WorkerManager):
                        app.mgr._deny_managed_service()
                except ManagedServiceError as e:
                    return self._json(409, {"error":str(e)})
                if len((app.mgr.snapshot().get("balance") or {}).get("counts") or []) > 2:
                    return self._json(409, {"error": "Optimize now is not yet safe for N-stage MLX Balance; use measured replies instead"})
                if app.mgr._switch_thread and app.mgr._switch_thread.is_alive():
                    return self._json(409, {"error": "a model load is in progress"})
                if app.optimizer.snapshot().get("running"):
                    return self._json(409, {"error": "optimize already running"})
                gguf = (path.endswith("/gguf/start")
                        or app.mgr.snapshot().get("backend") == "llama")
                try:
                    if gguf:
                        snap_ = app.gguf_optimizer.start()
                        app.optimizer = app.gguf_optimizer
                        return self._json(200, snap_)
                    snap_ = app.mlx_optimizer.start()
                    app.optimizer = app.mlx_optimizer
                    return self._json(200, snap_)
                except RuntimeError as e:
                    return self._json(409, {"error": str(e)})
            if path == "/api/optimize/pause":
                return self._json(200, app.optimizer.pause((body or {}).get("paused", True)))
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
            if path == "/api/helpers/answer":
                import web_helpers
                p = web_helpers.pairing(body.get("helper_id"))
                if not p or body.get("action") not in ("download", "decline"):
                    return self._json(400, {"error": "Unknown helper or action"})
                web_helpers.answer(p["id"], body["action"] == "download")
                if body["action"] == "decline":
                    return self._json(200, {"ok": True})
                return self._api_picker_download({"repo_id": p["draft"]["hf_repo"], "helper_id": p["id"]})
            if path == "/api/picker/download":
                return self._api_picker_download(body=body)
            if path == "/api/picker/download/resume":
                old = web_picker.get_job((body or {}).get("job_id") or "") or {}
                if not old:
                    return self._json(404, {"error": "unknown job"})
                if old.get("status") not in ("cancelled", "error"):
                    return self._json(409, {"error": "job is %s, not stopped/failed" % old.get("status")})
                req = dict(old.get("request") or {})
                if not req:
                    req = {"repo_id": old.get("repo_id"), "placement": old.get("placement")}
                req["resume_of"] = old.get("id")
                if req.get('file_fetch'):
                    try:
                        import web_files
                        return self._json(200, {"job": web_files.start(app, app.balance(req, fresh=True))})
                    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as e:
                        return self._json(400, {"error": str(e)})
                return self._api_picker_download(body=req)
            if path == "/api/picker/download/cancel":
                jid = (body or {}).get("job_id") or ""
                if jid.startswith('files-live-'):
                    import web_files
                    orphan = next((j for j in app.list_orphan_fetch_jobs() if j.get('id')==jid),None)
                    if not orphan: return self._json(404,{'error':'transfer is no longer running'})
                    return self._json(200,web_files.cancel(app,orphan))
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
            self.send_header("Cache-Control", "public, max-age=86400" if rel.startswith("assets/") else "no-cache")
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
            if hasattr(app.mgr,"refresh_managed_service"):
                app.mgr.refresh_managed_service()
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
            cat["max_split_stages"] = web_nodes.stage_limit(app.configured_nodes())
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
            cleanup_kinds = ("hf-cache",)
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

            helpers = {}
            for n in cfg_nodes:
                nid = n.get("id") or n.get("label")
                for key, h in ((blobs.get(nid) or {}).get("helpers") or {}).items():
                    e = helpers.setdefault(key, {"id": "cleanup:" + key, "kind": key,
                        "name": h["name"], "note": ("Pairs with " + ", ".join(h["pairs"])) if h.get("pairs") else "Manually installed helper; no catalog pairing recorded",
                        "size_gb": {}, "size_by_label": {}})
                    e["size_gb"][nid] = h["size_gb"]
                    e["size_by_label"][n.get("label") or nid] = h["size_gb"]
            cleanup.extend(helpers.values())

            # Attach placement + held_on from inventories when available
            try:
                invs = app.gather_model_inventories()
                place_by = {}
                held_by = {}
                part_by = {}
                for ni in invs:
                    label = ni.get("label") or ni.get("id")
                    for rid, st in (ni.get("models") or {}).items():
                        held_by.setdefault(rid, []).append(label)
                        if not st.get("full_ok") and not st.get("lead_ok") and not st.get("packer_ok"):
                            part_by.setdefault(rid, []).append(label)
                        if st.get("placement") and rid not in place_by:
                            place_by[rid] = st["placement"]
                for e in models:
                    rid = e.get("id")
                    e["held_on"] = held_by.get(rid) or list((e.get("size_by_label") or {}).keys())
                    if rid in place_by:
                        e["placement"] = place_by[rid]
                    if rid in part_by:
                        e["incomplete_on"] = part_by[rid]
                    e["n_nodes"] = len(cfg_nodes)
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
                "max_split_stages": web_nodes.stage_limit(app.configured_nodes()),
            })

        def _api_picker_delete(self, body=None):
            body = body or {}
            rid = body.get("id") or body.get("repo_id") or body.get("kind") or ""
            kind = (body.get("kind") or "").strip()
            if not kind.startswith(("draft:", "mtp:")):
                kind = kind.lower()
            if not body.get("confirm"):
                return self._json(400, {"error": "confirm=true required"})
            current = app.mgr.snapshot().get("model_id")
            cfg_nodes = app.configured_nodes()

            if kind in ("hf-cache", "drafts") or str(rid).startswith("cleanup:"):
                k = kind or str(rid).split(":", 1)[-1]
                results = []
                for n in cfg_nodes:
                    kn = "hf-cache" if k in ("hf-cache", "hf_cache", "cache") else k
                    if kn != "hf-cache" and current:
                        return self._json(409, {"error": "Stop the loaded model before deleting helpers."})
                    cur = (current or "").replace("'", "")
                    import shlex
                    kn = shlex.quote(kn)
                    try:
                        if web_nodes.is_local(n):
                            import subprocess
                            py = str(Path(app.mgr.repo) / "proxy" / "picker_disk_sizes.py")
                            r = subprocess.run(
                                [sys.executable, py, "--delete", k, "--current", cur],
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
                from hf_auth import validated_token_status
                return self._json(200, validated_token_status())
            except Exception as e:
                return self._json(500, {"error": "Could not check token status", "configured": False})

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
                max_split_stages=web_nodes.stage_limit(app.configured_nodes()),
            )
            from placement import placement_options
            opts = placement_options(
                fit=fit, nodes=online,
                max_split_stages=web_nodes.stage_limit(app.configured_nodes()),
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
                max_split_stages=web_nodes.stage_limit(app.configured_nodes()),
            )
            return self._json(200, fit)

        def _api_picker_download(self, body=None):
            body = body or {}
            repo = (body.get("repo_id") or body.get("id") or "").strip()
            if not repo:
                return self._json(400, {"error": "repo_id required"})
            try:
                from model_files import repo_name
                repo_name(repo)
            except ValueError as e:
                return self._json(400, {'error': str(e)})
            if body.get("source") == "cloud" or repo.startswith("ollama-cloud/"):
                return self._json(400, {"error": "cloud models are framework-only for now"})
            gguf_file = None
            if body.get("source") == "gguf":
                # Peers can run without the file (RPC ships tensors), but Day 18 copies it to every Mini.
                gguf_file = (body.get("gguf_file") or "").strip()
                if not gguf_file:
                    try:
                        gfs = web_picker._fetch_repo_blobs(repo).get("gguf_files") or []
                    except Exception:
                        gfs = []
                    if len(gfs) == 1:
                        gguf_file = gfs[0]["rfilename"]
                if (not gguf_file or ".." in gguf_file or gguf_file.startswith("/")
                        or not gguf_file.endswith(".gguf")):
                    return self._json(400, {"error": "pick one GGUF file (quant) to download"})
                lead = next((n for n in app.configured_nodes() if n.get("role") == "lead"), None)
                if not lead:
                    return self._json(400, {"error": "No lead configured"})
                body = dict(body, placement_id=None)
            import web_helpers
            helper = web_helpers.pairing(body.get("helper_id")) if body.get("helper_id") else None
            if body.get("helper_id") and (not helper or repo != helper["draft"]["hf_repo"]):
                return self._json(400, {"error": "Invalid helper"})
            packer_layers = body.get("packer_layers")
            pk_explicit = packer_layers is not None
            n_layers_dl = None
            try:
                packer_layers = int(packer_layers) if packer_layers is not None else None
            except (TypeError, ValueError):
                packer_layers = None
            if packer_layers is None:
                # Same default as the catalog (web_catalog._default_packer_layers), and
                # it is saved in caravan-placement.json, so download/catalog/load agree.
                import web_catalog
                n_layers = None
                try:
                    import urllib.request
                    from mlx_split_fetch import n_layers_of
                    with urllib.request.urlopen(
                            "https://huggingface.co/%s/resolve/main/config.json" % repo, timeout=10) as r:
                        n_layers = n_layers_of(json.loads(r.read()))
                except Exception:
                    n_layers = None
                packer_layers = web_catalog._default_packer_layers(repo, n_layers)
                n_layers_dl = n_layers

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
                max_split_stages=web_nodes.stage_limit(app.configured_nodes()),
            )
            from placement import placement_options, resolve_option
            opts = placement_options(
                fit=fit, nodes=online,
                max_split_stages=web_nodes.stage_limit(app.configured_nodes()),
                weights_gb=weights,
            )
            place = resolve_option(opts, body=body)
            if gguf_file:
                place = {"enabled": True}
            if not place:
                return self._json(400, {"error": "no placement option available", "options": opts})
            if not place.get("enabled"):
                return self._json(400, {
                    "error": place.get("reason") or "placement disabled",
                    "placement": place, "options": opts,
                })

            if gguf_file:
                lid = lead.get("id") or lead.get("label")
                # llama.cpp needs the complete lead file; peers fetch tensor ranges
                # explicitly from the Balance file view, never a full GGUF copy.
                ids = [lid]
                place = {"mode": "one", "full_copy": True, "node_ids": ids, "enabled": True,
                         "label": f"GGUF to {len(ids)} Mini{'s' if len(ids) > 1 else ''} · "
                                  "complete lead file; peer tensor fetch in Balance"}
            if helper:
                lead = next((n for n in app.configured_nodes() if n.get("role") == "lead"), None)
                if not lead:
                    return self._json(400, {"error": "No lead configured"})
                place = {"mode": "one", "full_copy": True, "node_ids": [lead.get("id") or lead.get("label")], "label": "Guess-ahead helper · applies on next load"}
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
            if mode == 'split' and (len(target_nodes) > 2 or any(n.get('model_root') for n in target_nodes)):
                try:
                    import web_files
                    if pk_explicit and body.get('counts') is None:
                        raise ValueError('Use one count per Mini, not packer_layers, for an N-stage split')
                    plan = web_files.prepare_new_mlx(app, repo, target_nodes, body.get('counts'))
                    job = web_files.start(app, plan)
                    return self._json(200, {'job': job, 'stages': len(target_nodes), 'placement': job.get('placement'),
                                            'note': 'N-stage own-file download; no files are deleted'})
                except Exception as e:
                    return self._json(400, {'error': str(e)})
            # Day 18 split safety: default the split point to a balanced one from each
            # Mini's RAM (24/8 on two 24 GB Minis left EXO2 under the margin → 507).
            balance_note = ""
            if (mode == "split" and not pk_explicit and not gguf_file and not helper
                    and n_layers_dl and weights and len(target_nodes) >= 2):
                try:
                    import split_balance
                    live_by = {(n.get("id") or n.get("label")): n for n in online}
                    stg = [dict(n, **{k: v for k, v in (live_by.get(n.get("id") or n.get("label")) or {}).items()
                                      if k in ("ram", "active_gb", "weights_gb", "model")})
                           for n in target_nodes[: web_nodes.MAX_SPLIT_STAGES]]
                    kb = split_balance.balanced_packer_layers(n_layers_dl, weights, stg)
                    if kb and kb != packer_layers:
                        balance_note = f"split point {kb}/{n_layers_dl - kb} (balanced for each Mini's RAM; default was {packer_layers})"
                        packer_layers = kb
                except Exception:  # noqa: BLE001 - keep the old default
                    pass

            n_stages = len(target_nodes) if mode == "split" else 1
            note = place.get("label") or ""
            if mode == "split" and len(target_nodes) > web_nodes.MAX_SPLIT_STAGES:
                note = (
                    f"{len(target_nodes)}-Mini split coming later; "
                    f"downloading for {web_nodes.MAX_SPLIT_STAGES}-stage runtime"
                )
                target_nodes = target_nodes[: web_nodes.MAX_SPLIT_STAGES]
                n_stages = len(target_nodes)
            if balance_note:
                note = (note + " · " if note else "") + balance_note

            if gguf_file:
                try:
                    gsz = next((int(g.get("size") or 0) for g in
                                web_picker._fetch_repo_blobs(repo).get("gguf_files") or []
                                if g.get("rfilename") == gguf_file), 0)
                except Exception:
                    gsz = int(weights * 1e9)
                totals = {"lead": gsz, "packer": gsz, "each": gsz, "full": gsz}
            else:
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
                    if gguf_file:
                        cmd += ["--gguf-file", gguf_file]
                    elif pk and role != "all":
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
                    if gguf_file:
                        script += "--gguf-file %s " % shlex.quote(gguf_file)
                    elif pk and role != "all":
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
                            # Only a live job's Stop counts. An older stopped job for the same
                            # repo keeps cancel=True forever and used to kill every restart.
                            if (j.get("repo_id") == repo_id and j.get("cancel")
                                    and j.get("status") in ("running", "cancelling", "queued")):
                                app.picker_kill_node(node, repo_id, j)
                                raise RuntimeError("cancelled")
                        log_f = "/tmp/caravan-fetch-%s.log" % (node.get("id") or "node")
                        check = app._ssh_fn()(node,
                            "head -1 %s 2>/dev/null | sed 's/^/REPORT:/'; "
                            "if [ -f %s ]; then pid=$(cat %s); "
                            "if kill -0 $pid 2>/dev/null; then echo RUNNING; "
                            "else echo DONE; fi; else echo DONE; fi" % (log_f, pid_file, pid_file),
                            timeout=30,
                        )
                        st = (check.stdout or "").strip().splitlines()
                        for ln in st:
                            if ln.startswith("REPORT:"):
                                web_picker.apply_reported_total(
                                    repo_id, node.get("id") or node.get("label"), ln[7:])
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
                    if gguf_file:
                        import gguf_split
                        dest = str(gguf_split.GGUF_ROOTS[0] / folder)
                    run = make_run_local(n)
                    def _mk_local_measure(nn, dd, rid=repo, key=nid):
                        def _m():
                            prev = prev_state.get(key)
                            snap = app.picker_measure_node(nn, dd, repo_id=rid, prev=prev)
                            prev_state[key] = snap
                            return snap
                        return _m
                    measure = _mk_local_measure(n, dest)
                    save_placement = None
                else:
                    dest = ("~/.caravan/models/%s" if gguf_file else "~/.caravan/mlx-models/%s") % folder
                    run = make_run_remote(n)
                    def _mk_measure(nn, dd, rid=repo, key=nid):
                        def _m():
                            prev = prev_state.get(key)
                            snap = app.picker_measure_node(nn, dd, repo_id=rid, prev=prev)
                            prev_state[key] = snap
                            return snap
                        return _m
                    measure = _mk_measure(n, dest)
                    def _mk_save(nn, dd):
                        def _s(blob):
                            import shlex
                            rd = "$HOME/" + dd[2:] if dd.startswith("~/") else dd
                            cmd = 'mkdir -p "%s" && printf %%s %s > "%s/caravan-placement.json"' % (
                                rd, shlex.quote(json.dumps(blob, indent=2)), rd)
                            app._ssh_fn()(nn, cmd, timeout=30)
                        return _s
                    save_placement = _mk_save(n, dest)
                tb = totals.get("each") if full_copy else (
                    totals.get("lead") if role == "lead" else totals.get("packer")
                )
                if tb is None:
                    tb = totals.get("each") or totals.get("full")
                if helper:
                    dest = "~/.caravan/mlx-models/drafts/" + helper["draft"]["name"]
                    if web_nodes.is_local(n):
                        dest = str(Path(dest).expanduser())
                    measure = _mk_local_measure(n, dest) if web_nodes.is_local(n) else _mk_measure(n, dest)
                    save_placement = None
                runners.append({
                    "id": nid,
                    "label": n.get("label") or nid,
                    "role": role,
                    "dest": dest,
                    "run": run,
                    "measure": measure,
                    "total_bytes": tb,
                    "save_placement": save_placement,
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
            req = {k: v for k, v in body.items() if k != "resume_of"}
            extra = {"request": req}
            if gguf_file:
                extra["load_id"] = "gguf/" + Path(gguf_file).stem
            if body.get("resume_of"):
                extra.update(resume_of=body["resume_of"], resuming=True)
            web_picker._job_set(job["id"], **extra)
            job = {**job, **extra}
            return self._json(200, {
                "job": job,
                "totals": totals,
                "stages": len(runners),
                "max_split_stages": web_nodes.stage_limit(app.configured_nodes()),
                "note": note,
                "placement": place,
                "nodes": [{"id": r["id"], "label": r["label"], "role": r["role"]} for r in runners],
            })


        def _api_load(self, body=None):
            if isinstance(app.mgr, WorkerManager):
                try:
                    app.mgr._deny_managed_service()
                except ManagedServiceError as e:
                    return self._json(409, {"error":str(e)})
            if app.optimizer.snapshot().get("running"):
                return self._json(409, {"error": "Cancel Optimize now and wait before loading"})
            body = body or {}
            mid = body.get("model_id") or body.get("id")
            if not mid:
                return self._json(400, {"error": "model_id required"})
            # Prefer N-node disk inventory (EXO2-only placements etc.) over the
            # local-only catalog.get_model fallback.
            entry = None
            mid_l = str(mid).lower()
            for m in app.list_loadable_models() or []:
                if not isinstance(m, dict):
                    continue
                if (m.get("id") == mid or m.get("hf") == mid
                        or str(m.get("id") or "").lower() == mid_l
                        or str(m.get("hf") or "").lower() == mid_l):
                    entry = m
                    break
            if entry and entry.get("source") == "gguf":
                entry = dict(entry)
                pid_ = body.get("placement_id") or entry.get("default_placement")
                opt = next((o for o in entry.get("placement_options") or [] if o.get("id") == pid_), None)
                if not opt:
                    return self._json(400, {"error": f"unknown placement {pid_!r} for {mid}"})
                if not opt.get("enabled"):
                    return self._json(400, {"error": opt.get("reason") or "placement doesn't fit"})
                entry["placement"] = {"mode": opt["mode"], "node_ids": opt["node_ids"]}
            if body.get("balance"):
                if app._inflight:
                    return self._json(409, {"error": "Wait for the current reply before reloading"})
                try:
                    plan = app.balance(dict(body, model_id=mid), fresh=True)
                    if not plan["ready"]:
                        plan.pop("entry", None)
                        plan.pop("file_requests", None)
                        return self._json(409, {"error": "Split needs files or more memory; nothing was changed", "balance": plan})
                    entry = plan["entry"]
                except (ValueError, OSError, KeyError, TypeError) as e:
                    return self._json(400, {"error": str(e)})
            balanced_msg = None
            sc = ((entry or {}).get("split_check")
                  if entry and not body.get("balance") and entry.get("source") != "gguf" and entry.get("run_mode") == "split" else None)
            if sc and not sc.get("ok") and not body.get("force_split"):
                if sc.get("better") and sc.get("balanced_ready"):
                    kb = int(sc["balanced_packer_layers"])
                    entry = dict(entry, packer_layers=kb)
                    balanced_msg = (f"Loading at a balanced split ({kb}/{sum(sc['counts']) - kb}) instead of "
                                    f"the saved {'/'.join(map(str, sc['counts']))}, so every Mini keeps its safety margin.")
                else:
                    return self._json(409, {"error": entry.get("split_note") or sc.get("note") or "split too tight",
                                            "split_check": sc})
            try:
                snap = app.mgr.switch(mid, wait=False, settings=body.get("settings"),
                                     entry=entry)
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                return self._json(400, {"error": str(e)})
            if balanced_msg:
                try:
                    app.mgr._note(balanced_msg)
                except Exception:  # noqa: BLE001
                    pass
                snap = dict(snap, balance_note=balanced_msg)
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
            except (OSError, http.client.HTTPException) as e:
                return self._json(502, {"error": "The model stopped before replying. Check the status line.",
                                        "detail": str(e)[:300]})

            if not stream:
                try:
                    data = json.loads(upstream.read().decode())
                except (OSError, ValueError, http.client.HTTPException) as e:
                    return self._json(502, {"error": "The model stopped mid-reply. Check the status line.",
                                            "detail": str(e)[:300]})
                finally:
                    upstream.close()
                t_done = time.time()
                usage = (data.get("usage") or {})
                if data.get("timings"):
                    import gguf_split
                    usage = gguf_split.usage_from_timings(usage, data["timings"])
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
            timings_ = None
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
                            if obj.get("timings"):
                                timings_ = obj["timings"]
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
            if timings_:
                import gguf_split
                usage = gguf_split.usage_from_timings(usage, timings_)
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
        if mgr.adopt_gguf():
            print("[caravan-web] adopted running GGUF llama-server from before restart", flush=True)
        elif mgr.adopt_running():
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
