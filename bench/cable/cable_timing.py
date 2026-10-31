"""Cable-timing microbenchmark for the split-each-layer (tensor-parallel)
plan in docs/ROADMAP.md ("Beating the turn-taking in the split", idea 4).

Measures round trips between two Macs: the lead sends N bytes and gets N
bytes back, as one per-layer exchange would (each side sends its partial
result and receives the other's). Two paths:

  caravan  Caravan's own split link: the same framing (agent/mlx_split.py
           encode_frame / read_frame), the same client (FrontClient, with
           TCP_NODELAY) and the same server loop (serve_front) as v3.
  raw      Plain TCP, TCP_NODELAY, an 8-byte length prefix, no JSON.

Optional --gpu-sync (caravan path, needs mlx): both sides turn the bytes
into an MLX array and evaluate one tiny op before replying/sending, so
the round trip includes a GPU sync like a real exchange would.

Also measures bulk throughput (1 MiB frames, one way, acked at the end).

No models are loaded. Usage:

  # on the packer Mac
  python3 bench/cable/cable_timing.py serve --listen 169.254.x.y:5570 [--gpu-sync]
  # on the lead Mac
  python3 bench/cable/cable_timing.py run --peer 169.254.x.y:5570 [--gpu-sync] \
      [--repeats 2000] [--json out.json]

The raw server listens on the next port (5571). Stop the server with Ctrl-C.
"""
import argparse
import json
import socket
import statistics
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
import mlx_split as S  # noqa: E402

# Per-layer exchange sizes, hidden_size x batch x 2 bytes (bf16), from each
# model's config.json, plus generic sizes.
MODELS = {"Qwen3 30B-A3B": (2048, 48), "Gemma 4 26B-A4B": (2816, 30), "GPT-OSS 20B": (2880, 24)}
BATCHES = (1, 4, 16)
GENERIC = (1 << 10, 4 << 10, 16 << 10, 64 << 10, 256 << 10, 1 << 20)


def _gpu_touch(payload):
    import mlx.core as mx
    a = mx.array(memoryview(payload), dtype=mx.uint8) if payload else mx.zeros((1,), dtype=mx.uint8)
    mx.eval(a + 1)


class EchoState:
    """Stands in for FrontState: answers hello like the packer does, and
    echoes 'x' payloads back (after a GPU touch with --gpu-sync)."""

    def __init__(self, gpu_sync=False):
        self.epoch = "cable-bench"
        self.gpu_sync = gpu_sync
        self.bulk = 0

    def handle(self, h, p):
        op = h.get("op")
        if op == "hello":
            return {"proto": S.PROTO, "epoch": self.epoch, "stage": "bench", "range": [0, 0], "n_layers": 0}, b""
        if op == "x":
            if self.gpu_sync:
                _gpu_touch(p)
            return {}, p
        if op == "bulk":          # one-way: count, reply only when asked
            self.bulk += len(p)
            return {"n": self.bulk}, b""
        return {"error": f"unknown op {op!r}"}, b""


def _recv_exact(sock, n):
    return S._recv_exact(sock, n)


def raw_server(host, port, stop):
    srv = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    srv.settimeout(1.0)
    while not stop.is_set():
        try:
            c, _ = srv.accept()
        except socket.timeout:
            continue
        c.settimeout(None)
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            while True:
                (n,) = struct.unpack(">Q", _recv_exact(c, 8))
                c.sendall(struct.pack(">Q", n) + _recv_exact(c, n))
        except (ConnectionError, OSError):
            c.close()
    srv.close()


def serve(a):
    host, port = S._hostport(a.listen)
    stop = threading.Event()
    threading.Thread(target=raw_server, args=(host, port + 1, stop), daemon=True).start()
    try:
        S.serve_front(a.listen, EchoState(a.gpu_sync), stop=stop)
    except KeyboardInterrupt:
        stop.set()


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def summarize(ts):
    us = [t * 1e6 for t in ts]
    return {"median_us": round(statistics.median(us), 1), "p95_us": round(pct(us, 0.95), 1),
            "p99_us": round(pct(us, 0.99), 1), "min_us": round(min(us), 1), "n": len(us)}


