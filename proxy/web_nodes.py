"""Configured Minis / string nodes for the web UI (Topology + picker).

Reads optional [web.nodes.<id>] tables from ~/.caravan/config.toml.
Missing section → Brenden's default 2-Mini string (EXO1 local lead, EXO2 SSH).
A node with no host is omitted. Offline configured nodes are marked offline
and skipped by fit.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

import web_catalog as catalog
import web_settings

# N-stage runtime: no default topology cap; an explicit operator cap still works.
MAX_SPLIT_STAGES = int(os.environ.get("CARAVAN_MAX_SPLIT_STAGES", str(__import__("sys").maxsize)))

def stage_limit(nodes):
    return min(MAX_SPLIT_STAGES, max(1, len(nodes)))

DEFAULT_NODES = [
    {
        "id": "exo1",
        "label": "EXO1",
        "role": "lead",
        "host": "local",
    },
    {
        "id": "exo2",
        "label": "EXO2",
        "role": "packer",
        "host": catalog.DEFAULT_PACKER_SSH,
        "ssh": catalog.DEFAULT_PACKER_SSH,
        "repo": "~/cv3",
        "peer": catalog.DEFAULT_PACKER_PEER,
        "remote_repo": "~/cv3",
    },
]


def _raw_web_nodes(cfg: Optional[dict] = None) -> dict:
    """Return the raw `web.nodes` table from config (or empty)."""
    if cfg is None:
        # load_config only returns defaults/models — read file again for web.*
        p = web_settings.CONFIG_PATH
        if not p.is_file():
            return {}
        try:
            text = p.read_text()
            try:
                import tomllib
                raw = tomllib.loads(text)
            except ImportError:
                raw = web_settings._parse_toml_subset(text)
        except Exception:
            return {}
    else:
        # Prefer embedded raw if present
        raw = cfg.get("_raw") or {}
        if not raw and cfg.get("path"):
            try:
                p = Path(cfg["path"])
                if p.is_file():
                    text = p.read_text()
                    try:
                        import tomllib
                        raw = tomllib.loads(text)
                    except ImportError:
                        raw = web_settings._parse_toml_subset(text)
            except Exception:
                raw = {}
    web = raw.get("web") or {}
    nodes = web.get("nodes") or {}
    return nodes if isinstance(nodes, dict) else {}


def nodes_from_config(cfg: Optional[dict] = None) -> list:
    """Configured nodes in display order. Host empty → skipped (does not exist)."""
    raw = _raw_web_nodes(cfg)
    if not raw:
        return [dict(n) for n in DEFAULT_NODES]
    out = []
    for nid, tbl in raw.items():
        if not isinstance(tbl, dict):
            continue
        host = str(tbl.get("host") or "").strip()
        if not host:
            continue  # no host → node does not exist
        role = str(tbl.get("role") or ("lead" if not out else "packer")).strip().lower()
        if role in ("head",):
            role = "lead"
        if role in ("front", "tail"):
            role = "packer"
        node = {
            "id": str(nid),
            "label": str(tbl.get("label") or nid),
            "role": role,
            "host": host,
            "ssh": str(tbl.get("ssh") or ("" if host == "local" else host)),
            "repo": str(tbl.get("repo") or tbl.get("remote_repo") or "~/cv3"),
            "peer": str(tbl.get("peer") or ""),
            "listen": str(tbl.get("listen") or ""),
            "model_root": str(tbl.get("model_root") or ""),
            "python": str(tbl.get("python") or "~/.caravan/venvs/mlx/bin/python"),
            "upstream_peer": str(tbl.get("upstream_peer") or ""),
            "physical_id": str(tbl.get("physical_id") or ""),
            "order": int(tbl["order"]) if str(tbl.get("order") or "").isdigit() else len(out),
        }
        out.append(node)
    if not out:
        return [dict(n) for n in DEFAULT_NODES]
    # lead first, then packers by order
    out.sort(key=lambda n: (0 if n["role"] == "lead" else 1, n.get("order", 0), n["id"]))
    return out


def is_local(node: dict) -> bool:
    h = (node.get("host") or "").strip().lower()
    return h in ("local", "localhost", "127.0.0.1", "")


def online_nodes(nodes: list) -> list:
    return [n for n in (nodes or []) if isinstance(n, dict)
            and not n.get("offline") and not n.get("error")]


def split_stage_nodes(nodes: list, *, max_stages: int = MAX_SPLIT_STAGES) -> list:
    """Nodes that participate in today's split download/load (≤ max_stages)."""
    online = online_nodes(nodes)
    if not online:
        return []
    leads = [n for n in online if n.get("role") == "lead"]
    others = [n for n in online if n.get("role") != "lead"]
    ordered = (leads or online[:1]) + others
    # dedupe by id
    seen = set()
    out = []
    for n in ordered:
        i = n.get("id") or n.get("label")
        if i in seen:
            continue
        seen.add(i)
        out.append(n)
        if len(out) >= max_stages:
            break
    return out


