"""Truthful download progress for MLX fetches (classic HF + hf_xet).

Finding (Nov 5 2026): with hf_xet, `.incomplete` often stays at 0 bytes and
`~/.cache/huggingface/xet` may not grow while `nettop` still shows 3–6 MB/s
into the fetch process. File-only progress freezes; network bytes do not.

Fallback chain (most reliable first):
  1. JSONL progress hook from mlx_split_fetch (`/tmp/caravan-progress-<folder>.jsonl`)
  2. On-disk finished shards + .incomplete
  3. Cumulative `bytes_in` for the fetch pid via `nettop -P -L 1 -p <pid> -J bytes_in`
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

STALL_SECS = float(os.environ.get("CARAVAN_DOWNLOAD_STALL_SECS", "30"))
PROGRESS_DIR = Path(os.environ.get("CARAVAN_PROGRESS_DIR", "/tmp"))


def progress_path_for(repo_or_folder: str) -> Path:
    folder = repo_or_folder.replace("/", "--")
    return PROGRESS_DIR / f"caravan-progress-{folder}.jsonl"


def measure_disk(dest: str) -> dict:
    dest_p = Path(dest).expanduser()
    done = incomplete = n_inc = 0
    if not dest_p.exists():
        return {"done_bytes": 0, "incomplete_bytes": 0, "have_bytes": 0,
                "n_incomplete": 0, "source": "disk"}
    try:
        for pat in ("*.safetensors", "*.gguf"):
            for p in dest_p.glob(pat):
                try:
                    done += p.stat().st_size
                except OSError:
                    pass
        cache_dl = dest_p / ".cache" / "huggingface" / "download"
        if cache_dl.is_dir():
            for p in cache_dl.rglob("*"):
                if p.is_file() and p.name.endswith(".incomplete"):
                    # HF can leave the .incomplete beside the finished file: count once.
                    rel = p.relative_to(cache_dl).as_posix()[: -len(".incomplete")]
                    if (dest_p / rel).is_file() or (dest_p / p.name[: -len(".incomplete")]).is_file():
                        continue
                    try:
                        incomplete += p.stat().st_size
                        n_inc += 1
                    except OSError:
                        pass
        # xet blobs (sometimes grow even when .incomplete is 0)
        xet = dest_p / ".cache" / "huggingface" / "xet"
        xet_bytes = 0
        if xet.is_dir():
            for p in xet.rglob("*"):
                if p.is_file():
                    try:
                        xet_bytes += p.stat().st_size
                    except OSError:
                        pass
    except OSError:
        xet_bytes = 0
    have = done + incomplete
    # Prefer disk+incomplete; if both tiny but xet grew, count xet as have
    if have < 1_000_000 and xet_bytes > have:
        have = xet_bytes
    return {
        "done_bytes": done,
        "incomplete_bytes": incomplete,
        "have_bytes": have,
        "n_incomplete": n_inc,
        "xet_bytes": xet_bytes,
        "source": "disk",
    }


def read_hook(repo_or_folder: str) -> Optional[dict]:
    p = progress_path_for(repo_or_folder)
    if not p.is_file():
        return None
    try:
        lines = p.read_text().strip().splitlines()
        if not lines:
            return None
        blob = json.loads(lines[-1])
        if not isinstance(blob, dict):
            return None
        blob["source"] = "hook"
        return blob
    except (OSError, ValueError):
        return None


def nettop_bytes_in(pid: int) -> Optional[int]:
    """Cumulative bytes received by pid (macOS nettop). None if unavailable.

    Only the row named "<proc>.<pid>,<bytes>," for the requested pid counts, read with
    -x (raw numbers). The old "largest number on any line" parse could pick up another
    process or a scaled value and reported 851 GB for a 278 MB download (Nov 6, 2026).
    """
    if not pid or pid <= 0:
        return None
    try:
        r = subprocess.run(
            ["nettop", "-P", "-x", "-L", "1", "-p", str(int(pid)), "-J", "bytes_in"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_nettop_bytes_in(r.stdout or "", int(pid))


def parse_nettop_bytes_in(out: str, pid: int) -> Optional[int]:
    tot, seen = 0, False
    for line in out.splitlines():
        m = re.match(r"^.*\.(\d+),(\d+),?\s*$", line.strip())
        if m and int(m.group(1)) == pid:
            tot += int(m.group(2)); seen = True
    return tot if seen else None

def find_fetch_pids(repo_id: str) -> list:
    """Local pids running mlx_split_fetch for repo.

    macOS `pgrep -af` often prints only PIDs (no args), so we prefer `ps`.
    """
    needle = f"mlx_split_fetch.py {repo_id}" if repo_id else "mlx_split_fetch.py"
    try:
        r = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        r = None
    out = []
    if r and r.stdout:
        for line in r.stdout.splitlines():
            if needle not in line:
                continue
            parts = line.strip().split(None, 1)
            if parts and parts[0].isdigit():
                out.append(int(parts[0]))
        if out:
            return out
    try:
        r2 = subprocess.run(
            ["pgrep", "-f", needle],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return out
    return [int(p) for p in (r2.stdout or "").split() if p.strip().isdigit()]


def fmt_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds != seconds or seconds < 0:  # noqa: PLR0124
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def grew(prev: Optional[dict], have: int, disk_have=None, net_raw=None) -> bool:
    """Real growth since the last sample on ANY signal (shown bytes, disk, network),
    not a new maximum: a clamped or max()'d display value can sit still while
    files are still landing, which used to raise a false "stalled?"."""
    if not prev:
        return have > 0
    if have > int(prev.get("have_bytes") or 0):
        return True
    if disk_have is not None and prev.get("disk_have") is not None and int(disk_have) > int(prev["disk_have"]):
        return True
    pn = prev.get("net_raw") if prev.get("net_raw") is not None else prev.get("net_last")
    if net_raw is not None and pn is not None and int(net_raw) > int(pn):
        return True
    return False


def combine_progress(
    *,
    dest: str,
    repo_id: str,
    total_bytes: Optional[int],
    pid: Optional[int] = None,
    prev: Optional[dict] = None,
    net_baseline: Optional[int] = None,
) -> dict:
    """Merge hook / disk / nettop into one progress snapshot."""
    now = time.time()
    total = int(total_bytes or 0)
    hook = read_hook(repo_id)
    disk = measure_disk(dest)

    # Resolve pid
    pids = [pid] if pid else find_fetch_pids(repo_id)
    pids = [p for p in pids if p]
    net_raw = None
    for p in pids:
        net_raw = nettop_bytes_in(p)
        if net_raw is not None:
            pid = p
            break

    # Network bytes relative to baseline (first sample)
    net_have = None
    baseline = net_baseline
    if prev and prev.get("net_baseline") is not None:
        baseline = int(prev["net_baseline"])
    if net_raw is not None:
        if baseline is None:
            baseline = net_raw
        net_have = max(0, net_raw - int(baseline))

    # Choose have_bytes
    source = "starting"
    have = 0
    if hook and hook.get("have_bytes") is not None:
        have = int(hook["have_bytes"])
        source = "hook"
    elif disk["have_bytes"] > 0 and (
        disk["incomplete_bytes"] > 0
        or disk["done_bytes"] > 0
        or disk.get("xet_bytes", 0) > 1_000_000
    ):
        # Prefer disk when it is actually moving / has content
        have = int(disk["have_bytes"])
        source = "disk"
        # If disk frozen (incomplete=0 growth) but net moving, use net
        if (
            disk["incomplete_bytes"] == 0
            and net_have is not None
            and prev
            and int(prev.get("have_bytes") or 0) == have
            and net_have > have
        ):
            have = net_have
            source = "nettop"
    elif net_have is not None and net_have > 0:
        have = net_have
        source = "nettop"
    elif disk["have_bytes"] > 0:
        have = int(disk["have_bytes"])
        source = "disk"

    if total > 0:
        have = min(have, total)  # never show more than the Mini downloads

    # Speed from delta
    speed = 0.0
    if prev and prev.get("t") and prev.get("have_bytes") is not None:
        dt = max(0.001, now - float(prev["t"]))
        speed = max(0.0, (have - int(prev["have_bytes"])) / dt)

    stalled = False
    last_byte_t = float((prev or {}).get("last_byte_t") or now)
    if grew(prev, have, disk.get("have_bytes"), net_raw):
        last_byte_t = now
    elif source != "starting" and (now - last_byte_t) >= STALL_SECS:
        stalled = True
    if source == "starting":
        last_byte_t = float((prev or {}).get("last_byte_t") or now)

    pct = 0
    if total > 0 and have > 0:
        pct = max(0, min(99, int(have * 100 / total)))
        if have >= total and disk.get("n_incomplete", 1) == 0 and disk.get("done_bytes", 0) > 0:
            pct = 100
    eta_s = ((total - have) / speed) if (speed > 0 and total > have) else None
    mb_s = speed / 1e6

    if source == "starting" or (have == 0 and source != "disk"):
        msg = "starting…"
        pct = 0
    else:
        if total:
            msg = f"{have/1e9:.2f}/{total/1e9:.2f} GB · {mb_s:.1f} MB/s · ETA {fmt_eta(eta_s)}"
        else:
            msg = f"{have/1e9:.2f} GB · {mb_s:.1f} MB/s"
        if source == "nettop":
            msg += " · via network"
        elif source == "hook":
            msg += " · live"
        if disk.get("n_incomplete"):
            msg += f" · {disk['n_incomplete']} active"
        if stalled:
            msg += " · stalled?"

    return {
        "pct": pct,
        "msg": msg,
        "have_bytes": have,
        "total_bytes": total or None,
        "speed_bps": speed,
        "mb_s": round(mb_s, 2),
        "eta_s": None if eta_s is None else int(eta_s),
        "t": now,
        "last_byte_t": last_byte_t,
        "n_incomplete": disk.get("n_incomplete", 0),
        "source": source,
        "stalled": stalled,
        "pid": pid,
        "net_baseline": baseline,
        "net_raw": net_raw,
        "disk_have": disk.get("have_bytes"),
    }
