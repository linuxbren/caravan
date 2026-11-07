#!/usr/bin/env python3
"""Split a GGUF across Minis from the command line -- same mechanism as the web UI.

    python3 agent/gguf_split_cli.py start --model ~/.caravan/models/X.gguf \
        --peer EXO2=brenden@169.254.103.191 [--peer EXO3=...] [--port 8080]
    python3 agent/gguf_split_cli.py status
    python3 agent/gguf_split_cli.py stop

Each peer: ggml-rpc-server on its own 127.0.0.1 (started over SSH, PID
recorded on the peer). Lead: one SSH tunnel per peer and llama-server
--rpc 127.0.0.1:<tunnel>,... on 127.0.0.1:<port>. No network listener for
rpc-server anywhere (docs/SECURITY.md). Without --peer, peers come from the
web UI's node list (~/.caravan/config.toml [web.nodes.*], default EXO2).
Everything started is recorded in ~/.caravan/cli-gguf.json; stop kills only
those PIDs after checking their command lines.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
import gguf_split as G  # noqa: E402

STATE = Path(os.environ.get("CARAVAN_CLI_GGUF_STATE", "~/.caravan/cli-gguf.json")).expanduser()


def ssh(target, cmd, timeout=40):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, cmd],
                          capture_output=True, text=True, timeout=timeout)


def peers_from_config():
    import web_nodes
    return [(n.get("label") or n["id"], n.get("ssh") or n["host"])
            for n in web_nodes.nodes_from_config() if not web_nodes.is_local(n)]


def free_local():
    r = subprocess.run(["/bin/sh", "-c", G.FREE_RAM_CMD], capture_output=True, text=True)
    return G.parse_free_gb(r.stdout)


def stop(quiet=False) -> int:
    if not STATE.is_file():
        if not quiet:
            print("nothing running (no state file)")
        return 0
    st = json.loads(STATE.read_text())
    pid = st.get("lead_pid")
    if pid and "llama-server" in G.pid_cmdline(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if "llama-server" not in G.pid_cmdline(pid):
                break
            time.sleep(0.3)
        print(f"stopped llama-server {pid}")
    for t in st.get("tunnels") or []:
        if G.is_tunnel_cmd(G.pid_cmdline(t["pid"])):
            os.kill(t["pid"], signal.SIGTERM)
            print(f"closed tunnel {t['pid']} (127.0.0.1:{t['port']})")
    for p in st.get("peers") or []:
        r = ssh(p["ssh"], G.rpc_stop_command(), timeout=30)
        print(f"stopped rpc-server on {p['label']}" + ("" if r.returncode == 0 else f" (rc {r.returncode})"))
    STATE.unlink()
    return 0


def start(a) -> int:
    if STATE.is_file():
        print("already running; stop first", file=sys.stderr)
        return 2
    model = Path(a.model).expanduser()
    if not model.is_file():
        print(f"no such GGUF: {model}", file=sys.stderr)
        return 2
    peers = [tuple(x.split("=", 1)) for x in a.peer] if a.peer else peers_from_config()
    st = {"model": str(model), "port": a.port, "peers": [], "tunnels": [], "lead_pid": None,
          "started": time.strftime("%Y-%m-%d %H:%M:%S %Z")}
    t0 = time.time()
    try:
        rpc, free = [], [free_local()]
        for i, (label, target) in enumerate(peers):
            r = ssh(target, G.rpc_start_command())
            pid = G.parse_pid(r.stdout)
            if not pid:
                raise RuntimeError(f"rpc-server on {label} did not start: {r.stdout[-300:]} {r.stderr[-200:]}")
            st["peers"].append({"label": label, "ssh": target, "pid": pid})
            STATE.write_text(json.dumps(st))
            lp = G.tunnel_port(i)
            tun = subprocess.Popen(G.ssh_tunnel_args(target, lp), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
            st["tunnels"].append({"pid": tun.pid, "port": lp, "ssh": target})
            STATE.write_text(json.dumps(st))
            if not G.wait_port(lp, proc=tun):
                raise RuntimeError(f"SSH tunnel to {label} failed")
            rpc.append(f"127.0.0.1:{lp}")
            fr = ssh(target, G.FREE_RAM_CMD, timeout=15)
            free.append(G.parse_free_gb(fr.stdout))
            print(f"{label}: rpc-server pid {pid}, tunnel 127.0.0.1:{lp}, free {free[-1]} GB")
        shares = G.shares_from_free(free) if rpc else [1]
        args = G.llama_args(str(model), port=a.port, peers=rpc, shares=shares)
        log = Path("~/.caravan/cli-gguf.log").expanduser()
        lp_ = subprocess.Popen(args, stdout=open(log, "wb"), stderr=subprocess.STDOUT, start_new_session=True)
        st["lead_pid"] = lp_.pid
        st["shares"] = shares
        STATE.write_text(json.dumps(st))
        print(f"llama-server pid {lp_.pid} split {':'.join(map(str, shares))}; log {log}")
        while time.time() - t0 < 1200:
            if lp_.poll() is not None:
                raise RuntimeError("llama-server exited: " + log.read_text(errors="replace")[-600:])
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/health", timeout=2) as r:
                    if r.status == 200:
                        print(f"ready in {time.time() - t0:.1f}s on http://127.0.0.1:{a.port}")
                        return 0
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError("timed out")
    except Exception as e:  # noqa: BLE001
        print(f"split failed: {e}", file=sys.stderr)
        stop(quiet=True)
        return 1


def status() -> int:
    if not STATE.is_file():
        print("not running")
        return 0
    st = json.loads(STATE.read_text())
    alive = "llama-server" in G.pid_cmdline(st.get("lead_pid"))
    print(json.dumps({**st, "lead_alive": alive}, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--model", required=True)
    s.add_argument("--peer", action="append", default=[], help="LABEL=ssh-target (repeat)")
    s.add_argument("--port", type=int, default=8080)
    sub.add_parser("stop")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    return {"start": lambda: start(a), "stop": stop, "status": status}[a.cmd]()


if __name__ == "__main__":
    sys.exit(main())
