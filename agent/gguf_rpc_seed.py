"""GGUF stage 2 (Day 18): a peer Mini loads its share from its OWN disk.

llama.cpp RPC: for every tensor over 10 MiB the lead first sends only an
FNV-1a hash (SET_TENSOR_HASH); `rpc-server -c` answers from
<cache>/rpc/<hash> if it has that file, so the bytes never cross the link.
This script fills that cache from the peer's local copy of the same GGUF,
for the layers the peer will hold. Same trust model as before: rpc-server
still listens on 127.0.0.1 only, reached over the SSH tunnel.

    python gguf_rpc_seed.py <model.gguf> --shares 1,1 --index 1 [--cache-dir D]

Prints one JSON line: {"tensors", "new", "have", "bytes", "layers", "s"}.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HASH_THRESHOLD = 10 * 1024 * 1024
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("CARAVAN_FNV_SEED", "~/.caravan/bin/caravan-fnv-seed")).expanduser()


def rpc_cache_dir() -> Path:
    """Same rule as rpc-server's fs_get_cache_directory() + 'rpc/' on macOS/Linux."""
    if os.environ.get("LLAMA_CACHE"):
        base = Path(os.environ["LLAMA_CACHE"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "llama.cpp"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "llama.cpp"
    return base / "rpc"


def device_layers(n_layer: int, shares: list, index: int, pad: int = 1) -> range:
    """Layers llama.cpp gives device `index` (llama-model.cpp: upper_bound on the
    cumulative split over n_layer+1 slots; slot n_layer is the output layer).
    Padded by `pad` on each side: an extra cached tensor costs disk, a missing
    one only costs link bytes."""
    tot = float(sum(shares))
    cum, acc = [], 0.0
    for s in shares:
        acc += s / tot
        cum.append(acc)
    slots = n_layer + 1
    mine = [il for il in range(slots)
            if min(bisect.bisect_right(cum, il / slots), len(shares) - 1) == index]
    if not mine:
        return range(0)
    return range(max(0, mine[0] - pad), min(slots, mine[-1] + 1 + pad))


def tensor_plan(path: str, layers: range | None):
    """[(name, offset, size)] for tensors > HASH_THRESHOLD in the given layers."""
    src = Path(os.environ.get("CARAVAN_LLAMA_SRC", "~/dev/llama.cpp")).expanduser() / "gguf-py"
    if src.is_dir():
        sys.path.insert(0, str(src))
    from gguf import GGUFReader
    r = GGUFReader(path)
    n_layer = None
    for k, f in r.fields.items():
        if k.endswith(".block_count"):
            n_layer = int(f.parts[f.data[0]][0])
    out = []
    for t in r.tensors:
        size = int(t.n_bytes)
        if size <= HASH_THRESHOLD:
            continue
        if layers is not None:
            if t.name.startswith("blk."):
                if int(t.name.split(".")[1]) not in layers:
                    continue
            elif t.name.startswith("output") and (n_layer is None or n_layer not in layers):
                continue
            elif t.name.startswith("token_embd"):
                continue  # input layer stays on the lead's CPU/first device
        out.append((t.name, int(t.data_offset), size))
    return out, n_layer


def ensure_bin() -> Path:
    if BIN.is_file():
        return BIN
    BIN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cc", "-O2", "-o", str(BIN), str(HERE / "fnv_seed.c")], check=True)
    return BIN


def seed(path: str, shares: list | None = None, index: int | None = None,
         cache_dir: Path | None = None) -> dict:
    t0 = time.time()
    cache = Path(cache_dir) if cache_dir else rpc_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    plan, n_layer = tensor_plan(path, None)
    layers = None
    if shares and index is not None and n_layer:
        layers = device_layers(n_layer, shares, index)
        plan, _ = tensor_plan(path, layers)
    feed = "".join("%d %d\n" % (o, s) for _, o, s in plan)
    p = subprocess.run([str(ensure_bin()), str(Path(path).expanduser()), str(cache)],
                       input=feed, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-400:] or "seed failed")
    lines = [ln.split() for ln in p.stdout.splitlines() if ln.strip()]
    return {"tensors": len(plan), "new": sum(1 for x in lines if x[1] == "new"),
            "have": sum(1 for x in lines if x[1] == "have"),
            "bytes": sum(s for _, _, s in plan),
            "layers": [layers.start, layers.stop] if layers is not None else None,
            "n_layer": n_layer, "cache": str(cache), "s": round(time.time() - t0, 1)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("gguf")
    ap.add_argument("--shares", default=None, help="tensor-split, e.g. 1,1")
    ap.add_argument("--index", type=int, default=None, help="this Mini's device index (lead=0)")
    ap.add_argument("--cache-dir", default=None)
    a = ap.parse_args(argv)
    shares = [float(x) for x in a.shares.split(",")] if a.shares else None
    print(json.dumps(seed(a.gguf, shares, a.index, a.cache_dir)), flush=True)


if __name__ == "__main__":
    main()
