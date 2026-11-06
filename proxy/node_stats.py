#!/usr/bin/env python3
"""One node's live stats for the Topology drawer (ROADMAP #14).

Runs locally on a Mini and prints JSON: CPU use, GPU Device Utilization %
(from ioreg), optional GPU power W (macmon), temperature (only when a real
reading is available), thermal pressure, RAM, and disk free.
Python 3.9-compatible, stdlib only, no sudo.

GPU % uses IOAccelerator's "Device Utilization %" — macmon's gpu_usage can
read 100% while --split-keepalive only keeps the clock up.

Temperature / CPU / GPU watts come from a long-lived `macmon pipe -i 500`
daemon started on first poll and stopped after ~30s with no polls. That keeps
500ms Topology refreshes fresh without paying macmon's ~1.5s cold start each
time. `models_on_disk()` stays here for the future model picker but is not
gathered for /api/nodes.

    python3 proxy/node_stats.py                 # JSON to stdout
    python3 proxy/node_stats.py --macmon-daemon # background pipe writer
"""
import json
import os
import re
import shutil
import signal
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
_UI = HOME / ".caravan" / "web-ui"
_SIZE_CACHE = _UI / "model_sizes.json"
_MM_LIVE = _UI / "macmon_live.json"          # {"t": epoch, "data": {...}}
_MM_PID = _UI / "macmon_pipe.pid"
_MM_LAST_POLL = _UI / "macmon_last_poll"     # mtime = last gather()/ensure
_MM_IDLE_STOP = 30.0
_MM_INTERVAL_MS = 500


def _run(cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _touch_last_poll():
    try:
        _UI.mkdir(parents=True, exist_ok=True)
        _MM_LAST_POLL.write_text(str(time.time()))
    except OSError:
        pass


def _last_poll_age():
    try:
        return time.time() - _MM_LAST_POLL.stat().st_mtime
    except OSError:
        return 1e9


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid():
    try:
        return int(_MM_PID.read_text().strip())
    except (OSError, ValueError):
        return None


def _stop_macmon_daemon():
    pid = _read_pid()
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.05)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    try:
        _MM_PID.unlink()
    except OSError:
        pass


def _macmon_exe():
    return next((str(p) for p in MACMON if p.exists()), shutil.which("macmon"))


def run_macmon_daemon():
    """Long-lived: macmon pipe -i 500 → macmon_live.json; exit after idle stop."""
    _UI.mkdir(parents=True, exist_ok=True)
    _MM_PID.write_text(str(os.getpid()))
    exe = _macmon_exe()
    if not exe:
        return
    # Detach from the caller’s process group so web/SSH exit doesn’t kill us.
    try:
        os.setsid()
    except OSError:
        pass
    proc = subprocess.Popen(
        [exe, "pipe", "-i", str(_MM_INTERVAL_MS)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )
    try:
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            try:
                tmp = _MM_LIVE.with_suffix(".tmp")
                tmp.write_text(json.dumps({"t": time.time(), "data": data}))
                tmp.replace(_MM_LIVE)
            except OSError:
                pass
            if _last_poll_age() > _MM_IDLE_STOP:
                break
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            if _read_pid() == os.getpid():
                _MM_PID.unlink()
        except OSError:
            pass


def ensure_macmon_daemon():
    """Touch last-poll and start the pipe daemon if it is not already running."""
    _touch_last_poll()
    pid = _read_pid()
    if pid and _pid_alive(pid):
        return
    if not _macmon_exe():
        return
    _UI.mkdir(parents=True, exist_ok=True)
    # Re-exec this file as a daemon so lead (in-process) and packer (SSH CLI)
    # share the same live file.
    cmd = [sys.executable, str(Path(__file__).resolve()), "--macmon-daemon"]
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
        close_fds=True,
    )


def macmon_live():
    """Latest sample from the background pipe, or None if not ready yet."""
    ensure_macmon_daemon()
    try:
        c = json.loads(_MM_LIVE.read_text())
        data = c.get("data")
        # Stale guard: if the daemon died mid-write, ignore very old samples.
        age = time.time() - float(c.get("t", 0))
        if age > 5.0:
            return None, age
        return data, age
    except (OSError, ValueError, TypeError):
        return None, None


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
        m = re.match(r"^(.+?):\s+(\d+)\.?$", line)
        if m:
            v[m.group(1).strip()] = int(m.group(2)) * page
    try:
        total = int(_run(["sysctl", "-n", "hw.memsize"]).strip())
    except ValueError:
        total = 0
    used = (v.get("Anonymous pages", 0) - v.get("Pages purgeable", 0)
            + v.get("Pages wired down", 0) + v.get("Pages occupied by compressor", 0))
    if used <= 0:
        used = v.get("Pages active", 0) + v.get("Pages wired down", 0)
    # Reclaimable-aware (matches memory_guard / macOS pressure better than raw free).
    available = (v.get("Pages free", 0) + v.get("Pages speculative", 0)
                 + v.get("Pages purgeable", 0) + v.get("Pages inactive", 0))
    return {"total_gb": round(total / 1e9, 1), "used_gb": round(used / 1e9, 1),
            "free_gb": round(max(0, total - used) / 1e9, 1),
            "available_gb": round(available / 1e9, 1)}


def disk():
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
    """Reusable for the future model-selection screen; not used by /api/nodes."""
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
    mm, mm_age = macmon_live()
    # Brief wait on first open so the daemon’s first sample can land.
    if mm is None:
        for _ in range(10):
            time.sleep(0.1)
            mm, mm_age = macmon_live()
            if mm is not None:
                break
    cpu = None
    temp = None
    gpu_power = None
    if mm:
        c = mm.get("cpu_usage_pct")
        if isinstance(c, (int, float)):
            cpu = round(c * 100, 1)   # macmon reports a 0-1 fraction
        t = (mm.get("temp") or {}).get("cpu_temp_avg")
        if isinstance(t, (int, float)) and t > 5:
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
        "macmon_age_s": round(mm_age, 3) if isinstance(mm_age, (int, float)) else None,
        "thermal_pressure": thermal_pressure(),
        "ram": memory(),
        "disk": disk(),
    }


if __name__ == "__main__":
    if "--macmon-daemon" in sys.argv:
        run_macmon_daemon()
        sys.exit(0)
    if "--stop-macmon" in sys.argv:
        _stop_macmon_daemon()
        sys.exit(0)
    json.dump(gather(), sys.stdout)
    sys.stdout.write("\n")
