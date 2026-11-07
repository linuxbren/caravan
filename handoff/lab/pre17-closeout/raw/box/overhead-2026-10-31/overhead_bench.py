#!/usr/bin/env python3
"""Per-pass overhead on one Mini.

Times one decode step (T=1, after a short prefill) with mx.eval sync:
  full   — whole model
  packer — even-cut Packer 1 half (embed + layers 0..K-1)
  lead   — even-cut lead half (layers K..N-1 + norm + lm_head) on a concrete H
  empty  — embed + 1 layer

Usage (from caravan repo root):
  ~/.caravan/venvs/mlx/bin/python bench/overhead/overhead_bench.py MODEL_DIR OUT.json
"""
from __future__ import annotations
import gc, json, os, statistics, sys, time
from pathlib import Path

REPEATS = 30
WARMUP = 5
PREFILL = 32

def med(xs):
    return round(statistics.median(xs), 3)

def p90(xs):
    s = sorted(xs)
    return round(s[int(0.9 * (len(s) - 1))], 3)

def time_steps(fn, repeats=REPEATS, warmup=WARMUP):
    for _ in range(warmup):
        fn()
    xs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000.0)
    return xs

def hidden_size(cfg):
    tc = cfg.get("text_config") or cfg
    for k in ("hidden_size", "n_embd", "d_model"):
        if k in tc:
            return int(tc[k])
    raise KeyError("hidden_size")

