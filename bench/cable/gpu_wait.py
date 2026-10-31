"""GPU-wait test for splitting each layer across both Minis (ROADMAP idea 4,
follow-up to cable_timing.py).

Both Macs run the same loop at the same time, the way split-each-layer
would: for every layer, each Mac computes its half of the attention part
and then its half of the feed-forward (MoE) part on the GPU, waits for it
(mx.eval), sends its partial result (hidden_size x batch bf16) to the other
Mac over Caravan's link framing (agent/mlx_split.py encode_frame /
read_frame, TCP_NODELAY), receives the other's, and adds both into the
hidden state. Two exchanges per layer.

The GPU work is synthetic but sized like the real models (4-bit quantized
weights, a different set of weights for every layer, half of the attention
projections and half of the active experts' intermediate size per Mac; at
batch B the experts touched are the expected number of distinct experts for
B tokens). No model is loaded. Attention over the chat history (KV cache)
is not modelled, nor routing.

Modes, timed per token (one pass over all layers):
  compute   all segments queued lazily, one mx.eval per token (no waits)
  sync      mx.eval after every segment + copy to bytes and back, no cable
  exchange  sync + swap partials with the other Mac (the real pattern)
  net       swap partials only, no GPU work
  overlap   (batch >= 2) two micro-batches: queue both, wait for the first,
            send it while the GPU finishes the second (mx.async_eval)

Usage (same command on both Macs except role/address):
  packer:  python3 bench/cable/gpu_wait.py packer --listen 169.254.x.y:5572
  lead:    python3 bench/cable/gpu_wait.py lead --peer 169.254.x.y:5572 --json out.json
"""
import argparse
import json
import socket
import statistics
import sys
import time
from pathlib import Path

import mlx.core as mx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
import mlx_split as S  # noqa: E402

# From each model's config.json.
MODELS = {
    "qwen3-30b-a3b": dict(hidden=2048, layers=48, q=32 * 128, kv=4 * 128, experts=128, k=8, inter=768, dense=0),
    "gemma4-26b-a4b": dict(hidden=2816, layers=30, q=16 * 256, kv=8 * 256, experts=128, k=8, inter=704, dense=2112),
    "gpt-oss-20b": dict(hidden=2880, layers=24, q=64 * 64, kv=8 * 64, experts=32, k=4, inter=2880, dense=0),
}
GS, BITS = 64, 4


def distinct_experts(m, batch):
    e, k = m["experts"], m["k"]
    return max(k, round(e * (1 - (1 - k / e) ** batch)))


def qweight(out_dim, in_dim):
    w = mx.random.normal((out_dim, in_dim), scale=in_dim ** -0.5).astype(mx.bfloat16)
    q = mx.quantize(w, group_size=GS, bits=BITS)
    mx.eval(*q)
    return q


def qmm(x, q):
    return mx.quantized_matmul(x, *q, transpose=True, group_size=GS, bits=BITS)


