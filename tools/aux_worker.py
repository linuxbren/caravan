#!/usr/bin/env python3
"""Opt-in loopback tiny worker. Wait for the primary and free RAM; no downloads.

This does not alter primary workers, Hermes configuration, or shared disk caches.
launchd may retry exit 75. Memory limits are soft MLX caps, not OS reservations.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def admit(available_gb, budget_gb=2.0, reserve_gb=1.75):
    try:
        values = tuple(map(float, (available_gb, budget_gb, reserve_gb)))
        return all(math.isfinite(v) and v > 0 for v in values) and values[0] >= sum(values[1:])
    except (TypeError, ValueError, OverflowError):
        return False


def worker_command(model, port=8196, budget_gb=2.0):
    return [sys.executable, str(ROOT / "agent/mlx_worker.py"),
            "--model", str(model), "--host", "127.0.0.1", "--port", str(port),
            "--no-learn", "--no-split-draft", "--no-split-shared-prefix-cache",
            "--wired-limit", "off", "--memory-limit-gb", str(budget_gb),
            "--cache-limit-gb", "0.25", "--prompt-cache-size", "2",
            "--prompt-cache-bytes", "256MiB", "--no-persist",
            "--memory-recall-tokens", "0", "--max-tokens", "128"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True)
    p.add_argument("--port", type=int, default=8196)
    p.add_argument("--primary-port", type=int, default=8194)
    p.add_argument("--budget-gb", type=float, default=2.0)
    p.add_argument("--reserve-gb", type=float, default=1.75)
    p.add_argument("--wait-seconds", type=float, default=600)
    a = p.parse_args()
    if not (1 <= a.port <= 65535 and 1 <= a.primary_port <= 65535 and a.port != a.primary_port):
        p.error("use distinct valid auxiliary and primary ports")
    if not admit(1e9, a.budget_gb, a.reserve_gb) or not math.isfinite(a.wait_seconds) or a.wait_seconds < 0:
        p.error("use positive finite memory bounds and a finite nonnegative wait")
    model = Path(a.model).expanduser().resolve()
    try:
        if not (model / "config.json").is_file():
            raise ValueError("missing config.json")
        index = model / "model.safetensors.index.json"
        names = set(json.loads(index.read_text())["weight_map"].values()) if index.exists() else {"model.safetensors"}
        if not names or any(not isinstance(n, str) or Path(n).name != n or not n.endswith(".safetensors") or not (model / n).is_file() for n in names):
            raise ValueError("missing or invalid weight shards")
        if sum((model / n).stat().st_size for n in names) / 1e9 + .25 > a.budget_gb:
            raise ValueError("weights exceed the auxiliary budget including 0.25 GB runtime allowance")
    except (OSError, ValueError, KeyError, TypeError) as e:
        p.error(f"use a complete small local MLX model; no downloads: {e}")
    sys.path.insert(0, str(ROOT / "agent"))
    from mlx_split import host_memory_gb
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    until = time.monotonic() + a.wait_seconds
    while True:
        ready = False
        try:
            with http.open(f"http://127.0.0.1:{a.primary_port}/health", timeout=3) as r:
                ready = r.status == 200
        except Exception:
            pass
        available = host_memory_gb()[1]
        if ready and admit(available, a.budget_gb, a.reserve_gb):
            break
        print(f"aux wait: primary_ready={ready}, available_gb={available}, budget_gb={a.budget_gb}, reserve_gb={a.reserve_gb}", flush=True)
        if time.monotonic() >= until:
            return 75
        time.sleep(min(10, max(0, until - time.monotonic())))
    command = worker_command(model, a.port, a.budget_gb)
    os.execv(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main())