def main():
    model_dir = Path(sys.argv[1]).expanduser().resolve()
    out_path = Path(sys.argv[2]).expanduser()
    repeats = int(sys.argv[3]) if len(sys.argv) > 3 else REPEATS
    warmup = int(sys.argv[4]) if len(sys.argv) > 4 else WARMUP

    repo = Path(__file__).resolve().parents[2]  # bench/overhead -> repo
    sys.path.insert(0, str(repo / "agent"))
    import mlx.core as mx
    import mlx_split as S
    from mlx_lm.utils import load_model, maybe_set_recommended_wired_limit
    from mlx_lm.models.cache import make_prompt_cache

    results = {
        "model": model_dir.name,
        "model_dir": str(model_dir),
        "repeats": repeats,
        "warmup": warmup,
        "prefill_tokens": PREFILL,
        "host": os.uname().nodename,
        "mlx": getattr(mx, "__version__", "?"),
    }
    print(f"=== {model_dir.name} on {results['host']}", flush=True)

    # ---- packer half (even cut) ----
    print("  load packer Stage...", flush=True)
    t0 = time.time()
    front = S.Stage(model_dir, "front", None)
    print(f"  packer layers {front.range} of {front.n_layers} in {time.time()-t0:.1f}s, {front.nbytes()/1e9:.2f} GB", flush=True)
    fcache = front.make_cache()
    # prefill
    pref = list(range(1000, 1000 + PREFILL))
    front.front_forward(pref, fcache)
    tok = [2000]
    def packer_step():
        front.front_forward(tok, fcache)
    xs = time_steps(packer_step, repeats, warmup)
    results["packer"] = {
        "range": list(front.range), "n_layers": front.range[1] - front.range[0],
        "ms": {"median": med(xs), "p90": p90(xs), "min": round(min(xs), 3), "max": round(max(xs), 3)},
        "raw_ms": [round(x, 3) for x in xs],
    }
    print(f"  packer half: {results['packer']['ms']['median']} ms med", flush=True)

    # ---- near-empty: embed + 1 layer (reuse front model by running only first layer) ----
    # Rebuild a Stage with front_layers=1
    del front, fcache
    gc.collect()
    print("  load empty Stage (K=1)...", flush=True)
    empty = S.Stage(model_dir, "front", 1)
    ecache = empty.make_cache()
    empty.front_forward(pref, ecache)
    def empty_step():
        empty.front_forward(tok, ecache)
    xs = time_steps(empty_step, repeats, warmup)
    results["empty"] = {
        "range": list(empty.range), "n_layers": 1,
        "ms": {"median": med(xs), "p90": p90(xs), "min": round(min(xs), 3), "max": round(max(xs), 3)},
        "raw_ms": [round(x, 3) for x in xs],
    }
    print(f"  empty (embed+1): {results['empty']['ms']['median']} ms med", flush=True)
    # keep empty briefly to steal a hidden state shape, then free
    rh, rp = None, None
    # produce one H via empty for shape; lead needs full packer H width — same hidden size
    cfg = empty.config if isinstance(empty.config, dict) else dict(empty.config)
    H = hidden_size(cfg)
    del empty, ecache
    gc.collect()

    # ---- lead half ----
    print("  load lead Stage...", flush=True)
    head = S.Stage(model_dir, "head", None)
    print(f"  lead layers {head.range} of {head.n_layers}, {head.nbytes()/1e9:.2f} GB", flush=True)
    hcache = head.make_cache()
    # Need a real hidden state from the packer half for correct shapes/dtypes.
    # Load packer again briefly for one forward, or synthesize bf16 H.
    # Synthesize: bf16 [1,1,H] — layers may be sensitive to values but timing is fine.
    h = mx.zeros((1, 1, H), dtype=mx.bfloat16)
    mx.eval(h)
    # warm lead cache with PREFILL dummy steps (same H reused — not realistic cache
    # content, but allocates cache state like decode)
    for _ in range(PREFILL):
        out = head.run_layers(h, hcache)
        logits = head.logits(out)
        mx.eval(logits, [c.state for c in hcache])
    def lead_step():
        out = head.run_layers(h, hcache)
        logits = head.logits(out)
        mx.eval(logits, [c.state for c in hcache])
    xs = time_steps(lead_step, repeats, warmup)
    results["lead"] = {
        "range": list(head.range), "n_layers": head.range[1] - head.range[0],
        "ms": {"median": med(xs), "p90": p90(xs), "min": round(min(xs), 3), "max": round(max(xs), 3)},
        "raw_ms": [round(x, 3) for x in xs],
        "note": "fed zeros([1,1,H]) bf16; cache advanced each step",
    }
    print(f"  lead half: {results['lead']['ms']['median']} ms med", flush=True)
    n_layers = head.n_layers
    del head, hcache, h
    gc.collect()

    # ---- full model ----
    print("  load full model...", flush=True)
    t0 = time.time()
    model, config = load_model(model_dir, lazy=False, strict=False)
    try:
        maybe_set_recommended_wired_limit(model)
    except Exception:
        pass
    print(f"  full loaded in {time.time()-t0:.1f}s", flush=True)
    cache = make_prompt_cache(model)
    # prefill
    x = mx.array(pref, dtype=mx.int32)[None]
    # use model() API
    def _eval_out(y, cache):
        states = []
        for c in cache:
            if c is None: continue
            st = getattr(c, "state", None)
            if st is not None:
                states.append(st)
        mx.eval(y, states)
    y = model(x, cache=cache)
    _eval_out(y, cache)
    x1 = mx.array([[2000]], dtype=mx.int32)
    def full_step():
        y = model(x1, cache=cache)
        _eval_out(y, cache)
    xs = time_steps(full_step, repeats, warmup)
    results["full"] = {
        "n_layers": n_layers,
        "ms": {"median": med(xs), "p90": p90(xs), "min": round(min(xs), 3), "max": round(max(xs), 3)},
        "raw_ms": [round(x, 3) for x in xs],
    }
    print(f"  full model: {results['full']['ms']['median']} ms med", flush=True)

    # derived
    f = results["full"]["ms"]["median"]
    p = results["packer"]["ms"]["median"]
    l = results["lead"]["ms"]["median"]
    e = results["empty"]["ms"]["median"]
    results["derived"] = {
        "sum_halves_ms": round(p + l, 3),
        "sum_minus_full_ms": round(p + l - f, 3),
        "empty_as_fixed_ms": e,
        "packer_minus_empty_ms": round(p - e, 3),
        "implied_per_layer_packer_ms": round((p - e) / max(results["packer"]["n_layers"] - 1, 1), 3),
    }
    print(f"  derived: sum halves {p+l:.2f} vs full {f:.2f} (extra {p+l-f:.2f}); empty/fixed ~{e:.2f}", flush=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"  wrote {out_path}", flush=True)

if __name__ == "__main__":
    main()
