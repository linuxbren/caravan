#!/usr/bin/env python3
"""Fetch ONLY Orvena MTP tensor byte ranges; never copy from another Mini."""
import argparse
import hashlib
import json
import struct
import urllib.request
from pathlib import Path

SOURCE = "https://huggingface.co/Orvena/Orvena-4B/resolve/main/"

def get(name, start=None, end=None):
    headers = {"Range": f"bytes={start}-{end}"} if start is not None else {}
    # A unique query keeps caches from confusing distinct Range requests.
    url = SOURCE + name + (f"?caravan_range={start}-{end}" if headers else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as r:
        if headers and r.status != 206:
            raise RuntimeError(f"Server ignored range for {name}; refusing whole shard")
        b = r.read()
    if headers and len(b) != end - start + 1:
        raise RuntimeError("short range read")
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    args = ap.parse_args()
    target = Path(args.target).expanduser()
    cfg = json.loads((target / "config.json").read_text())
    upstream = json.loads(get("config.json"))
    if cfg["text_config"]["hidden_size"] != 2560 or cfg["text_config"]["vocab_size"] != 248320:
        raise ValueError("Wrong target; requires Orvena-4B-MLX-4bit")
    index = json.loads(get("model.safetensors.index.json"))["weight_map"]
    keys = {k: v for k, v in index.items() if k.startswith("mtp.")}
    import numpy as np
    arrays = {}
    # safetensors numpy cannot encode BF16; use MLX to preserve original bytes.
    import mlx.core as mx
    for fn in sorted(set(keys.values())):
        n = struct.unpack("<Q", get(fn, 0, 7))[0]
        header = json.loads(get(fn, 8, 7 + n))
        for k in keys:
            if keys[k] != fn:
                continue
            d = header[k]
            lo, hi = d["data_offsets"]
            print(f"fetch {k}: {hi-lo} bytes", flush=True)
            raw = get(fn, 8 + n + lo, 8 + n + hi - 1)
            if d["dtype"] != "BF16":
                raise ValueError("expected BF16")
            v = mx.array(np.frombuffer(raw, dtype=np.uint16).copy()).view(mx.bfloat16).reshape(d["shape"])
            name = k.removeprefix("mtp.")
            if v.ndim == 1:  # Qwen zero-centered RMSNorm, sanitize exactly once
                v = v + 1.0
            arrays[name] = v
    out = target / "caravan-mtp"
    out.mkdir(exist_ok=True)
    mx.save_safetensors(str(out / "model.safetensors"), arrays)
    meta = {"model_type": "qwen3_5_mtp", "text_config": upstream["text_config"],
            "source_repo": "Orvena/Orvena-4B", "target_repo": "Orvena/Orvena-4B-MLX-4bit",
            "target_config_sha256": hashlib.sha256((target / "config.json").read_bytes()).hexdigest(),
            "sanitized": True, "tensors": len(arrays),
            "payload_bytes": sum(x.nbytes for x in arrays.values())}
    (out / "config.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta), flush=True)

if __name__ == "__main__":
    main()