def gather_node_stats(node: dict, *, ssh_fn=None, local_gather=None) -> dict:
    """Return stats dict for one node; sets offline/error on failure."""
    base = {
        "id": node.get("id"),
        "label": node.get("label"),
        "role": node.get("role"),
        "host": node.get("host"),
        "ssh": node.get("ssh"),
        "repo": node.get("repo"),
        "peer": node.get("peer"),
    }
    try:
        if is_local(node):
            if local_gather is None:
                import node_stats
                local_gather = node_stats.gather
            stats = local_gather() or {}
        else:
            if ssh_fn is None:
                raise RuntimeError("no ssh")
            repo = (node.get("repo") or "~/cv3").rstrip("/")
            # Prefer remote checkout's node_stats.py
            cmd = f"/usr/bin/python3 {repo}/proxy/node_stats.py"
            r = ssh_fn(node, cmd, timeout=25)
            if getattr(r, "returncode", 1) != 0:
                raise RuntimeError((getattr(r, "stderr", None) or getattr(r, "stdout", None) or "ssh failed")[-200:])
            line = (r.stdout or "").strip().splitlines()[-1]
            stats = json.loads(line)
        if not isinstance(stats, dict):
            raise RuntimeError("bad stats")
        out = dict(stats)
        out.update(base)
        out["offline"] = False
        return out
    except Exception as e:  # noqa: BLE001
        return {**base, "offline": True, "error": str(e)}


def gather_all(nodes_cfg: list, *, ssh_fn=None, local_gather=None,
               model: Optional[str] = None, split: Optional[dict] = None,
               running_on: Optional[list] = None) -> list:
    """Parallel gather for every configured node; annotate layers from split.

    running_on: node ids that actually host the loaded model. None means
    "every node" only when split packers are present; otherwise the lead.
    Nodes not hosting it get model="" (idle) so the UI never shows a model
    on a Mini that isn't running it.
    """
    results = [None] * len(nodes_cfg)
    lock = threading.Lock()

    def one(i, n):
        st = gather_node_stats(n, ssh_fn=ssh_fn, local_gather=local_gather)
        with lock:
            results[i] = st

    threads = [threading.Thread(target=one, args=(i, n)) for i, n in enumerate(nodes_cfg)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    lead_l = (split or {}).get("lead") or {}
    packers = (split or {}).get("packers") or []
    pk_i = 0
    if running_on is None:
        if packers:
            running_on = [n.get("id") for n in nodes_cfg]
        else:
            running_on = [n.get("id") for n in nodes_cfg if n.get("role") == "lead"][:1]
    hosts = set(running_on or [])
    out = []
    for st in results:
        if st is None:
            continue
        if st.get("id") not in hosts:
            st["model"] = ""
            st["layers"] = None
            out.append(st)
            continue
        if model and not st.get("offline"):
            st["model"] = model
        elif not model:
            st["model"] = ""
        if st.get("role") == "lead" and lead_l:
            st["layers"] = lead_l.get("name")
            st["weights_gb"] = lead_l.get("weights_gb")
            st["active_gb"] = lead_l.get("active_gb")
        elif st.get("role") != "lead" and pk_i < len(packers):
            pk = packers[pk_i] or {}
            st["layers"] = pk.get("name")
            st["weights_gb"] = pk.get("weights_gb")
            st["active_gb"] = pk.get("active_gb")
            st["sessions"] = pk.get("sessions")
            pk_i += 1
        out.append(st)
    return out


def make_ssh_fn(mgr):
    """Build ssh_fn(node, cmd, timeout=) using WorkerManager-style _ssh or per-node ssh."""
    def ssh_fn(node, cmd, timeout=60):
        target = (node.get("ssh") or node.get("host") or "").strip()
        if not target or is_local(node):
            raise RuntimeError("local node has no ssh")
        # Prefer mgr._ssh when target matches default packer; else raw ssh.
        default = (getattr(mgr, "packer_ssh", None) or "").strip()
        if target == default and hasattr(mgr, "_ssh"):
            return mgr._ssh(cmd, timeout=timeout)
        import subprocess
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, cmd],
            capture_output=True, text=True, timeout=timeout,
        )
    return ssh_fn
