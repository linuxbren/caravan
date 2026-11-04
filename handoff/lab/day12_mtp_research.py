#!/usr/bin/env python3
"""Day 12 #16: probe whether our models ship MTP / multi-token draft heads.

Reads config.json (+ adjacent) for known MTP fields. Optionally peeks at
safetensors index for key name patterns. Does NOT download weights.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

MTP_CONFIG_KEYS = (
    "mtp", "MTP", "multi_token_prediction", "num_nextn_predict_layers",
    "num_mtp_layers", "mtp_num_hidden_layers", "draft_layers",
    "eagle", "speculative", "num_predict_tokens", "n_future_tokens",
)
MTP_WEIGHT_SUBSTR = (
    "mtp", "multi_token", "eagle", "draft_head", "hc_feat", "embed_mtp",
)

MODELS = [
    ("qwen3-30b", Path.home() / ".exo/models/mlx-community--Qwen3-30B-A3B-4bit"),
    ("gemma4-26b", Path.home() / ".exo/models/mlx-community--gemma-4-26b-a4b-it-4bit"),
    ("gpt-oss-20b", Path.home() / ".exo/models/mlx-community--gpt-oss-20b-MXFP4-Q8"),
    ("llama31-8b", Path.home() / ".caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit"),
    ("deepseek-r1-distill-qwen-14b", Path.home() / ".caravan/mlx-models/mlx-community--DeepSeek-R1-Distill-Qwen-14B-4bit"),
    ("qwen25-14b", Path.home() / ".caravan/mlx-models/mlx-community--Qwen2.5-14B-Instruct-4bit"),
]


def probe(tag: str, d: Path) -> dict:
    out = {"tag": tag, "path": str(d), "exists": d.is_dir()}
    if not d.is_dir():
        return out
    cfg_path = d / "config.json"
    cfg = {}
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text())
    hits = {k: cfg[k] for k in MTP_CONFIG_KEYS if k in cfg}
    # also scan nested
    blob = json.dumps(cfg)
    soft = [k for k in MTP_CONFIG_KEYS if k.lower() in blob.lower() and k not in hits]
    out["config_mtp_fields"] = hits
    out["config_soft_mentions"] = soft
    out["model_type"] = cfg.get("model_type") or cfg.get("architectures")
    out["architectures"] = cfg.get("architectures")
    out["num_hidden_layers"] = cfg.get("num_hidden_layers") or cfg.get("n_layer")
    # safetensors index
    idx = d / "model.safetensors.index.json"
    weight_hits = []
    if idx.is_file():
        j = json.loads(idx.read_text())
        wm = j.get("weight_map") or {}
        for name in wm:
            low = name.lower()
            if any(s in low for s in MTP_WEIGHT_SUBSTR):
                weight_hits.append(name)
    else:
        # single file models: list keys via safetensors header if available
        sts = list(d.glob("*.safetensors"))
        out["safetensors_files"] = [x.name for x in sts[:12]]
        try:
            from safetensors import safe_open
            for st in sts[:4]:
                with safe_open(str(st), framework="numpy") as f:
                    for name in f.keys():
                        low = name.lower()
                        if any(s in low for s in MTP_WEIGHT_SUBSTR):
                            weight_hits.append(name)
        except Exception as e:
            out["safetensors_scan_error"] = f"{type(e).__name__}: {e}"
    out["weight_mtp_like"] = weight_hits[:50]
    out["weight_mtp_count"] = len(weight_hits)
    out["verdict"] = (
        "HAS_MTP_SIGNAL" if (hits or weight_hits) else "NO_MTP_IN_MLX_COPY"
    )
    return out


def main():
    results = [probe(t, p) for t, p in MODELS]
    # Also note original HF repos that might still have MTP (not downloaded)
    notes = {
        "qwen3": "Qwen3 MoE releases sometimes include MTP in original BF16; MLX 4-bit community quants usually strip them. Check Qwen/Qwen3-30B-A3B on HF for mtp_* tensors.",
        "gpt-oss": "OpenAI gpt-oss MXFP4 MLX copy has no small draft sibling; MTP unknown — check openai/gpt-oss-20b original for eagle/mtp.",
        "deepseek": "DeepSeek V3/R1-style MTP is the inspiration; we have DeepSeek-R1-Distill-Qwen-14B-4bit which is a distill and likely has NO MTP heads.",
        "feasibility": "Cheap restore requires (1) original tensors present on HF, (2) matching hidden size / vocab with MLX copy, (3) attaching as draft in guess-ahead path. If MLX copy has zero mtp_* keys, must download original MTP-only tensors and quantize — medium overnight job, not a same-evening prototype unless tensors are small.",
    }
    out = {"models": results, "notes": notes}
    path = Path.home() / ".caravan/bench-2026-11-03/day12-speedups/mtp-research.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    print("WROTE", path)


if __name__ == "__main__":
    main()
