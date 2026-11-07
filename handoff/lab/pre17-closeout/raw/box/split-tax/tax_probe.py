#!/usr/bin/env python3
"""Fine-grained split tax probe: live packer + in-process lead Stage.

Expects instrumented mlx_split on sys.path (agent/ with tax patch).
Usage:
  tax_probe.py PEER MODEL_DIR OUT.json [N=64] [PREFILL=32]
"""
from __future__ import annotations
import json, os, statistics, sys, time
from pathlib import Path

def med(xs):
    return round(statistics.median(xs), 3) if xs else None

def main():
    peer = sys.argv[1]
    model_dir = Path(sys.argv[2]).expanduser().resolve()
    out = Path(sys.argv[3]).expanduser()
    N = int(sys.argv[4]) if len(sys.argv) > 4 else 64
    PREFILL = int(sys.argv[5]) if len(sys.argv) > 5 else 32

    import mlx.core as mx
    import mlx_split as S

    print("load lead Stage...", flush=True)
    stage = S.Stage(model_dir, "head", None)
    client = S.FrontClient(peer)
    hello = client.call("hello", proto=S.PROTO)[0]
    print("packer", hello.get("stage"), hello.get("range"), flush=True)
    assert hello.get("range") == [0, stage.range[0]], (hello.get("range"), stage.range)

    cache = stage.make_cache()
    pref = list(range(1000, 1000 + PREFILL))
    # prefill via scratch then end; then decode on a fresh scratch that we keep
    rh, rp = client.call("fwd", tokens=pref, ctx="scratch", new=True)
    h = S.array_from(mx, rh, rp)
    h = stage.run_layers(h, cache)
    logits = stage.logits(h)
    mx.eval(logits, [c.state for c in cache])
    # keep using same scratch on packer (new=False) + same lead cache for decode
    # Restart scratch session for clean decode timing matching overhead_bench style:
    client.call("end_scratch")
    # New scratch for decode; prefill again into both caches
    cache = stage.make_cache()
    rh, rp = client.call("fwd", tokens=pref, ctx="scratch", new=True)
    h = S.array_from(mx, rh, rp)
    h = stage.run_layers(h, cache)
    logits = stage.logits(h)
    mx.eval(logits, [c.state for c in cache])

    rows = []
    tok = 2000
    for i in range(N):
        row = {"i": i}
        t0 = time.perf_counter()
        toks = [tok]
        row["tolist_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        t1 = time.perf_counter()
        # encode+send measured inside by splitting _roundtrip manually
        header = {"op": "fwd", "tokens": toks, "ctx": "scratch", "new": False}
        client._ensure()
        t_enc0 = time.perf_counter()
        data = S.encode_frame(header, b"")
        row["lead_encode_ms"] = round((time.perf_counter() - t_enc0) * 1000, 3)
        t_send0 = time.perf_counter()
        client.sock.sendall(data)
        row["lead_send_ms"] = round((time.perf_counter() - t_send0) * 1000, 3)
        t_recv0 = time.perf_counter()
        rh, rp = S.read_frame(client.sock)
        row["lead_recv_wait_ms"] = round((time.perf_counter() - t_recv0) * 1000, 3)
        row["rpc_wait_ms"] = round((time.perf_counter() - t1) * 1000, 3)
        row["packer_s_ms"] = round(float(rh.get("_s", 0.0)) * 1000, 3)
        row["packer_tax"] = rh.get("_tax")
        if "error" in rh:
            raise RuntimeError(rh["error"])
        # update client stats like _roundtrip
        st = client.stats
        st["calls"] += 1
        st["bytes_out"] += len(data)
        st["bytes_in"] += 12 + len(rp) + len(json.dumps(rh))
        st["wait_s"] += row["rpc_wait_ms"] / 1000.0
        st["front_s"] += float(rh.get("_s", 0.0))

        tax = {}
        t2 = time.perf_counter()
        h = S.array_from(mx, rh, rp, tax=tax)
        row["deser"] = {k: tax[k] for k in tax}
        row["deser_ms"] = tax.get("deser_ms")

        t3 = time.perf_counter()
        h2 = stage.run_layers(h, cache)
        logits = stage.logits(h2)
        row["lead_graph_ms"] = round((time.perf_counter() - t3) * 1000, 3)
        t4 = time.perf_counter()
        mx.eval(logits, [c.state for c in cache])
        row["lead_eval_ms"] = round((time.perf_counter() - t4) * 1000, 3)
        t5 = time.perf_counter()
        tok = int(mx.argmax(logits[0, -1]).item())
        row["sample_ms"] = round((time.perf_counter() - t5) * 1000, 3)
        row["lead_total_ms"] = round((time.perf_counter() - t2) * 1000, 3)
        row["step_total_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        rows.append(row)
        if i < 3 or i == N - 1:
            pt = row.get("packer_tax") or {}
            print(f"  i={i} rpc={row['rpc_wait_ms']:.2f} packer_s={row['packer_s_ms']:.2f} "
                  f"eval={pt.get('eval_ms')} ser={pt.get('ser_ms')} deser={row['deser_ms']} "
                  f"lead_eval={row['lead_eval_ms']} sample={row['sample_ms']} total={row['step_total_ms']:.2f}",
                  flush=True)

    def flatten_keys(rows):
        keys = set()
        for r in rows:
            keys.update(k for k, v in r.items() if isinstance(v, (int, float)))
            if r.get("packer_tax"):
                keys.update("packer." + k for k, v in r["packer_tax"].items() if isinstance(v, (int, float)))
            if r.get("deser"):
                keys.update("deser." + k for k, v in r["deser"].items() if isinstance(v, (int, float)))
        return sorted(keys)

    def vals(key):
        outv = []
        for r in rows:
            if key.startswith("packer."):
                v = (r.get("packer_tax") or {}).get(key[7:])
            elif key.startswith("deser."):
                v = (r.get("deser") or {}).get(key[6:])
            else:
                v = r.get(key)
            if isinstance(v, (int, float)):
                outv.append(v)
        return outv

    keys = flatten_keys(rows)
    summary = {k: {"median": med(vals(k)), "p90": (sorted(vals(k))[int(0.9*(len(vals(k))-1))] if vals(k) else None),
                   "min": round(min(vals(k)), 3) if vals(k) else None,
                   "max": round(max(vals(k)), 3) if vals(k) else None} for k in keys}

    result = {
        "model": model_dir.name,
        "peer": peer,
        "n": N,
        "prefill": PREFILL,
        "host": os.uname().nodename,
        "mlx": getattr(mx, "__version__", "?"),
        "lead_range": list(stage.range),
        "summary_ms": summary,
        "rows": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result) + "\n")
    print("medians (selected):", flush=True)
    for k in ["rpc_wait_ms", "packer_s_ms", "packer.eval_ms", "packer.ser_ms", "packer.after_eval_ser_ms",
              "packer.prev_encode_ms", "packer.prev_send_ms", "deser_ms", "deser.deser_eval_ms",
              "lead_eval_ms", "sample_ms", "lead_total_ms", "step_total_ms",
              "lead_encode_ms", "lead_send_ms", "lead_recv_wait_ms"]:
        if k in summary:
            print(f"  {k}: {summary[k]}", flush=True)
    print("wrote", out, flush=True)
    client.close()

if __name__ == "__main__":
    main()
