"""Configured Minis / string nodes for the web UI (Topology + picker).

Reads optional [web.nodes.<id>] tables from ~/.caravan/config.toml.
Missing section retains the legacy two-Mac inventory. New installs create
an explicit local node; other deployments should configure their own inventory.
A node with no host is omitted. Offline configured nodes are marked offline
and skipped by fit.
"""
from __future__ import annotations

import json
import os
import re
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
        # No config is a new, single-Mac install, never a lab SSH target.
        # Existing developer config files retain the historical fallback.
        if cfg is None and not web_settings.CONFIG_PATH.is_file():
            return [dict(id="local", label="My Mac", role="lead", host="local")]
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


def looks_like_hostname(name: str) -> bool:
    """True for machine hostnames that should not appear as a Mac label."""
    s = (name or "").strip()
    if not s:
        return True
    if any(ch.isspace() for ch in s):
        return False
    if s.lower() in ("localhost", "local", "127.0.0.1"):
        return True
    if "." in s or ":" in s:
        return True
    if re.match(r"^exo\d+$", s, re.I):
        return True
    if re.match(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)+$", s) and not re.search(r"(?i)mac|mini", s):
        return True
    return False


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def friendly_mac_label(node=None, *, label=None, role=None, node_id=None,
                       index=None, node_count=None, inventory=None) -> str:
    """Same friendly Mac name for MLX and GGUF job cards. Never a hostname.

    Both job types look up the configured node (inventory) so a Mini that
    GGUF shows as "My Mac" is not shown as a hostname on an MLX card.
    """
    node = node or {}
    raw = (label if label is not None else node.get("label") or "").strip()
    role = (role if role is not None else node.get("role") or "").strip().lower()
    nid = node_id if node_id is not None else node.get("id")
    inv = list(inventory or [])
    match = None
    if inv:
        if nid:
            match = next((n for n in inv if n.get("id") == nid), None)
        if match is None and raw:
            match = next((n for n in inv
                          if n.get("label") == raw or n.get("host") == raw
                          or n.get("id") == raw or n.get("ssh") == raw), None)
        if match is None and role:
            match = next((n for n in inv if (n.get("role") or "").lower() == role), None)
        if match is not None:
            inv_label = (match.get("label") or "").strip()
            if inv_label and not looks_like_hostname(inv_label) and inv_label.lower() not in ("lead", "packer", "local"):
                return inv_label
            role = role or (match.get("role") or "").strip().lower()
            if index is None:
                try:
                    index = inv.index(match)
                except ValueError:
                    index = None
            if node_count is None:
                node_count = len(inv)
    if raw and not looks_like_hostname(raw) and raw.lower() not in ("lead", "packer", "local"):
        return raw
    # Role first: a job may have only the packer as its single runner (index 0).
    if role == "lead":
        return "My Mac" if node_count == 1 else "1st Mac"
    if role == "packer":
        return "2nd Mac"
    if index == 0:
        return "My Mac" if node_count == 1 else "1st Mac"
    if index == 1:
        return "2nd Mac"
    if isinstance(index, int) and index >= 0:
        return _ordinal(index + 1) + " Mac"
    if nid and not looks_like_hostname(str(nid)):
        return str(nid)
    return "Mac"


def friendly_job(job, inventory=None, node_count=None):
    """Copy a picker job with hostname / EXO* labels replaced by friendly Mac names."""
    if not job:
        return job
    j = dict(job)
    runners = [dict(r) for r in (j.get("runners") or [])]
    inv = list(inventory or [])
    n = node_count if node_count is not None else (len(inv) or len(runners) or 1)
    for i, r in enumerate(runners):
        r["label"] = friendly_mac_label(r, index=i, node_count=n, inventory=inv)
    j["runners"] = runners
    by_id = {r.get("id"): r for r in runners}
    by_role = {r.get("role"): r for r in runners if r.get("role")}
    progress = {}
    for k, snap in (j.get("progress") or {}).items():
        snap = dict(snap)
        match = by_id.get(k) or by_role.get(k)
        if match:
            snap["label"] = match["label"]
        else:
            snap["label"] = friendly_mac_label(
                label=snap.get("label"), role=snap.get("role"),
                node_id=k, node_count=n, inventory=inv)
        progress[k] = snap
    j["progress"] = progress
    return j
