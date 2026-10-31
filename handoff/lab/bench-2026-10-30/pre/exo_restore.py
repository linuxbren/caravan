#!/usr/bin/env python3
"""Boot-time restore of the Qwen instance on the exo1+exo2 EXO cluster (lives on exo2: ~/macstax/exo_restore.py).

Why: after a power cut (2026-10-04) EXO came back with both nodes connected but no instance loaded,
so Hermes and the vet server had no model until someone re-placed it by hand.

Behaviour (run once at login by launchd, com.postrockfoundry.exo-restore):
  1. Wait (up to 20 min) for the EXO API and both nodes in the topology.
  2. If ANY instance exists, do nothing: never fight a model someone placed on purpose.
  3. Otherwise place Qwen3.6-35B-A3B-5bit as a 2-node Pipeline/MlxRing instance (weights are already on both
     nodes, so nothing downloads), wait for RunnerReady, send one tiny chat, then run talaria_check.sh.
Everything is logged to ~/macstax/logs/exo_restore.log.  `--dry-run` only reports what it would do.
Python 3.9 compatible (macOS system python).
"""
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:52415"
MODEL = "mlx-community/Qwen3.6-35B-A3B-5bit"
PLACE = {"model_id": MODEL, "sharding": "Pipeline", "instance_meta": "MlxRing", "min_nodes": 2}
LOG = Path.home() / "macstax" / "logs" / "exo_restore.log"
DRY = "--dry-run" in sys.argv


def log(msg):
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def call(path, body=None, timeout=10):
    req = urllib.request.Request(API + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def state():
    try:
        return call("/state")
    except Exception:
        return None


def runner_kinds(s):
    return sorted({next(iter(v)) if isinstance(v, dict) and v else str(v) for v in (s.get("runners") or {}).values()})


def main():
    log(f"start{' (dry run)' if DRY else ''}")
    deadline = time.time() + 20 * 60
    s = None
    while time.time() < deadline:
        s = state()
        nodes = len(((s or {}).get("topology") or {}).get("nodes") or [])
        if s is not None and nodes >= 2:
            break
        time.sleep(15)
    else:
        log("gave up: EXO API or both nodes not up after 20 min")
        return 1
    if s.get("instances"):
        log(f"instance already present ({len(s['instances'])}), nothing to do; runners {runner_kinds(s)}")
        return 0
    if DRY:
        log(f"would place: {PLACE}")
        return 0
    log(f"no instance: placing {PLACE}")
    log(f"place_instance -> {call('/place_instance', PLACE, timeout=60).get('message')}")
    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        s = state() or {}
        kinds = runner_kinds(s)
        if kinds and all(k == "RunnerReady" for k in kinds):
            break
        time.sleep(10)
    else:
        log(f"runners not ready after 15 min: {kinds}")
        return 1
    log(f"runners ready: {kinds}")
    try:
        r = call("/v1/chat/completions", {"model": MODEL, "max_tokens": 5,
                                          "messages": [{"role": "user", "content": "Reply with: ok"}]}, timeout=300)
        log(f"test chat: {r['choices'][0]['message']['content'][:40]!r}")
    except Exception as e:
        log(f"test chat failed: {e}")
    chk = Path.home() / "macstax" / "talaria_check.sh"
    if chk.exists():
        out = subprocess.run([str(chk)], capture_output=True, text=True, timeout=600).stdout
        log("talaria_check: " + " | ".join(l.strip() for l in out.splitlines() if "PASS" in l or "FAIL" in l))
    return 0


if __name__ == "__main__":
    sys.exit(main())
