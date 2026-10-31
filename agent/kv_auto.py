"""Automatic KV-cache type (2026-10-30, improvement 3).

cache_type_k / cache_type_v default to "auto": use f16 (fastest -- the
q8_0 cache cost 4-6% on Qwen3-30B and Gemma 4 in the Oct 30 baseline)
when it fits, q8_0 when it doesn't. "Fits" means

    model weights + KV(n_slots x ctx_per_slot, f16) + compute reserve
        + safety margin  <=  GPU working-set limit x devices

An explicit type (CLI flag, CARAVAN_CACHE_TYPE_K/V, or config) always
wins; only the side(s) left at "auto" are decided here. Anything we can't
estimate (unreadable GGUF, unknown layout) falls back to q8_0 -- the old
default -- so this never makes a working setup bigger by accident.

KV size comes from the GGUF header (gguf_meta.py): per layer
n_head_kv x (key_length + value_length) elements per token, with
sliding-window layers (Gemma 2/3/4, GPT-OSS...) capped at
min(ctx_per_slot, sliding_window + n_ubatch) tokens per slot -- the size
llama.cpp actually allocates for its SWA cache unless --swa-full.

GPU limit, in order: explicit setting (kv_auto.gpu_working_set_mib /
CARAVAN_GPU_WORKING_SET_MIB) > Metal recommendedMaxWorkingSetSize (asked
once via `swift`, cached in ~/.caravan/agent/gpu_limit.json) >
iogpu.wired_limit_mb if non-zero > 18186.25 MiB. Units: llama.cpp prints
the limit as "19069.67 MB" -- decimal MB; it's 18186.25 MiB, and every
llama.cpp buffer size is MiB, so that's the number to compare against.

Compute reserve: llama.cpp's Metal compute buffer is dominated by the
logits for a full ubatch, ubatch x n_vocab x 4 B. The Oct 30 verbose runs
(-ub 2048, 4k ctx) measured 1203 / 2092 / 1616 MiB for Qwen3-30B (vocab
151,936 -> 1187 predicted) / Gemma 4 (262,144 -> 2048) / GPT-OSS
(201,088 -> 1571), so the estimate is that plus 64 MiB
(kv_auto.compute_reserve_mib pins it). The safety margin defaults to
256 MiB (kv_auto.safety_margin_mib) and only gates the f16 choice --
q8_0 is the old behaviour, so it's never refused, just flagged when even
it looks over (Qwen 1 x 18432 q8_0 is right at the edge and works).
Weights = file size (within ~15 MiB of llama.cpp's MTL0 model buffer for
all three models). A heuristic, not a guarantee: the log line shows every
term so a wrong call is easy to spot and override.
"""
import json
import os
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional

try:
    import gguf_meta
except ImportError:  # imported as agent.kv_auto
    from agent import gguf_meta

DEFAULT_GPU_WORKING_SET_MIB = 18186.25   # = 19,069.67 MB, M4 24 GB
DEFAULT_RESERVE_BASE_MIB = 64.0
DEFAULT_N_VOCAB = 262144                  # if the GGUF has no vocab (conservative)
DEFAULT_SAFETY_MARGIN_MIB = 256.0
GPU_LIMIT_CACHE = Path.home() / ".caravan" / "agent" / "gpu_limit.json"
MIB = 1024 * 1024

# Bytes per element (ggml block size accounted for).
KV_TYPE_BYTES = {
    "f32": 4.0, "f16": 2.0, "bf16": 2.0,
    "q8_0": 34 / 32, "q4_0": 18 / 32, "q4_1": 20 / 32,
    "q5_0": 22 / 32, "q5_1": 24 / 32, "iq4_nl": 18 / 32,
}

# SWA layer pattern for architectures whose GGUF doesn't carry
# <arch>.attention.sliding_window_pattern (llama.cpp hard-codes these via
# hparams.set_swa_pattern(n): layer il is SWA iff il % n < n - 1).
SWA_PATTERN_BY_ARCH = {"gpt-oss": 2, "gemma2": 2, "gemma3": 6, "gemma3n": 5, "cohere2": 4}


class KvLayout(NamedTuple):
    """Per-layer (elements per token for K+V, is_swa)."""
    layers: tuple
    sliding_window: int
    arch: str
    n_vocab: int = DEFAULT_N_VOCAB


class KvDecision(NamedTuple):
    cache_type_k: str
    cache_type_v: str
    reason: str
    estimate: dict


def _per_layer(meta, arch, key, n_layer, default=None):
    v = meta.get(f"{arch}.{key}", default)
    if isinstance(v, list):
        if len(v) != n_layer:
            raise ValueError(f"{key}: {len(v)} entries for {n_layer} layers")
        return list(v)
    if v is None:
        return None
    return [v] * n_layer


