#!/usr/bin/env python3
"""One node's live stats for the Topology drawer (ROADMAP #14).

Runs locally on a Mini and prints JSON: CPU use, GPU Device Utilization %
(from ioreg), optional GPU power W (macmon), temperature (only when a real
reading is available), thermal pressure, RAM, disk free, and the models on
disk. Python 3.9-compatible, stdlib only, no sudo.

GPU % uses IOAccelerator's "Device Utilization %" — macmon's gpu_usage can
read 100% while --split-keepalive only keeps the clock up.

Temperature: macOS has no unprivileged temperature API. If `macmon`
(github.com/vladkens/macmon, reads the SMC without sudo) is installed we
use its cpu_temp_avg (file-cached ~2.5s so 1s polls stay light). Otherwise
temp_c is null — never a guess — and the page shows thermal pressure from
`pmset -g therm` instead.

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
_MM_CACHE = HOME / ".caravan" / "web-ui" / "macmon_cache.json"
_MODELS_LIST_CACHE = HOME / ".caravan" / "web-ui" / "models_list_cache.json"
# macmon pipe takes ~1.5s on these Minis; reuse across 1s polls / SSH gathers.
_MM_TTL = 2.5
_MODELS_TTL = 60.0


def _run(cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _read_json_cache(path, ttl):
    try:
        c = json.loads(path.read_text())
        if time.time() - float(c.get("t", 0)) <= ttl:
            return c.get("data")
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_json_cache(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"t": time.time(), "data": data}))
    except OSError:
        pass


def macmon(*, force=False):
    """SMC sample via macmon. File-cached so 1s polls do not stack 1.5s samples."""
    if not force:
        try:
            c = json.loads(_MM_CACHE.read_text())
            if time.time() - float(c.get("t", 0)) <= _MM_TTL:
                return c.get("data")
        except (OSError, ValueError, TypeError):
            pass
    exe = next((str(p) for p in MACMON if p.exists()), shutil.which("macmon"))
    if not exe:
        _write_json_cache(_MM_CACHE, None)
        return None
    # -i 200: one sample; wall time is still ~1.5s (SMC warmup), hence the cache.
    out = _run([exe, "pipe", "-s", "1", "-i", "200"], timeout=8).strip().splitlines()
    try:
        data = json.loads(out[-1]) if out else None
    except ValueError:
        data = None
    _write_json_cache(_MM_CACHE, data)
    return data




def gpu_util_ioreg():
    """GPU busy % from IOAccelerator — fast, no sudo. Prefer over macmon gpu_usage,
    which can stick at 100% while --split-keepalive only keeps the clock up."""
    out = _run(["ioreg", "-r", "-c", "IOAccelerator", "-d", "1"], timeout=3)
    vals = [int(x) for x in re.findall(r'"Device Utilization %"=(\d+)', out)]
    if not vals:
        return None
    return float(max(vals))


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


def models_on_disk_cached():
    cached = _read_json_cache(_MODELS_LIST_CACHE, _MODELS_TTL)
    if cached is not None:
        return cached
    out = models_on_disk()
    _write_json_cache(_MODELS_LIST_CACHE, out)
    return out


def gather():
    mm = macmon()
    cpu = None
    temp = None
    gpu_power = None
    if mm:
        c = mm.get("cpu_usage_pct")
        if isinstance(c, (int, float)):
            cpu = round(c * 100, 1)   # macmon reports a 0-1 fraction
        t = (mm.get("temp") or {}).get("cpu_temp_avg")
        if isinstance(t, (int, float)) and t > 5:   # 0-ish = no sensor reading
            temp = round(t, 1)
        p = mm.get("gpu_power")
        if isinstance(p, (int, float)):
            gpu_power = round(p, 1)
    if cpu is None:
        cpu = cpu_pct_ps()
    gpu = gpu_util_ioreg()
    return {
        "host": socket.gethostname().split(".")[0],
        "t": time.time(),
        "cpu_pct": cpu,
        "gpu_pct": gpu,
        "gpu_power_w": gpu_power,
        "cpus": os.cpu_count(),
        "load_1m": round(os.getloadavg()[0], 2),
        "temp_c": temp,
        "temp_source": "macmon" if temp is not None else None,
        "thermal_pressure": thermal_pressure(),
        "ram": memory(),
        "disk": disk(),
        "models": models_on_disk_cached(),
    }


if __name__ == "__main__":
    json.dump(gather(), sys.stdout)
    sys.stdout.write("\n")
