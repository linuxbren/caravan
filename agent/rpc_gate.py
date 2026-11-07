#!/usr/bin/env python3
"""Allowlisting front door for llama.cpp's ggml-rpc-server.

ggml-rpc-server has no auth ("never expose the RPC server to an open
network"). Caravan runs it bound to 127.0.0.1 only and puts this gate on
the Mini-to-Mini link address. The gate accepts a TCP connection only when
the peer's IP is in the allowlist (Caravan's topology Minis) and otherwise
closes it immediately. No sudo, no pf, works for any number of Minis.

    rpc_gate.py --listen 169.254.103.191:50052 --allow 169.254.126.240 \
        -- ~/dev/llama.cpp/build/bin/ggml-rpc-server -d MTL0 -p 50053 -c

Everything after `--` is the rpc-server command; the gate adds
`-H 127.0.0.1` itself (and refuses a command that sets -H/--host), spawns
it as a child, forwards allowed connections to 127.0.0.1:<its -p>, and
stops it on SIGTERM/SIGINT. One PID to track. Listen host 0.0.0.0 / :: is
refused unless --i-know-listen-any is given.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import signal
import socket
import subprocess
import sys
import threading
import time

BUF = 1 << 20


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S") + " [rpc-gate] " + msg, flush=True)


def parse_hostport(s: str):
    host, _, port = s.rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"bad host:port {s!r}")
    return host.strip("[]"), int(port)


def is_any(host: str) -> bool:
    return host in ("0.0.0.0", "::", "", "*")


def child_port(cmd: list) -> int:
    for i, a in enumerate(cmd):
        if a in ("-H", "--host"):
            raise ValueError("rpc-server command must not set -H; the gate binds it to 127.0.0.1")
    for i, a in enumerate(cmd):
        if a in ("-p", "--port") and i + 1 < len(cmd):
            return int(cmd[i + 1])
    return 50052


def allowed(ip: str, allow: set) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return str(a) in allow


def pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            b = src.recv(BUF)
            if not b:
                break
            dst.sendall(b)
    except OSError:
        pass
    finally:
        for s in (dst, src):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def handle(conn: socket.socket, target) -> None:
    try:
        up = socket.create_connection(target, timeout=10)
    except OSError as e:
        log(f"rpc-server not reachable on {target}: {e}")
        conn.close()
        return
    up.settimeout(None)
    for s in (conn, up):
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
    t = threading.Thread(target=pipe, args=(up, conn), daemon=True)
    t.start()
    pipe(conn, up)
    t.join()
    conn.close()
    up.close()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("usage: rpc_gate.py --listen HOST:PORT --allow IP[,IP...] -- rpc-server args", file=sys.stderr)
        return 2
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", required=True)
    ap.add_argument("--allow", required=True, help="comma-separated peer IPs")
    ap.add_argument("--i-know-listen-any", action="store_true")
    a = ap.parse_args(argv[:i])
    cmd = argv[i + 1:]
    host, port = parse_hostport(a.listen)
    if is_any(host) and not a.i_know_listen_any:
        log("refusing to listen on all interfaces; give the Mini-to-Mini link address")
        return 2
    allow = {s.strip() for s in a.allow.split(",") if s.strip()}
    if not allow:
        log("empty allowlist; refusing to start")
        return 2
    try:
        cport = child_port(cmd)
    except ValueError as e:
        log(str(e))
        return 2
    if cport == port:
        log("rpc-server port must differ from the gate port")
        return 2
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    srv = socket.socket(fam, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((host, port))
    except OSError as e:
        log(f"cannot bind {host}:{port}: {e}")
        return 3
    srv.listen(16)
    child = subprocess.Popen(cmd + ["-H", "127.0.0.1"])
    log(f"listening on {host}:{port}, allow {sorted(allow)}, rpc-server pid {child.pid} on 127.0.0.1:{cport}")

    def stop(*_):
        try:
            child.terminate()
            child.wait(timeout=5)
        except Exception:
            child.kill()
        os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def watch():
        child.wait()
        log(f"rpc-server exited rc={child.returncode}")
        os._exit(1)
    threading.Thread(target=watch, daemon=True).start()

    while True:
        conn, addr = srv.accept()
        if not allowed(addr[0], allow):
            log(f"refused {addr[0]} (not a Caravan peer)")
            conn.close()
            continue
        log(f"accepted {addr[0]}")
        threading.Thread(target=handle, args=(conn, ("127.0.0.1", cport)), daemon=True).start()


if __name__ == "__main__":
    sys.exit(main())