def kv_layout(meta: dict) -> KvLayout:
    arch = meta.get("general.architecture")
    if not arch:
        raise ValueError("no general.architecture")
    n_layer = int(meta[f"{arch}.block_count"])
    n_head = _per_layer(meta, arch, "attention.head_count", n_layer)
    n_head_kv = _per_layer(meta, arch, "attention.head_count_kv", n_layer) or n_head
    n_embd = int(meta[f"{arch}.embedding_length"])
    hd_default = n_embd // int(n_head[0]) if n_head else None
    k_len = int(meta.get(f"{arch}.attention.key_length", hd_default))
    v_len = int(meta.get(f"{arch}.attention.value_length", k_len))
    k_swa = int(meta.get(f"{arch}.attention.key_length_swa", k_len))
    v_swa = int(meta.get(f"{arch}.attention.value_length_swa", v_len))
    window = int(meta.get(f"{arch}.attention.sliding_window", 0) or 0)

    pattern = meta.get(f"{arch}.attention.sliding_window_pattern")
    if window <= 0:
        is_swa = [False] * n_layer
    elif isinstance(pattern, list) and len(pattern) == n_layer:
        is_swa = [bool(x) for x in pattern]
    else:
        n = int(pattern) if isinstance(pattern, int) and pattern > 0 else SWA_PATTERN_BY_ARCH.get(arch)
        if n is None:
            is_swa = [True] * n_layer  # all-SWA (e.g. mistral-style)
        else:
            is_swa = [(il % n) < (n - 1) for il in range(n_layer)]

    layers = []
    for il in range(n_layer):
        kvh = int(n_head_kv[il])
        if kvh <= 0:  # layer without its own KV (shared / recurrent)
            layers.append((0, False))
            continue
        kl, vl = (k_swa, v_swa) if is_swa[il] else (k_len, v_len)
        layers.append((kvh * (kl + vl), is_swa[il]))
    n_vocab = meta.get(f"{arch}.vocab_size")
    if not isinstance(n_vocab, int):
        toks = meta.get("tokenizer.ggml.tokens")
        n_vocab = len(toks) if toks is not None and len(toks) > 0 else DEFAULT_N_VOCAB
    return KvLayout(tuple(layers), window, arch, int(n_vocab))


def compute_reserve_mib(layout: KvLayout, n_ubatch: int) -> float:
    """Metal compute buffer estimate: full-ubatch f32 logits + a little."""
    return n_ubatch * layout.n_vocab * 4 / MIB + DEFAULT_RESERVE_BASE_MIB


def kv_bytes(layout: KvLayout, n_slots: int, ctx_per_slot: int, n_ubatch: int,
             type_k: str, type_v: str, swa_full: bool = False) -> float:
    """Estimated KV-cache bytes. K and V share the per-layer element count
    split half/half (exact when key_length == value_length, as in every
    model here)."""
    bk, bv = KV_TYPE_BYTES[type_k], KV_TYPE_BYTES[type_v]
    swa_tokens = ctx_per_slot if swa_full else min(ctx_per_slot, layout.sliding_window + n_ubatch)
    total = 0.0
    for elems, is_swa in layout.layers:
        tokens = swa_tokens if is_swa else ctx_per_slot
        total += (elems / 2) * (bk + bv) * tokens
    return total * n_slots


def _swift_working_set_mib(timeout: float = 60.0) -> Optional[float]:
    code = "import Metal; print(MTLCreateSystemDefaultDevice()!.recommendedMaxWorkingSetSize)"
    try:
        r = subprocess.run(["swift", "-e", code], capture_output=True, text=True, timeout=timeout)
        return int(r.stdout.strip()) / MIB if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _sysctl_wired_limit_mib() -> Optional[float]:
    try:
        r = subprocess.run(["sysctl", "-n", "iogpu.wired_limit_mb"],
                           capture_output=True, text=True, timeout=5)
        v = int(r.stdout.strip())
        return float(v) if v > 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def gpu_working_set_mib(explicit=None, cache_file: Path = GPU_LIMIT_CACHE,
                        query=_swift_working_set_mib, wired=_sysctl_wired_limit_mib) -> tuple:
    """(MiB, source)."""
    if explicit not in (None, ""):
        return float(explicit), "configured"
    try:
        cached = json.loads(Path(cache_file).read_text())
        return float(cached["recommended_max_working_set_mib"]), f"metal (cached {cache_file})"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    v = query()
    if v:
        try:
            Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_file).write_text(json.dumps({"recommended_max_working_set_mib": v}))
        except OSError:
            pass
        return v, "metal recommendedMaxWorkingSetSize"
    w = wired()
    if w:
        return w, "sysctl iogpu.wired_limit_mb"
    return DEFAULT_GPU_WORKING_SET_MIB, "default"


def _env_or(cfg: dict, key: str, env: str):
    e = os.environ.get(env, "").strip()
    if e:
        return e
    return cfg.get(key)