def time_caravan(client, n, repeats, warmup, gpu_sync):
    payload = b"\x01" * n
    out = []
    for i in range(warmup + repeats):
        t0 = time.perf_counter()
        if gpu_sync:
            _gpu_touch(payload)
        rh, rp = client.call("x", payload)
        dt = time.perf_counter() - t0
        assert len(rp) == n
        if i >= warmup:
            out.append(dt)
    return out


def time_raw(sock, n, repeats, warmup):
    payload = struct.pack(">Q", n) + b"\x01" * n
    out = []
    for i in range(warmup + repeats):
        t0 = time.perf_counter()
        sock.sendall(payload)
        (m,) = struct.unpack(">Q", _recv_exact(sock, 8))
        _recv_exact(sock, m)
        dt = time.perf_counter() - t0
        if i >= warmup:
            out.append(dt)
    return out


def bulk(client, total_mb=256, frame=1 << 20):
    payload = b"\x02" * frame
    client.call("bulk", b"")
    t0 = time.perf_counter()
    sent = 0
    for _ in range(total_mb):      # each call waits for a tiny ack, so this is one-way MB/s
        client.call("bulk", payload)
        sent += frame
    dt = time.perf_counter() - t0
    return {"mb": total_mb, "seconds": round(dt, 3), "MB_per_s": round(sent / dt / 1e6, 1)}


def run(a):
    host, port = S._hostport(a.peer)
    client = S.FrontClient(a.peer)
    client.call("x", b"")
    raw = socket.create_connection((host, port + 1), timeout=10)
    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sizes = {}
    for name, (hidden, layers) in MODELS.items():
        for b in BATCHES:
            sizes.setdefault(hidden * b * 2, []).append(f"{name} batch {b}")
    for n in GENERIC:
        sizes.setdefault(n, []).append("generic")
    rows = []
    for n in sorted(sizes):
        reps = a.repeats if n <= (256 << 10) else max(200, a.repeats // 10)
        c = summarize(time_caravan(client, n, reps, a.warmup, a.gpu_sync))
        r = summarize(time_raw(raw, n, reps, a.warmup))
        rows.append({"bytes": n, "what": sizes[n], "caravan": c, "raw": r})
        print(f"{n:>9,} B  caravan median {c['median_us']:>8.1f} us p95 {c['p95_us']:>8.1f}  "
              f"raw median {r['median_us']:>8.1f} us p95 {r['p95_us']:>8.1f}  ({', '.join(sizes[n])})", flush=True)
    bw = bulk(client)
    print(f"bulk one-way, 1 MiB frames: {bw['MB_per_s']} MB/s ({bw['mb']} MB in {bw['seconds']} s)")
    est = []
    for name, (hidden, layers) in MODELS.items():
        for b in BATCHES:
            row = next(x for x in rows if x["bytes"] == hidden * b * 2)
            for path in ("caravan", "raw"):
                est.append({"model": name, "batch": b, "path": path, "layers": layers,
                            "cable_ms_median": round(layers * 2 * row[path]["median_us"] / 1000, 2),
                            "cable_ms_p95": round(layers * 2 * row[path]["p95_us"] / 1000, 2)})
    out = {"peer": a.peer, "gpu_sync": a.gpu_sync, "repeats": a.repeats, "warmup": a.warmup,
           "when": time.strftime("%Y-%m-%d %H:%M:%S %z"), "rows": rows, "bulk": bw, "cable_per_token": est}
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    client.close()
    raw.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--listen", required=True)
    s.add_argument("--gpu-sync", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--peer", required=True)
    r.add_argument("--gpu-sync", action="store_true")
    r.add_argument("--repeats", type=int, default=2000)
    r.add_argument("--warmup", type=int, default=100)
    r.add_argument("--json")
    a = ap.parse_args(argv)
    return serve(a) if a.cmd == "serve" else run(a)


if __name__ == "__main__":
    main()
