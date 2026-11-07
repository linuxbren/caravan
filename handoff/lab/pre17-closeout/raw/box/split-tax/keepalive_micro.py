#!/usr/bin/env python3
"""Compare decode step with/without GPU keepalive on live packer."""
from __future__ import annotations
import json, os, statistics, sys, time
from pathlib import Path

def med(xs): return round(statistics.median(xs), 3)

def run(peer, model_dir, use_warm, n=64, prefill=32):
    import mlx.core as mx
    import mlx_split as S
    stage = S.Stage(model_dir, "head", None)
    client = S.FrontClient(peer)
    if use_warm:
        client.enable_gpu_keepalive(mx)
    hello = client.call("hello", proto=S.PROTO)[0]
    assert hello.get("range") == [0, stage.range[0]]
    cache = stage.make_cache()
    pref = list(range(1000, 1000+prefill))
    rh, rp = client.call("fwd", tokens=pref, ctx="scratch", new=True)
    h = S.array_from(mx, rh, rp)
    h = stage.run_layers(h, cache)
    logits = stage.logits(h)
    mx.eval(logits, [c.state for c in cache])
    rows=[]
    tok=2000
    for i in range(n):
        t0=time.perf_counter()
        rh, rp = client.call("fwd", tokens=[tok], ctx="scratch", new=False)
        t_rpc=(time.perf_counter()-t0)*1000
        t1=time.perf_counter()
        h = S.array_from(mx, rh, rp)
        h = stage.run_layers(h, cache)
        logits = stage.logits(h)
        mx.eval(logits, [c.state for c in cache])
        tok = int(mx.argmax(logits[0,-1]).item())
        t_lead=(time.perf_counter()-t1)*1000
        rows.append({"rpc":t_rpc,"packer_s":float(rh.get("_s",0))*1000,"lead":t_lead,"total":t_rpc+t_lead})
    client.close()
    return {k: med([r[k] for r in rows]) for k in rows[0]}

def main():
    peer, model, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    # first without (packer may still have keepalive from worker — disable by using
    # a probe that only warms lead). For clean A/B restart packer without keepalive.
    cold = run(peer, model, False)
    warm = run(peer, model, True)
    result={"host":os.uname().nodename,"cold_lead_only":cold,"warm_lead":warm}
    out.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))

if __name__=="__main__":
    main()
