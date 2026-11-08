"""MLX architecture support helpers (model_type remaps + usable checks).

Finding (Nov 5 2026): mlx-community/JevK5-chat-mlx-4bit ships
`model_type: qwen3_5_text` (Qwen3_5ForCausalLM, hybrid linear attention).
mlx_lm 0.32.2 has `models/qwen3_5.py` but only registers `qwen3_5`, so load
fails with "Model type qwen3_5_text not supported" until remapped.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Caravan-applied remaps (also patched into mlx_lm.utils.MODEL_REMAPPING at worker start).
MODEL_TYPE_REMAP = {
    "qwen3_5_text": "qwen3_5",
}

# Types we know mlx_lm cannot run even after remap (extend when discovered).
UNSUPPORTED_MODEL_TYPES = set()


def read_model_type(model_dir: str | Path) -> Optional[str]:
    p = Path(model_dir).expanduser() / "config.json"
    if not p.is_file():
        return None
    try:
        cfg = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    mt = cfg.get("model_type")
    if not mt and isinstance(cfg.get("text_config"), dict):
        mt = (cfg.get("text_config") or {}).get("model_type")
    return str(mt) if mt else None


def effective_model_type(model_type: Optional[str]) -> Optional[str]:
    if not model_type:
        return None
    return MODEL_TYPE_REMAP.get(model_type, model_type)


def architecture_status(model_dir: str | Path = None, *, model_type: Optional[str] = None) -> dict:
    """Return {supported, model_type, effective, reason, remapped}."""
    mt = model_type or (read_model_type(model_dir) if model_dir else None)
    if not mt:
        return {
            "supported": True,  # unknown — don't block; worker will fail clearly
            "model_type": None,
            "effective": None,
            "remapped": False,
            "reason": "",
        }
    eff = effective_model_type(mt)
    remapped = eff != mt
    if mt in UNSUPPORTED_MODEL_TYPES or eff in UNSUPPORTED_MODEL_TYPES:
        return {
            "supported": False,
            "model_type": mt,
            "effective": eff,
            "remapped": remapped,
            "reason": f"unsupported architecture ({mt})",
        }
    return {
        "supported": True,
        "model_type": mt,
        "effective": eff,
        "remapped": remapped,
        "reason": (f"remapped {mt} → {eff}" if remapped else ""),
    }


def apply_mlx_lm_remaps(log=None) -> list:
    """Patch mlx_lm.utils.MODEL_REMAPPING in-process. Returns applied pairs."""
    applied = []
    try:
        from mlx_lm import utils as U
    except ImportError:
        return applied
    rem = getattr(U, "MODEL_REMAPPING", None)
    if not isinstance(rem, dict):
        return applied
    for src, dst in MODEL_TYPE_REMAP.items():
        if rem.get(src) != dst:
            rem[src] = dst
            applied.append((src, dst))
            if log:
                try:
                    log(f"model_type remap: {src} → {dst}")
                except Exception:
                    pass
    return applied


def _text_cfg(config: dict) -> dict:
    cfg = dict(config or {})
    for sub in ("text_config", "llm_config"):
        if isinstance(cfg.get(sub), dict):
            merged = dict(cfg[sub])
            for k, v in cfg.items():
                merged.setdefault(k, v)
            return merged
    return cfg


def _iter_layers(model):
    lm = getattr(model, "language_model", None) or model
    inner = getattr(lm, "model", None) or lm
    return list(getattr(inner, "layers", None) or [])


def fix_rope_scaling(model, config: dict, *, nn=None, initialize_rope=None, log=None) -> int:
    """Day 18: some mlx_lm model classes (mixtral, qwen3_moe, phi3, ...) build a
    plain nn.RoPE and ignore config.rope_scaling. Mixtral-shaped Llama 3.x
    merges (Dark Champion) ship llama3 scaling (factor 32), so long prompts
    drift. Swap any *plain* nn.RoPE for mlx_lm's initialize_rope(...) when the
    config asks for scaling. Classes that already scale (llama, qwen2/3,
    gpt_oss ...) keep their own rope objects, so this is a no-op for them.
    Returns the number of attention modules patched."""
    cfg = _text_cfg(config)
    sc = cfg.get("rope_scaling") or cfg.get("rope_parameters")
    if not isinstance(sc, dict):
        return 0
    rt = sc.get("type") or sc.get("rope_type") or "default"
    if rt == "default" or (rt == "linear" and not sc.get("factor")):
        return 0
    if nn is None:
        import mlx.nn as nn  # type: ignore
    if initialize_rope is None:
        from mlx_lm.models.rope_utils import initialize_rope  # type: ignore
    n = 0
    for layer in _iter_layers(model):
        if layer is None:
            continue
        attn = getattr(layer, "self_attn", None) or getattr(layer, "attention", None)
        rope = getattr(attn, "rope", None)
        if rope is None or type(rope) is not nn.RoPE:
            continue
        if rt == "linear" and abs(float(getattr(rope, "scale", 1.0)) - 1.0) > 1e-9:
            continue  # class already applied linear scaling
        attn.rope = initialize_rope(
            rope.dims, rope.base, rope.traditional, sc,
            cfg.get("max_position_embeddings"))
        n += 1
    if n and log:
        try:
            log(f"rope scaling: applied {rt} to {n} attention layer(s) (mlx_lm class ignored it)")
        except Exception:
            pass
    return n