def decide(model_path, n_slots: int, ctx_per_slot: int, n_ubatch: int,
           cache_type_k: str = "auto", cache_type_v: str = "auto", n_devices: int = 1,
           swa_full: bool = False, cfg: Optional[dict] = None,
           limit_fn=gpu_working_set_mib, meta_fn=gguf_meta.read_metadata) -> KvDecision:
    """Resolves "auto" K/V types. `cfg` is the "kv_auto" config section:
    gpu_working_set_mib, compute_reserve_mib, safety_margin_mib (env
    CARAVAN_GPU_WORKING_SET_MIB / CARAVAN_COMPUTE_RESERVE_MIB /
    CARAVAN_KV_SAFETY_MARGIN_MIB)."""
    cfg = cfg or {}
    auto_k, auto_v = cache_type_k == "auto", cache_type_v == "auto"
    if not (auto_k or auto_v):
        return KvDecision(cache_type_k, cache_type_v, "explicit", {})
    fallback_k = "q8_0" if auto_k else cache_type_k
    fallback_v = "q8_0" if auto_v else cache_type_v
    try:
        weights = Path(model_path).expanduser().stat().st_size
        layout = kv_layout(meta_fn(model_path))
    except Exception as e:  # noqa: BLE001 -- any failure means "can't estimate"
        return KvDecision(fallback_k, fallback_v, f"q8_0 fallback: can't estimate ({e})", {})

    limit_mib, limit_src = limit_fn(_env_or(cfg, "gpu_working_set_mib", "CARAVAN_GPU_WORKING_SET_MIB"))
    reserve = _env_or(cfg, "compute_reserve_mib", "CARAVAN_COMPUTE_RESERVE_MIB")
    reserve_mib = float(reserve) if reserve not in (None, "") else compute_reserve_mib(layout, n_ubatch)
    margin = _env_or(cfg, "safety_margin_mib", "CARAVAN_KV_SAFETY_MARGIN_MIB")
    budget_mib = limit_mib * max(1, n_devices)
    margin_mib = float(margin) if margin not in (None, "") else DEFAULT_SAFETY_MARGIN_MIB

    cand_k = "f16" if auto_k else cache_type_k
    cand_v = "f16" if auto_v else cache_type_v
    kv_f16 = kv_bytes(layout, n_slots, ctx_per_slot, n_ubatch, cand_k, cand_v, swa_full) / MIB
    kv_q8 = kv_bytes(layout, n_slots, ctx_per_slot, n_ubatch, fallback_k, fallback_v, swa_full) / MIB
    need_f16 = weights / MIB + kv_f16 + reserve_mib * max(1, n_devices) + margin_mib
    need_q8 = weights / MIB + kv_q8 + reserve_mib * max(1, n_devices) + margin_mib
    est = {
        "arch": layout.arch, "weights_mib": round(weights / MIB, 1),
        "kv_f16_mib": round(kv_f16, 1), "kv_q8_0_mib": round(kv_q8, 1),
        "compute_reserve_mib": round(reserve_mib, 1), "safety_margin_mib": round(margin_mib, 1),
        "gpu_limit_mib": round(limit_mib, 2), "gpu_limit_source": limit_src, "n_devices": n_devices,
        "need_f16_mib": round(need_f16, 1), "need_q8_0_mib": round(need_q8, 1),
        "budget_mib": round(budget_mib, 1),
        "slots": n_slots, "ctx_per_slot": ctx_per_slot, "ubatch": n_ubatch,
        "swa_layers": sum(1 for _, s in layout.layers if s), "sliding_window": layout.sliding_window,
        "n_vocab": layout.n_vocab,
    }
    if need_f16 <= budget_mib:
        return KvDecision(cand_k, cand_v,
                          f"f16 fits ({need_f16:.0f} <= {budget_mib:.0f} MiB)", est)
    q8_no_margin = need_q8 - margin_mib
    note = ("" if q8_no_margin <= budget_mib else
            f"; WARNING q8_0 is also at/over the estimated limit ({q8_no_margin:.0f} MiB before margin)")
    return KvDecision(fallback_k, fallback_v,
                      f"q8_0: f16 needs {need_f16:.0f} > {budget_mib:.0f} MiB{note}", est)


def format_decision(d: KvDecision) -> str:
    e = d.estimate
    if not e:
        return f"[caravan] KV cache -ctk {d.cache_type_k} -ctv {d.cache_type_v} ({d.reason})"
    return (f"[caravan] KV cache -ctk {d.cache_type_k} -ctv {d.cache_type_v}: {d.reason}. "
            f"Estimate: weights {e['weights_mib']:.0f} + KV f16 {e['kv_f16_mib']:.0f} / q8_0 "
            f"{e['kv_q8_0_mib']:.0f} + compute {e['compute_reserve_mib']:.0f} + margin "
            f"{e['safety_margin_mib']:.0f} MiB vs limit {e['gpu_limit_mib']:.0f} MiB x {e['n_devices']} "
            f"({e['gpu_limit_source']}); {e['arch']} {e['slots']}x{e['ctx_per_slot']} ub {e['ubatch']}, "
            f"{e['swa_layers']} SWA layers (window {e['sliding_window']})")
