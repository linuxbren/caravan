"""Day 12 probes: force_fused SDPA, layer compile (already tried), metal_kernel SwiGLU."""
from __future__ import annotations

import inspect
import json
import sys
import time
from functools import partial
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
from mlx_lm import load
from mlx_lm.models.cache import make_prompt_cache


def decode_loop(model, n=40, warmup=6):
    cache = make_prompt_cache(model)
    mx.eval(model(mx.array([[1]]), cache=cache))
    times = []
    for i in range(warmup + n):
        t0 = time.perf_counter()
        mx.eval(model(mx.array([[2]]), cache=cache))
        dt = time.perf_counter() - t0
        if i >= warmup:
            times.append(dt)
    return sum(times) / len(times)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else (
        "/Users/brenden/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit"
    )
    out = {"path": path, "mlx": mx.__version__}
    print("loading", path, flush=True)
    model, _tok = load(path)
    base_t = decode_loop(model)
    out["baseline_ms"] = round(base_t * 1000, 3)
    out["baseline_tps"] = round(1 / base_t, 2)
    print(f"baseline {out['baseline_ms']:.2f} ms/tok ({out['baseline_tps']:.2f} t/s)", flush=True)

    # force_fused SDPA
    import mlx_lm.models.llama as L
    import mlx_lm.models.base as B

    orig_fast = mx.fast.scaled_dot_product_attention
    _orig_b = B.scaled_dot_product_attention

    def wrapped(queries, keys, values, cache, scale, mask, sinks=None):
        if hasattr(cache, "bits"):
            return _orig_b(queries, keys, values, cache, scale, mask, sinks)
        return orig_fast(
            queries, keys, values, scale=scale, mask=mask, sinks=sinks, force_fused=True
        )

    B.scaled_dot_product_attention = wrapped
    L.scaled_dot_product_attention = wrapped
    model_ff, _ = load(path)
    L.scaled_dot_product_attention = wrapped
    try:
        t = decode_loop(model_ff)
        out["force_fused_ms"] = round(t * 1000, 3)
        out["force_fused_tps"] = round(1 / t, 2)
        out["force_fused_speedup"] = round(base_t / t, 3)
        print(
            f"force_fused {out['force_fused_ms']:.2f} ms/tok "
            f"({out['force_fused_tps']:.2f} t/s) x{out['force_fused_speedup']}",
            flush=True,
        )
    except Exception as e:
        out["force_fused_error"] = f"{type(e).__name__}: {e}"
        print("force_fused failed", out["force_fused_error"], flush=True)

    # metal_kernel API probe + microbench vs mx.compile silu*up
    print("metal_kernel signature:", inspect.signature(mx.fast.metal_kernel), flush=True)
    size = 1 << 20
    gate = mx.random.normal((size,)).astype(mx.float16)
    up = mx.random.normal((size,)).astype(mx.float16)
    mx.eval(gate, up)
    size_arr = mx.array([size], dtype=mx.uint32)

    @partial(mx.compile, shapeless=True)
    def compiled_swiglu(g, u):
        return nn.silu(g) * u

    def eager_swiglu(g, u):
        return nn.silu(g) * u

    results = {}
    for name, fn in [("eager", eager_swiglu), ("compile", compiled_swiglu)]:
        for _ in range(5):
            mx.eval(fn(gate, up))
        t0 = time.perf_counter()
        for _ in range(50):
            mx.eval(fn(gate, up))
        results[name + "_ms"] = (time.perf_counter() - t0) / 50 * 1000
    print("swiglu micro", results, flush=True)
    out["swiglu_micro_ms"] = results

    # Try metal_kernel with template dtype (MLX 0.32 style)
    metal_ok = False
    try:
        kernel = mx.fast.metal_kernel(
            name="caravan_swiglu",
            input_names=["gate", "up", "size"],
            output_names=["out"],
            source=(
                "uint i = thread_position_in_grid.x;\n"
                "if (i >= size[0]) return;\n"
                "float g = float(gate[i]);\n"
                "out[i] = T((g / (1.0f + metal::exp(-g))) * float(up[i]));\n"
            ),
        )
        def metal_swiglu(g, u):
            (o,) = kernel(
                inputs=[g, u, size_arr],
                grid=(size, 1, 1),
                threadgroup=(256, 1, 1),
                output_shapes=[g.shape],
                output_dtypes=[g.dtype],
                template=[("T", g.dtype)],
            )
            return o
        for _ in range(5):
            mx.eval(metal_swiglu(gate, up))
        t0 = time.perf_counter()
        for _ in range(50):
            mx.eval(metal_swiglu(gate, up))
        results["metal_ms"] = (time.perf_counter() - t0) / 50 * 1000
        # correctness vs eager
        e = eager_swiglu(gate, up)
        m = metal_swiglu(gate, up)
        mx.eval(e, m)
        results["metal_max_abs_err"] = float(mx.max(mx.abs(e.astype(mx.float32) - m.astype(mx.float32))).item())
        metal_ok = True
        print("metal swiglu", results, flush=True)
    except Exception as e:
        out["metal_error"] = f"{type(e).__name__}: {e}"
        print("metal failed", out["metal_error"], flush=True)
    out["swiglu_micro_ms"] = results
    out["metal_ok"] = metal_ok

    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("probe_fuse_result.json")
    dest.write_text(json.dumps(out, indent=2))
    print("wrote", dest, flush=True)


if __name__ == "__main__":
    main()
