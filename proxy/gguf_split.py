"""GGUF (llama.cpp) loads for the web UI: one Mini or split across K Minis.

Same mechanism as the CLI split (Sep 5, commit ae838f1, launchd/com.caravan.*):
each peer Mini runs `ggml-rpc-server` (loopback only); the lead reaches each
through an SSH tunnel and runs `llama-server --rpc 127.0.0.1:p1,127.0.0.1:p2,...` and llama.cpp ships each peer its share of the
weights over the network at load. Peers do NOT need the .gguf file -- only
the lead does. The first load copies the peer's share over Thunderbolt; with
`rpc-server -c` the peer keeps a local tensor cache so later loads are faster.

Pure helpers here (placement, commands, parsing) so tests need no Minis.
WorkerManager (web_workers.py) runs the commands and tracks every PID it
starts; Stop kills only those PIDs, after checking the command line.
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Optional

LLAMA_BIN = os.environ.get("CARAVAN_LLAMA_BIN", "~/dev/llama.cpp/build/bin")
RPC_PORT = int(os.environ.get("CARAVAN_GGUF_RPC_PORT", "50052"))
GGUF_CTX = int(os.environ.get("CARAVAN_GGUF_CTX", "8192"))
GGUF_ROOTS = [Path(p).expanduser() for p in os.environ.get(
    "CARAVAN_GGUF_ROOTS", "~/.caravan/models").split(":") if p]
# macOS lets Metal wire ~75% of RAM (recommendedMaxWorkingSetSize); keep
# headroom for KV cache + compute buffers on top of the weights.
GPU_FRACTION = 0.75
HEADROOM_GB = 1.5
RPC_PID = "~/.caravan/web-ui/rpc-server.pid"
RPC_LOG = "~/.caravan/web-ui/rpc-server.log"


def gguf_id(path) -> str:
    return "gguf/" + Path(str(path)).stem


def scan_local(roots=None) -> list:
    """GGUF files on this (lead) Mini. Skips mmproj and shard 2+ files."""
    out = []
    seen = set()
    for root in roots or GGUF_ROOTS:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.gguf")):
            name = p.name.lower()
            if "mmproj" in name or ("-of-" in name and "-00001-of-" not in name):
                continue
            try:
                size = p.stat().st_size  # follows symlinks
            except OSError:
                continue
            if size < 50_000_000:
                continue
            gid = gguf_id(p)
            if gid in seen:
                continue
            seen.add(gid)
            out.append({"id": gid, "name": p.stem, "path": str(p),
                        "size_gb": round(size / 1e9, 2)})
    return out


def node_gpu_gb(node: dict) -> Optional[float]:
    ram = (node or {}).get("ram") or {}
    tot = ram.get("total_gb")
    try:
        return float(tot) * GPU_FRACTION if tot else None
    except (TypeError, ValueError):
        return None


def rpc_host(node: dict) -> str:
    """Address the lead dials for this peer's rpc-server (Thunderbolt first)."""
    peer = (node.get("peer") or "").strip()
    if peer:
        return peer.rsplit(":", 1)[0] if ":" in peer else peer
    h = (node.get("ssh") or node.get("host") or "").strip()
    return h.split("@", 1)[-1]


def placement_options(weights_gb: float, nodes: list) -> dict:
    """one-Mini per node, then split across the first K online Minis (lead first).

    Default = the smallest option that fits (one Mini beats a split).
    """
    online = [n for n in nodes or [] if isinstance(n, dict)
              and not n.get("offline") and not n.get("error")]
    lead = [n for n in online if n.get("role") == "lead"][:1]
    ordered = lead + [n for n in online if n not in lead]
    need = float(weights_gb or 0) + HEADROOM_GB
    opts = []
    for n in lead:  # GGUF runs llama-server on the lead; the file lives there
        cap = node_gpu_gb(n)
        ok = cap is None or cap >= need
        opts.append({
            "id": f"one:{n['id']}", "mode": "one", "node_ids": [n["id"]],
            "node_labels": [n.get("label") or n["id"]],
            "label": f"One Mini · {n.get('label') or n['id']}",
            "enabled": ok, "fits": ok,
            "reason": "" if ok else f"needs ~{need:.1f} GB, {n.get('label')} has ~{cap:.1f} GB for the GPU",
        })
    for k in range(2, len(ordered) + 1):
        grp = ordered[:k]
        caps = [node_gpu_gb(n) for n in grp]
        total = sum(c for c in caps if c) if all(caps) else None
        ok = total is None or total >= need
        labels = [n.get("label") or n["id"] for n in grp]
        opts.append({
            "id": "split:" + ",".join(n["id"] for n in grp), "mode": "split",
            "node_ids": [n["id"] for n in grp], "node_labels": labels,
            "label": f"Split across {k} Minis · {' + '.join(labels)}",
            "enabled": ok, "fits": ok,
            "reason": "" if ok else f"needs ~{need:.1f} GB, these Minis have ~{total:.1f} GB together",
        })
    default = next((o["id"] for o in opts if o["enabled"]), None)
    return {"options": opts, "default_id": default, "weights_gb": weights_gb}


def tensor_split(nodes: list) -> list:
    """Share per Mini, proportional to its GPU memory (equal when unknown)."""
    caps = [node_gpu_gb(n) for n in nodes]
    if not all(caps):
        return [1] * len(nodes)
    return [round(c, 1) for c in caps]