class Half:
    """One Mac's half of every layer."""

    def __init__(self, name, batch):
        m = MODELS[name]
        self.m, self.batch, self.h = m, batch, m["hidden"]
        ffn = (distinct_experts(m, batch) * m["inter"] + m["dense"]) // 2
        ffn = (ffn + GS - 1) // GS * GS
        qkv = (m["q"] + 2 * m["kv"]) // 2
        self.layers = []
        for _ in range(m["layers"]):
            self.layers.append(dict(
                n1=mx.ones((self.h,), dtype=mx.bfloat16), n2=mx.ones((self.h,), dtype=mx.bfloat16),
                qkv=qweight(qkv, self.h), o=qweight(self.h, m["q"] // 2),
                gu=qweight(2 * ffn, self.h), down=qweight(self.h, ffn)))
        self.ffn = ffn
        self.weight_bytes = sum(a.nbytes for L in self.layers for k in ("qkv", "o", "gu", "down") for a in L[k])

    def attn(self, L, x):
        y = qmm(mx.fast.rms_norm(x, L["n1"], 1e-6), L["qkv"])
        return qmm(y[..., : self.m["q"] // 2], L["o"])      # stand-in for attention over the cache

    def ffn_part(self, L, x):
        gu = qmm(mx.fast.rms_norm(x, L["n2"], 1e-6), L["gu"])
        g, u = gu[..., : self.ffn], gu[..., self.ffn:]
        return qmm(nn_silu(g) * u, L["down"])

    def segments(self):
        for L in self.layers:
            yield lambda x, L=L: self.attn(L, x)
            yield lambda x, L=L: self.ffn_part(L, x)


def nn_silu(x):
    return x * mx.sigmoid(x)


def to_bytes(a):
    return bytes(memoryview(a.view(mx.uint16)))


def from_bytes(b, shape):
    return mx.array(memoryview(b), dtype=mx.uint8).view(mx.bfloat16).reshape(shape)


def send(sock, payload):
    sock.sendall(S.encode_frame({"op": "p"}, payload))


def recv(sock):
    return S.read_frame(sock)[1]


def token(half, mode, x, sock):
    shape = x.shape
    if mode == "compute":
        for seg in half.segments():
            x = x + 2 * seg(x)
        mx.eval(x)
        return x
    if mode == "net":
        z = to_bytes(x)
        for _ in range(2 * half.m["layers"]):
            send(sock, z)
            recv(sock)
        return x
    if mode == "overlap":
        a, b = x[: shape[0] // 2], x[shape[0] // 2:]
        for seg in half.segments():
            pa, pb = seg(a), seg(b)
            mx.async_eval(pa, pb)
            mx.eval(pa)
            send(sock, to_bytes(pa))
            mx.eval(pb)
            send(sock, to_bytes(pb))
            qa, qb = from_bytes(recv(sock), pa.shape), from_bytes(recv(sock), pb.shape)
            a, b = a + pa + qa, b + pb + qb
        mx.eval(a, b)
        return mx.concatenate([a, b])
    for seg in half.segments():
        p = seg(x)
        mx.eval(p)
        z = to_bytes(p)
        if mode == "sync":
            other = from_bytes(z, shape)
        else:
            send(sock, z)
            other = from_bytes(recv(sock), shape)
        x = x + p + other
    mx.eval(x)
    return x


def run_mode(half, mode, tokens, warmup, sock):
    x = mx.random.normal((half.batch, half.h)).astype(mx.bfloat16) * 0.1
    mx.eval(x)
    ts = []
    for i in range(warmup + tokens):
        t0 = time.perf_counter()
        x = token(half, mode, x, sock)
        x = mx.fast.rms_norm(x, half.layers[0]["n1"], 1e-6)   # keep values sane between tokens
        dt = time.perf_counter() - t0
        if i >= warmup:
            ts.append(dt)
    return ts


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def stats_ms(ts):
    return {"median_ms": round(statistics.median(ts) * 1e3, 3), "p95_ms": round(pct(ts, 0.95) * 1e3, 3), "n": len(ts)}


def plan(models, batches):
    for name in models:
        for b in batches:
            yield name, b


def packer(a):
    host, port = S._hostport(a.listen)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    c, _ = srv.accept()
    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    half = None
    while True:
        h, _ = S.read_frame(c)
        if h["op"] == "quit":
            break
        if h["op"] == "build":
            half = None
            mx.clear_cache()
            half = Half(h["model"], h["batch"])
            c.sendall(S.encode_frame({"op": "ready"}, b""))
        elif h["op"] == "mode":
            ts = run_mode(half, h["mode"], h["tokens"], h["warmup"], c)
            c.sendall(S.encode_frame({"op": "done", "stats": stats_ms(ts)}, b""))
    c.close()
    srv.close()


def lead(a):
    host, port = S._hostport(a.peer)
    c = socket.create_connection((host, port), timeout=600)
    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    results = []
    for name, b in plan(a.models.split(","), [int(x) for x in a.batches.split(",")]):
        t0 = time.time()
        c.sendall(S.encode_frame({"op": "build", "model": name, "batch": b}, b""))
        half = Half(name, b)
        assert S.read_frame(c)[0]["op"] == "ready"
        n_ex = 2 * half.m["layers"]
        row = {"model": name, "batch": b, "exchanges_per_token": n_ex, "bytes_per_exchange": b * half.h * 2,
               "weights_gb_per_mac": round(half.weight_bytes / 1e9, 2), "distinct_experts": distinct_experts(half.m, b),
               "build_s": round(time.time() - t0, 1), "modes": {}}
        modes = ["compute", "sync", "net", "exchange"] + (["overlap"] if b >= 2 else [])
        for mode in modes:
            c.sendall(S.encode_frame({"op": "mode", "mode": mode, "tokens": a.tokens, "warmup": a.warmup}, b""))
            ts = run_mode(half, mode, a.tokens, a.warmup, c)
            ph = S.read_frame(c)[0]
            row["modes"][mode] = {"lead": stats_ms(ts), "packer": ph["stats"], "lead_raw_ms": [round(t * 1e3, 4) for t in ts]}
        md = {k: v["lead"] for k, v in row["modes"].items()}
        base = md["compute"]["median_ms"]
        row["per_exchange_us"] = {k: {"median": round((md[k]["median_ms"] - base) * 1e3 / n_ex, 1),
                                      "p95": round((md[k]["p95_ms"] - base) * 1e3 / n_ex, 1)}
                                  for k in md if k != "compute"}
        row["per_exchange_us"]["net"] = {"median": round(md["net"]["median_ms"] * 1e3 / n_ex, 1),
                                         "p95": round(md["net"]["p95_ms"] * 1e3 / n_ex, 1)}
        results.append(row)
        print(f"{name} batch {b}: weights {row['weights_gb_per_mac']} GB/Mac, " +
              ", ".join(f"{k} {v['median_ms']:.2f} ms (p95 {v['p95_ms']:.2f})" for k, v in md.items()) +
              " | per exchange beyond compute: " +
              ", ".join(f"{k} {v['median']} us (p95 {v['p95']})" for k, v in row["per_exchange_us"].items()), flush=True)
        del half
        mx.clear_cache()
    c.sendall(S.encode_frame({"op": "quit"}, b""))
    c.close()
    out = {"peer": a.peer, "tokens": a.tokens, "warmup": a.warmup, "mlx": mx.__version__,
           "when": time.strftime("%Y-%m-%d %H:%M:%S %z"), "results": results}
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("packer")
    p.add_argument("--listen", required=True)
    l = sub.add_parser("lead")
    l.add_argument("--peer", required=True)
    l.add_argument("--models", default=",".join(MODELS))
    l.add_argument("--batches", default="1,4")
    l.add_argument("--tokens", type=int, default=200)
    l.add_argument("--warmup", type=int, default=20)
    l.add_argument("--json")
    a = ap.parse_args(argv)
    return packer(a) if a.cmd == "packer" else lead(a)


if __name__ == "__main__":
    main()
