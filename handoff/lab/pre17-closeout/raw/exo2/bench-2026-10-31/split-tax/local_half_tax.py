#!/usr/bin/env python3
"""One-Mini half breakdown with the same instrumented front_forward / lead path."""
from __future__ import annotations
import json, os, statistics, sys, time
from pathlib import Path

def med(xs):
    return round(statistics.median(xs), 3)

def main():
    model_dir = Path(sys.argv[1]).expanduser().resolve()
    out = Path(sys.argv[2]).expanduser()
    N = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    W = int(sys.argv[4]) if len(sys.argv) > 4 else 5
    PREFILL = 32
    import mlx.core as mx
    import mlx_split as S

    print("packer Stage...", flush=True)
    front = S.Stage(model_dir, "front", None)
    fcache = front.make_cache()
    pref = list(range(1000, 1000 + PREFILL))
    front.front_forward(pref, fcache)
    rows_p = []
    for i in range(W + N):
        # capture tax from return header
        # need to call front_forward and read _tax — it's in the header
        # Modify: front_forward returns hdr with _tax
        hdr, payload = front.front_forward([2000], fcache)
        if i >= W:
            rows_p.append({"payload_bytes": len(payload), **(hdr.get("_tax") or {})})

    print("lead Stage...", flush=True)
    # produce one real H via packer for deser+lead path, and also zeros path
    hdr, payload = front.front_forward([2000], fcache)
    del front, fcache

    head = S.Stage(model_dir, "head", None)
    hcache = head.make_cache()
    # warm with deser path
    for _ in range(PREFILL):
        tax = {}
        h = S.array_from(mx, hdr, payload, tax=tax)
        out_h = head.run_layers(h, hcache)
        logits = head.logits(out_h)
        mx.eval(logits, [c.state for c in hcache])

    rows_l = []
    for i in range(W + N):
        tax = {}
        t0 = time.perf_counter()
        h = S.array_from(mx, hdr, payload, tax=tax)
        t1 = time.perf_counter()
        out_h = head.run_layers(h, hcache)
        logits = head.logits(out_h)
        t2 = time.perf_counter()
        mx.eval(logits, [c.state for c in hcache])
        t3 = time.perf_counter()
        _ = int(mx.argmax(logits[0, -1]).item())
        t4 = time.perf_counter()
        if i >= W:
            rows_l.append({
                **tax,
                "lead_graph_ms": round((t2 - t1) * 1000, 3),
                "lead_eval_ms": round((t3 - t2) * 1000, 3),
                "sample_ms": round((t4 - t3) * 1000, 3),
                "lead_total_ms": round((t4 - t0) * 1000, 3),
                "deser_block_ms": round((t1 - t0) * 1000, 3),
            })

    # zeros baseline (like overhead_bench)
    H = int((hdr.get("shape") or [1,1,1])[-1])
    z = mx.zeros((1, 1, H), dtype=mx.bfloat16)
    mx.eval(z)
    zcache = head.make_cache()
    for _ in range(PREFILL):
        o = head.run_layers(z, zcache)
        lg = head.logits(o)
        mx.eval(lg, [c.state for c in zcache])
    rows_z = []
    for i in range(W + N):
        t0 = time.perf_counter()
        o = head.run_layers(z, zcache)
        lg = head.logits(o)
        mx.eval(lg, [c.state for c in zcache])
        if i >= W:
            rows_z.append({"zeros_lead_ms": round((time.perf_counter() - t0) * 1000, 3)})

    def summ(rows):
        keys = sorted({k for r in rows for k, v in r.items() if isinstance(v, (int, float))})
        out = {}
        for k in keys:
            xs = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
            out[k] = {"median": med(xs), "min": round(min(xs), 3), "max": round(max(xs), 3)}
        return out

    result = {
        "model": model_dir.name,
        "host": os.uname().nodename,
        "n": N,
        "packer": summ(rows_p),
        "lead_from_bytes": summ(rows_l),
        "lead_zeros": summ(rows_z),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["packer"], indent=2))
    print(json.dumps(result["lead_from_bytes"], indent=2))
    print(json.dumps(result["lead_zeros"], indent=2))
    print("wrote", out)

if __name__ == "__main__":
    main()