def llama_args(model_path: str, *, port: int, peers: list, shares: list,
               ctx: int = GGUF_CTX, bin_dir: str = LLAMA_BIN) -> list:
    """llama-server argv. peers = ["host:port", ...] (empty for one Mini)."""
    args = [str(Path(bin_dir).expanduser() / "llama-server"),
            "-m", str(Path(model_path).expanduser()),
            "--host", "127.0.0.1", "--port", str(int(port)),
            "-c", str(int(ctx)), "-ngl", "999", "-fa", "on", "--jinja"]
    if peers:
        devs = ["MTL0"] + [f"RPC{i}" for i in range(len(peers))]
        args += ["--rpc", ",".join(peers), "--device", ",".join(devs),
                 "--tensor-split", ",".join(str(s) for s in shares)]
    return args


def _rpath(p: str) -> str:
    return ('"$HOME"/' + shlex.quote(p[2:])) if p.startswith("~/") else shlex.quote(p)


def rpc_start_command(*, port: int = RPC_PORT, bin_dir: str = LLAMA_BIN) -> str:
    """Remote shell: stop our tracked rpc-server, start one on 127.0.0.1, print PID.

    Security: ggml-rpc-server has no auth, so on a peer it listens on
    loopback ONLY. The lead reaches it through an SSH local forward
    (ssh_tunnel_args), so only machines holding Caravan's SSH key -- the
    topology Minis -- can talk to it, over an encrypted channel. No network
    listener, no sudo/pf, any number of Minis. (Also sidesteps macOS Local
    Network privacy, which made llama-server's direct dials fail with
    "Failed to connect" when launched under the web server.)
    `-d MTL0` gives one RPC device per Mini, so RPC<i> maps to peer i.
    Exit 3 = port busy by something we don't own; 4 = died / not listening.
    """
    binp = _rpath(bin_dir.rstrip("/") + "/ggml-rpc-server")
    return (
        "mkdir -p ~/.caravan/web-ui; "
        + rpc_stop_command() + "; "
        + f"if lsof -nP -iTCP:{int(port)} -sTCP:LISTEN >/dev/null 2>&1; then echo PORT_BUSY; exit 3; fi; "
        f"nohup {binp} -d MTL0 -H 127.0.0.1 -p {int(port)} -c "
        f"> {RPC_LOG} 2>&1 & echo $! > {RPC_PID}; "
        f"p=$(cat {RPC_PID}); "
        f"for i in $(seq 1 60); do kill -0 $p 2>/dev/null || break; "
        f"lsof -nP -iTCP:{int(port)} -sTCP:LISTEN >/dev/null 2>&1 && break; sleep 0.25; done; "
        f"kill -0 $p 2>/dev/null || {{ tail -5 {RPC_LOG}; echo DIED; exit 4; }}; "
        f"lsof -nP -iTCP:{int(port)} -sTCP:LISTEN >/dev/null 2>&1 || {{ tail -5 {RPC_LOG}; echo NOT_LISTENING; exit 4; }}; "
        "echo PID:$p"
    )


def ssh_tunnel_args(ssh_target: str, local_port: int, remote_port: int = RPC_PORT) -> list:
    """ssh -L lead 127.0.0.1:<local_port> → peer 127.0.0.1:<remote_port>."""
    return ["ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15", "-o", "ConnectTimeout=10",
            "-c", "aes128-gcm@openssh.com,chacha20-poly1305@openssh.com", "-N",
            "-L", f"127.0.0.1:{int(local_port)}:127.0.0.1:{int(remote_port)}", ssh_target]


def tunnel_port(i: int) -> int:
    return RPC_PORT + 10 + int(i)


def rpc_stop_command() -> str:
    """Kill only the PID we recorded, and only if it is ggml-rpc-server."""
    return (
        f"if [ -f {RPC_PID} ]; then p=$(cat {RPC_PID}); "
        "if ps -p \"$p\" -o command= 2>/dev/null | grep -q ggml-rpc-server; then "
        "kill \"$p\"; for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 \"$p\" 2>/dev/null || break; sleep 0.3; done; "
        "kill -0 \"$p\" 2>/dev/null && kill -9 \"$p\"; fi; "
        f"rm -f {RPC_PID}; fi"
    )


def parse_pid(stdout: str) -> Optional[int]:
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("PID:") and line[4:].isdigit():
            return int(line[4:])
    return None


def usage_from_timings(usage: Optional[dict], timings: Optional[dict]) -> Optional[dict]:
    """llama-server streams `timings` (ms); map them onto usage.caravan seconds
    so the stats line reads the same as MLX: Read (prefill) / Write (decode)."""
    if not timings:
        return usage
    u = dict(usage or {})
    pn = timings.get("prompt_n")
    pms = timings.get("prompt_ms")
    dn = timings.get("predicted_n")
    dms = timings.get("predicted_ms")
    u.setdefault("prompt_tokens", pn)
    u.setdefault("completion_tokens", dn)
    cv = dict(u.get("caravan") or {})
    if pms is not None:
        cv.setdefault("prefill_s", round(pms / 1000.0, 4))
        cv.setdefault("ttft_s", round(pms / 1000.0, 4))
    if pms is not None and dms is not None:
        cv.setdefault("total_s", round((pms + dms) / 1000.0, 4))
    cv.setdefault("how", "llama.cpp")
    u["caravan"] = cv
    return u
