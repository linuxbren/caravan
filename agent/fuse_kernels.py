"""ROADMAP #17: optional fused-kernel experiments for the MLX worker.

Default is off. When enabled (flag or CARAVAN_FUSE_KERNELS), we apply the
cheap patches that Day 12 measured:

1. force_fused=True on mx.fast.scaled_dot_product_attention (non-quantized KV)
2. optional Metal SwiGLU kernel replacing mlx_lm.models.activations.swiglu

Heavy transformer ops (rms_norm, rope, SDPA, quantized matmul) already use
mx.fast / fused Metal paths in MLX 0.32 + mlx-lm 0.32. mx.compile on whole
layers did not help on M4 Minis (see handoff/lab/day12-fused/).
"""
from __future__ import annotations

import os
from functools import partial
from typing import Optional


FUSE_ENV = "CARAVAN_FUSE_KERNELS"
MODES = ("off", "force-fused", "metal-swiglu", "all")


def env_mode() -> str:
    raw = (os.environ.get(FUSE_ENV) or "").strip().lower()
    if not raw or raw in ("0", "false", "no", "off"):
        return "off"
    if raw in ("1", "true", "yes", "on", "all"):
        return "all"
    if raw in MODES:
        return raw
    return "off"


def resolve_mode(cli_value: Optional[str]) -> str:
    """CLI wins when set; else env; else off."""
    if cli_value is None:
        return env_mode()
    v = str(cli_value).strip().lower()
    if v in ("0", "false", "no"):
        return "off"
    if v in ("1", "true", "yes", "on"):
        return "all"
    if v in MODES:
        return v
    raise ValueError(f"unknown fuse-kernels mode {cli_value!r}; want one of {MODES}")


def _patch_force_fused() -> str:
    import mlx.core as mx
    import mlx_lm.models.base as base

    orig_fast = mx.fast.scaled_dot_product_attention
    orig_base = base.scaled_dot_product_attention

    def wrapped(queries, keys, values, cache, scale, mask, sinks=None):
        if hasattr(cache, "bits"):
            return orig_base(queries, keys, values, cache, scale, mask, sinks)
        return orig_fast(
            queries,
            keys,
            values,
            scale=scale,
            mask=mask,
            sinks=sinks,
            force_fused=True,
        )

    base.scaled_dot_product_attention = wrapped
    # Model files import the symbol by name at load time; patch common ones.
    patched = ["mlx_lm.models.base"]
    for mod_name in (
        "mlx_lm.models.llama",
        "mlx_lm.models.qwen2",
        "mlx_lm.models.qwen3",
        "mlx_lm.models.qwen3_moe",
        "mlx_lm.models.gemma",
        "mlx_lm.models.gemma2",
        "mlx_lm.models.gemma3",
        "mlx_lm.models.gpt_oss",
    ):
        try:
            mod = __import__(mod_name, fromlist=["*"])
        except Exception:
            continue
        if hasattr(mod, "scaled_dot_product_attention"):
            setattr(mod, "scaled_dot_product_attention", wrapped)
            patched.append(mod_name)
    return "force_fused on " + ", ".join(patched)


def _metal_swiglu_kernel():
    import mlx.core as mx

    return mx.fast.metal_kernel(
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


def _patch_metal_swiglu() -> str:
    import mlx.core as mx
    import mlx_lm.models.activations as acts

    kernel = _metal_swiglu_kernel()

    def metal_swiglu(gate, x):
        flat_g = gate.reshape(-1)
        flat_x = x.reshape(-1)
        n = flat_g.size
        size = mx.array([n], dtype=mx.uint32)
        # Cap grid to multiple of 256 for tidy threadgroups.
        tg = 256
        (out,) = kernel(
            inputs=[flat_g, flat_x, size],
            grid=(n, 1, 1),
            threadgroup=(tg, 1, 1),
            output_shapes=[flat_g.shape],
            output_dtypes=[flat_g.dtype],
            template=[("T", flat_g.dtype)],
        )
        return out.reshape(gate.shape)

    # Keep a compile fallback name for tests / comparison.
    acts.swiglu = metal_swiglu
    # SwitchGLU uses SwiGLU module which imports swiglu at class body time —
    # re-bind SwiGLU.__call__ too.
    try:
        from mlx_lm.models.switch_layers import SwiGLU

        def swiglu_call(self, x, gate):
            return metal_swiglu(gate, x)

        SwiGLU.__call__ = swiglu_call
    except Exception:
        pass
    return "metal_swiglu"


def apply_fuse_kernels(mode: str, log=None) -> list[str]:
    """Apply selected patches. Returns list of applied patch names."""
    mode = resolve_mode(mode)
    applied: list[str] = []
    if mode == "off":
        if log:
            log("fuse kernels: off")
        return applied
    want_ff = mode in ("force-fused", "all")
    want_ms = mode in ("metal-swiglu", "all")
    if want_ff:
        applied.append(_patch_force_fused())
    if want_ms:
        applied.append(_patch_metal_swiglu())
    if log:
        log("fuse kernels: " + ("; ".join(applied) if applied else mode))
    return applied


def compile_layers(model, log=None) -> int:
    """Wrap each transformer block with mx.compile(shapeless=True).

    Day 12 measured ~1.0x on Llama 3.1 8B (no win). Kept for A/B / research;
    not enabled by the default --fuse-kernels modes.
    """
    import mlx.core as mx

    inner = getattr(model, "model", model)
    layers = getattr(inner, "layers", None)
    if not layers:
        if log:
            log("fuse compile-layers: no layers found")
        return 0
    n = 0
    for layer in layers:
        orig = layer.__call__.__get__(layer, type(layer))

        def make(o):
            return mx.compile(o, shapeless=True)

        layer.__call__ = make(orig)
        n += 1
    if log:
        log(f"fuse compile-layers: wrapped {n} layers")
    return n
