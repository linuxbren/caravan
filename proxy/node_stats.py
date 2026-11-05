#!/usr/bin/env python3
"""One node's live stats for the Topology drawer (ROADMAP #14).

Runs locally on a Mini and prints JSON: CPU use, temperature (only when a
real reading is available), thermal pressure, RAM, disk free, and the
models on disk. Python 3.9-compatible, stdlib only, no sudo.

Temperature: macOS has no unprivileged temperature API. If `macmon`
(github.com/vladkens/macmon, reads the SMC without sudo) is installed we
use its cpu_temp_avg. Otherwise temp_c is null — never a guess — and the
page shows thermal pressure from `pmset -g therm` instead.

    python3 proxy/node_stats.py            # JSON to stdout
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
MODEL_DIRS = [HOME / ".exo" / "models", HOME / ".caravan" / "mlx-models"]
SKIP = {"caches", "drafts"}
MACMON = [HOME / ".cargo" / "bin" / "macmon", Path("/opt/homebrew/bin/macmon"),
          Path("/usr/local/bin/macmon")]
_SIZE_CACHE = HOME / ".caravan" / "web-ui" / "model_sizes.json"


def _run(cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def macmon():
    exe = next((str(p) for p in MACMON if p.exists()), shutil.which("macmon"))
    if not exe:
        return None
    out = _run([exe, "pipe", "-s", "1", "-i", "400"], timeout=8).strip().splitlines()
    try:
        return json.loads(out[-1]) if out else None
    except ValueError:
        return None


def cpu_pct_ps():
    out = _run(["ps", "-A", "-o", "%cpu="])
    tot = sum(float(x) for x in out.split() if re.match(r"^[\d.]+$", x))
    n = os.cpu_count() or 1
    return round(min(100.0, tot / n), 1)


def thermal_pressure():
    out = _run(["pmset", "-g", "therm"])
    if "No thermal warning level has been recorded" in out:
        return "nominal"
    m = re.search(r"thermal warning level.*?(\d+)", out, re.I)
    if m:
        return f"warning level {m.group(1)}"
    m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", out)
    if m:
        return f"CPU speed limit {m.group(1)}%"
    return "unknown"


def memory():
    out = _run(["vm_stat"])
    ps = re.search(r"page size of (\d+) bytes", out)
    page = int(ps.group(1)) if ps else 16384
    v = {}
    for line in out.splitlines()[1:]:
        m = re.match(r"^(.+?):\s+(\d+)\.$", line)
        if m:
            v[m.group(1).strip()] = int(m.group(2)) * page
    try:
        total = int(_run(["sysctl", "-n", "hw.memsize"]).strip())
    except ValueError:
        total = 0
    # Same idea as Activity Monitor's "used": app + wired + compressed.
    used = (v.get("Anonymous pages", 0) - v.get("Pages purgeable", 0)
            + v.get("Pages wired down", 0) + v.get("Pages occupied by compressor", 0))
    if used <= 0:
        used = v.get("Pages active", 0) + v.get("Pages wired down", 0)
    return {"total_gb": round(total / 1e9, 1), "used_gb": round(used / 1e9, 1),
            "free_gb": round(max(0, total - used) / 1e9, 1)}


def disk():
    # Data volume is where models live; "/" on APFS shares its space.
    p = HOME if HOME.exists() else Path("/")
    u = shutil.disk_usage(str(p))
    return {"total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1),
            "used_gb": round((u.total - u.free) / 1e9, 1)}


def _dir_bytes(p: Path) -> int:
    tot = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                tot += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return tot


def models_on_disk():
    try:
        cache = json.loads(_SIZE_CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    out, changed = [], False
    for base in MODEL_DIRS:
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir() or d.name in SKIP or d.name.startswith("."):
                continue
            key = str(d)
            try:
                mt = d.stat().st_mtime
            except OSError:
                continue
            c = cache.get(key)
            if not c or c.get("mtime") != mt:
                c = {"mtime": mt, "bytes": _dir_bytes(d)}
                cache[key] = c
                changed = True
            out.append({"name": d.name, "where": str(base).replace(str(HOME), "~"),
                        "size_gb": round(c["bytes"] / 1e9, 1)})
    if changed:
        try:
            _SIZE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _SIZE_CACHE.write_text(json.dumps(cache))
        except OSError:
            pass
    return out


def gather():
    mm = macmon()
    cpu = None
    temp = None
    gpu = None
    if mm:
        c = mm.get("cpu_usage_pct")
        if isinstance(c, (int, float)):
            cpu = round(c * 100, 1)   # macmon reports a 0-1 fraction
        t = (mm.get("temp") or {}).get("cpu_temp_avg")
        if isinstance(t, (int, float)) and t > 5:   # 0-ish = no sensor reading
            temp = round(t, 1)
        g = mm.get("gpu_usage")
        if isinstance(g, list) and len(g) == 2:
            gpu = round(g[1] * 100, 1)
    if cpu is None:
        cpu = cpu_pct_ps()
    return {
        "host": socket.gethostname().split(".")[0],
        "t": time.time(),
        "cpu_pct": cpu,
        "gpu_pct": gpu,
        "cpus": os.cpu_count(),
        "load_1m": round(os.getloadavg()[0], 2),
        "temp_c": temp,
        "temp_source": "macmon" if temp is not None else None,
        "thermal_pressure": thermal_pressure(),
        "ram": memory(),
        "disk": disk(),
        "models": models_on_disk(),
    }


if __name__ == "__main__":
    json.dump(gather(), sys.stdout)
    sys.stdout.write("\n")
