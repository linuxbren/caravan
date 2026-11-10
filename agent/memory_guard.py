"""RAM safety for growing chats (lead + packer).

Before a reply, estimate how much KV the prompt + max_tokens will need on
this Mini's layer share, compare with reclaimable system memory minus a
safety margin, and drop the oldest non-system turns until it fits. Pure
stdlib + model config.json — no mlx import, so unit tests stay light.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Optional


DEFAULT_CACHE_LIMIT_GB = 1.5
DEFAULT_MEMORY_LIMIT_GB = None          # None = do not call mx.set_memory_limit
DEFAULT_SAFETY_GB = 1.75
BYTES_F16 = 2.0


def model_layer_count(cfg: dict) -> int:
    """Decoder depth, including multimodal wrappers such as Qwen3.5.

    This must agree with the nested dimensions used by kv_elems_per_token;
    counting a wrapped decoder as one layer grossly inflates context budgets.
    """
    if isinstance(cfg.get("text_config"), dict):
        cfg = dict(cfg, **cfg["text_config"])
    return max(0, int(cfg.get("num_hidden_layers") or cfg.get("n_layers") or 0))


def kv_elems_per_token(cfg: dict) -> int:
    """K+V elements per token for one full layer (all kv heads)."""
    # Qwen3.5 and other multimodal wrappers keep decoder dimensions here.
    # Treating all layers as full KV is intentionally conservative for hybrids.
    if isinstance(cfg.get("text_config"), dict):
        cfg = dict(cfg, **cfg["text_config"])
    n_kv = int(cfg.get("num_key_value_heads") or cfg.get("num_attention_heads") or 0)
    hd = cfg.get("head_dim")
    if hd is None:
        hidden = int(cfg.get("hidden_size") or 0)
        n_heads = int(cfg.get("num_attention_heads") or 1) or 1
        hd = hidden // n_heads if hidden else 0
    hd = int(hd or 0)
    return max(0, n_kv * hd * 2)  # K and V


def bytes_per_token_for_layers(cfg: dict, n_layers: int, *, kv_bits: int = 16) -> float:
    """Estimated KV bytes per token for `n_layers` of this model."""
    elems = kv_elems_per_token(cfg)
    bpe = BYTES_F16
    if kv_bits and int(kv_bits) < 16:
        # Rough: QuantizedKVCache stores ~bits/16 of f16, plus a little overhead.
        bpe = BYTES_F16 * (int(kv_bits) / 16.0) * 1.15
    return float(elems) * bpe * max(0, int(n_layers))


def estimate_kv_gb(cfg: dict, n_tokens: int, n_layers: int, *, kv_bits: int = 16) -> float:
    return bytes_per_token_for_layers(cfg, n_layers, kv_bits=kv_bits) * max(0, int(n_tokens)) / 1e9


def _vm_stat_pages() -> dict:
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    page = 16384
    m = re.search(r"page size of (\d+) bytes", out)
    if m:
        page = int(m.group(1))
    v = {}
    for line in out.splitlines()[1:]:
        mm = re.match(r"^(.+?):\s+(\d+)\.?$", line)
        if mm:
            v[mm.group(1).strip()] = int(mm.group(2)) * page
    return v


def host_available_gb() -> tuple[float, float]:
    """(total_gb, available_gb). Available = free + speculative + purgeable + inactive
    (reclaimable under pressure) — closer to macOS Memory Pressure than raw free."""
    override = os.environ.get("CARAVAN_MEMORY_FORCE_HEADROOM_GB")
    v = _vm_stat_pages()
    total = 0.0
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip().isdigit():
            total = int(out.stdout.strip()) / 1e9
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if total <= 0 and v:
        total = sum(v.get(k, 0) for k in (
            "Pages free", "Pages speculative", "Pages active", "Pages inactive",
            "Pages wired down", "Pages occupied by compressor",
        )) / 1e9
    if total <= 0:
        # Linux / tests
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, rest = line.partition(":")
                    info[k] = int(rest.strip().split()[0]) * 1024
            total = info.get("MemTotal", 0) / 1e9
            avail = info.get("MemAvailable", info.get("MemFree", 0)) / 1e9
            if override is not None:
                return total, float(override)
            return total, avail
        except Exception:
            if override is not None:
                return 24.0, float(override)
            return 24.0, 12.0
    avail = (
        v.get("Pages free", 0)
        + v.get("Pages speculative", 0)
        + v.get("Pages purgeable", 0)
        + v.get("Pages inactive", 0)
    ) / 1e9
    if override is not None:
        return total, float(override)
    return total, avail


def peer_available_gb(stats: dict) -> Optional[float]:
    """Tightest upstream Mini, for legacy and flattened N-stage stats.

    Never add free RAM from co-hosted stages. The caller budgets all upstream
    layers against this minimum, conservatively covering shared physical RAM.
    Missing/invalid telemetry stays unknown rather than claiming a full budget.
    """
    import math
    try:
        peers = stats["packers"] if "packers" in stats else [stats]
        if not peers: return None
        available = []
        for peer in peers:
            value = peer.get("mem_available_gb")
            if value is None or isinstance(value, bool): return None
            value = float(value)
            if not math.isfinite(value) or value < 0: return None
            available.append(value)
        return min(available)
    except (TypeError, ValueError, AttributeError, KeyError):
        return None


def headroom_gb(*, safety_gb: float = DEFAULT_SAFETY_GB,
                packer_available_gb: Optional[float] = None) -> dict:
    total, avail = host_available_gb()
    local = max(0.0, avail - float(safety_gb))
    remote = None
    if packer_available_gb is not None:
        remote = max(0.0, float(packer_available_gb) - float(safety_gb))
    usable = local if remote is None else min(local, remote)
    # Keep full precision for budgeting; round only the reported fields.
    return {
        "total_gb": round(total, 2),
        "available_gb": round(avail, 3),
        "safety_gb": float(safety_gb),
        "local_headroom_gb": round(local, 3),
        "packer_available_gb": None if packer_available_gb is None else round(float(packer_available_gb), 3),
        "packer_headroom_gb": None if remote is None else round(remote, 3),
        "headroom_gb": usable,
        "headroom_gb_reported": round(usable, 3),
    }


def _is_system(m: dict) -> bool:
    return str(m.get("role") or "").lower() == "system"


def trim_messages_to_token_budget(
    messages: list,
    *,
    budget_tokens: int,
    count_tokens: Callable[[list], int],
) -> tuple[list, int, list]:
    """Drop oldest non-system turns until tokenize(messages) <= budget.
    Drops from the front in pairs when possible (user+assistant), else one at a time.
    Never drops the final user message.
    Returns (new_messages, trimmed_turn_count, dropped_messages_in_order).
    """
    msgs = [dict(m) for m in (messages or [])]
    if not msgs:
        return msgs, 0, []
    trimmed = 0
    dropped = []
    while len(msgs) > 1 and count_tokens(msgs) > budget_tokens:
        i = 0
        while i < len(msgs) - 1 and _is_system(msgs[i]):
            i += 1
        if i >= len(msgs) - 1:
            break
        if (i + 1 < len(msgs) - 1
                and str(msgs[i].get("role")) == "user"
                and str(msgs[i + 1].get("role")) == "assistant"):
            dropped.extend(msgs[i:i + 2])
            del msgs[i:i + 2]
            trimmed += 2
        else:
            dropped.append(msgs[i])
            del msgs[i]
            trimmed += 1
    return msgs, trimmed, dropped


def plan(
    messages: list,
    *,
    cfg: dict,
    n_layers: int,
    max_tokens: int,
    count_tokens: Callable[[list], int],
    kv_bits: int = 16,
    safety_gb: float = DEFAULT_SAFETY_GB,
    packer_available_gb: Optional[float] = None,
    packer_layers: Optional[int] = None,
) -> dict:
    """Decide whether messages fit; trim if needed.

    Returns dict with keys: messages, trimmed_turns, headroom_gb, need_gb,
    prompt_tokens, budget_tokens, error (or None), ok (bool).
    """
    hr = headroom_gb(safety_gb=safety_gb, packer_available_gb=packer_available_gb)
    headroom = float(hr["headroom_gb"])
    # Each Mini must fit its own layer share; use the tighter side.
    lead_layers = int(n_layers)
    pk_layers = int(packer_layers) if packer_layers is not None else lead_layers
    bpt_lead = bytes_per_token_for_layers(cfg, lead_layers, kv_bits=kv_bits)
    bpt_pk = bytes_per_token_for_layers(cfg, pk_layers, kv_bits=kv_bits)
    bpt = max(bpt_lead, bpt_pk)  # conservative: size as if both need the denser share
    if bpt <= 0:
        return {
            "messages": list(messages or []),
            "trimmed_turns": 0,
            "headroom_gb": headroom,
            "need_gb": 0.0,
            "prompt_tokens": 0,
            "budget_tokens": 10**9 if headroom > 0 else 0,
            "error": None if headroom > 0 else "Free memory is below the safety margin; wait or use a smaller model.",
            "ok": headroom > 0,
            **{k: hr[k] for k in ("available_gb", "safety_gb", "local_headroom_gb",
                                   "packer_available_gb", "packer_headroom_gb")},
        }
    # Tokens we can afford for prompt+completion on the tighter Mini.
    budget_tokens = int(headroom * 1e9 / bpt)
    # Leave room for the reply.
    prompt_budget = max(0, budget_tokens - max(1, int(max_tokens)))
    msgs = list(messages or [])
    trimmed = 0
    if prompt_budget <= 0:
        return {
            "messages": msgs,
            "trimmed_turns": 0,
            "headroom_gb": headroom,
            "need_gb": round(estimate_kv_gb(cfg, max_tokens + 1, lead_layers, kv_bits=kv_bits), 3),
            "prompt_tokens": 0,
            "budget_tokens": budget_tokens,
            "error": (f"Not enough memory headroom ({headroom:.2f} GB after "
                      f"{safety_gb} GB safety) for even a short reply. "
                      f"Free RAM on the Minis or lower max_tokens."),
            "ok": False,
            **{k: hr[k] for k in ("available_gb", "safety_gb", "local_headroom_gb",
                                   "packer_available_gb", "packer_headroom_gb")},
        }
    n = count_tokens(msgs)
    dropped = []
    if n > prompt_budget:
        msgs, trimmed, dropped = trim_messages_to_token_budget(
            msgs, budget_tokens=prompt_budget, count_tokens=count_tokens)
        n = count_tokens(msgs)
    need = estimate_kv_gb(cfg, n + max(1, int(max_tokens)), lead_layers, kv_bits=kv_bits)
    ok = n <= prompt_budget and need <= headroom + 1e-6
    err = None
    if not ok:
        err = (f"Even the newest turn needs about {need:.2f} GB of KV "
               f"(headroom {headroom:.2f} GB). Shorten the prompt or free RAM.")
    return {
        "messages": msgs,
        "trimmed_turns": trimmed,
        "dropped": dropped,
        "headroom_gb": headroom,
        "need_gb": round(need, 3),
        "prompt_tokens": n,
        "budget_tokens": prompt_budget,
        "bytes_per_token": round(bpt, 1),
        "error": err,
        "ok": ok and err is None,
        **{k: hr[k] for k in ("available_gb", "safety_gb", "local_headroom_gb",
                               "packer_available_gb", "packer_headroom_gb")},
    }
