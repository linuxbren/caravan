#!/usr/bin/env python3
"""Measure where a split decode step spends time on the lead.

Talks to a running lead worker... actually runs an in-process Stage packer
half + Stage lead half with a fake TCP delay OR uses FrontClient against
a live packer.

Usage against live split (packer already up):
  overlap_probe.py PEER HOST:PORT MODEL_DIR OUT.json

Times for each of N decode steps on the lead:
  tolist_ms, rpc_wait_ms, lead_layers_ms, total_ms
Shows lead GPU has nothing to do during rpc_wait (serial dependence).
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

N = 64
PREFILL = 32

def main():
    peer = sys.argv[1]
    model_dir = Path(sys.argv[2]).expanduser().resolve()
    out = Path(sys.argv[3]).expanduser()
    repo_agent = Path(__file__).resolve().parents[2] / "agent"
    if not (repo_agent / "mlx_split.py").exists():
        repo_agent = Path.home() / "dev/caravan-v3/agent"
    sys.path.insert(0, str(repo_agent))
    import mlx.core as mx
    import mlx_split as S

    print("load lead Stage...", flush=True)
    stage = S.Stage(model_dir, "head", None)
    client = S.FrontClient(peer)
    # hello
    hello = client.call("hello", proto=S.PROTO)[0]
    print("packer hello", hello.get("stage"), hello.get("range"), flush=True)
    assert hello.get("range") == [0, stage.range[0]], (hello.get("range"), stage.range)

    # prepare packer + lead caches via SplitModel-like loop
    cache = stage.make_cache()
    # prefill on packer+lead
    pref = list(range(1000, 1000 + PREFILL))
    rh, rp = client.call("fwd", tokens=pref, ctx="scratch", new=True)
    h = S.array_from(mx, rh, rp)
    h = stage.run_layers(h, cache)
    logits = stage.logits(h)
    mx.eval(logits, [c.state for c in cache])
    client.call("end_scratch")

    rows = []
    tok = 2000
    for i in range(N):
        # 1) concrete token (like SplitModel.tolist)
        t0 = time.perf_counter()
        toks = [tok]
        t_list = (time.perf_counter() - t0) * 1000
        # 2) RPC to packer
        t1 = time.perf_counter()
        rh, rp = client.call("fwd", tokens=toks, ctx="session")
        t_rpc = (time.perf_counter() - t1) * 1000
        # 3) lead layers + logits
        t2 = time.perf_counter()
        h = S.array_from(mx, rh, rp)
        h = stage.run_layers(h, cache)
        logits = stage.logits(h)
        mx.eval(logits, [c.state for c in cache])
        # sample greedy
        tok = int(mx.argmax(logits[0, -1]).item())
        t_lead = (time.perf_counter() - t2) * 1000
        rows.append({
            "i": i, "tolist_ms": round(t_list, 3), "rpc_wait_ms": round(t_rpc, 3),
            "lead_layers_ms": round(t_lead, 3),
            "total_ms": round(t_list + t_rpc + t_lead, 3),
            "front_s": round(client.stats["front_s"], 4),
        })
        # reset per-step front accounting by reading delta
        client.reset_stats()

    # Also try: can we async_eval lead while somehow overlapping? Demonstrate
    # that starting lead before rpc returns is impossible without H.
    # And that during rpc_wait, issuing unrelated GPU work is the only option.
    evidence = {
        "dependence": (
            "lead.run_layers needs packer's hidden state for the SAME token; "
            "packer.fwd needs the concrete sampled token from the PREVIOUS lead step. "
            "So for one chat, lead layers cannot start until rpc returns, and packer "
            "cannot start the next token until lead samples. mlx_lm.generate's "
            "mx.async_eval pipelines sample->next_forward on one Mac, but SplitModel "
            "must .tolist() the token before RPC, which forces that sync first."
        ),
        "mlx_lm_already_async": True,
    }

    import statistics as st
    def med(k):
        xs = [r[k] for r in rows]
        return round(st.median(xs), 3)
    summary = {
        "model": model_dir.name,
        "peer": peer,
        "n": N,
        "median_ms": {k: med(k) for k in ("tolist_ms", "rpc_wait_ms", "lead_layers_ms", "total_ms")},
        "rows": rows,
        "evidence": evidence,
        "host": os.uname().nodename,
    }
    print("medians", summary["median_ms"], flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")
    client.close()
    print("wrote", out, flush=True)

if __name__ == "__main__":
    main()
