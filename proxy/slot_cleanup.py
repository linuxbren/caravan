#!/usr/bin/env python3
"""Stale disk-KV-slot cleanup for Caravan.

slot_pin_proxy.py saves every session's llama-server KV cache to
SLOT_SAVE_DIR/<fingerprint>.bin after each reply (issue #4) -- ~1 GB per
session -- and nothing ever removed them, which is how node-a ended up
with ~154 GB of September session snapshots. This module removes (or
archives) slot files that haven't been written for MAX_AGE_DAYS, and
drops their now-pointless entries from the proxy's session->slot map
(session_slots.json).

"Last used" == file mtime: the proxy rewrites a session's .bin after
every successful reply, so mtime is exactly the last time that session
was active. (A restore alone doesn't touch mtime, but a restore is always
followed by a reply, which re-saves.)

Runs two ways:
  * automatically, inside slot_pin_proxy.py: once at startup and then
    every INTERVAL_HOURS on a background thread, holding the proxy's FIFO
    gate while it removes files so it can never race a slot save/restore;
  * standalone:
        python3 -m proxy.slot_cleanup --dry-run           # from repo root
        python3 proxy/slot_cleanup.py --max-age-days 14 --mode archive

Settings, by precedence: CLI flag > env var > "slot_cleanup" object in
~/.caravan/config.json (or $CARAVAN_CONFIG) > default.

    flag                     env                                  default
    --mode                   CARAVAN_SLOT_CLEANUP (delete|archive|off)  delete
    --max-age-days           CARAVAN_SLOT_MAX_AGE_DAYS            30
    --archive-dir            CARAVAN_SLOT_ARCHIVE_DIR             ~/.caravan/llama-server/slots-archive
    --interval-hours         CARAVAN_SLOT_CLEANUP_INTERVAL_HOURS  6   (proxy only; <=0 = startup only)
    --slot-dir               CARAVAN_SLOT_SAVE_DIR                ~/.caravan/llama-server/slots
    --state-file             CARAVAN_PROXY_STATE_FILE             ~/.caravan/proxy/session_slots.json
    --max-count              CARAVAN_SLOT_MAX_COUNT               200 (0 = no count cap)
    --max-gb                 CARAVAN_SLOT_MAX_GB                  50  (0 = no size cap)
    --protect-minutes        CARAVAN_SLOT_PROTECT_MINUTES         30

Per-Mini cap (v2, 2026-10-31): after the age rule, if the saved chats
left -- llama.cpp *.bin in slot_dir plus MLX *.safetensors in mlx_dir,
counted together -- are more than max_count files or max_gb in total,
the least recently used (oldest mtime) are evicted first until both
limits hold, using the same mode (delete / archive / off). A session
that is active is never evicted: it's in a llama.cpp slot right now,
had a turn or a save in the last protect_minutes, or (inside the proxy)
the proxy reports it as live. So the cap can be exceeded if everything
left is active; that is logged.

Stdlib only, Python 3.9-safe.
"""
import argparse
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, List, NamedTuple, Optional

MODES = ("delete", "archive", "off")

DEFAULTS = {
    "mode": "delete",
    "max_age_days": 30.0,
    "interval_hours": 6.0,
    "archive_dir": str(Path.home() / ".caravan" / "llama-server" / "slots-archive"),
    "slot_dir": str(Path.home() / ".caravan" / "llama-server" / "slots"),
    "state_file": str(Path.home() / ".caravan" / "proxy" / "session_slots.json"),
    # v2 (2026-10-31): Caravan's MLX worker saves <fp>.safetensors in
    # ~/.caravan/mlx/prompt-cache; same age rule as the llama.cpp .bin
    # files. Off unless set: the proxy passes its MLX cache dir, the CLI
    # takes --mlx-dir / CARAVAN_MLX_CACHE_DIR. "" / "off" = don't scan.
    "mlx_dir": "",
    # Per-Mini cap on saved chats (llama.cpp + MLX together), LRU first.
    "max_count": 200,
    "max_gb": 50.0,
    "protect_minutes": 30.0,
}

ENV_VARS = {
    "mode": "CARAVAN_SLOT_CLEANUP",
    "max_age_days": "CARAVAN_SLOT_MAX_AGE_DAYS",
    "interval_hours": "CARAVAN_SLOT_CLEANUP_INTERVAL_HOURS",
    "archive_dir": "CARAVAN_SLOT_ARCHIVE_DIR",
    "slot_dir": "CARAVAN_SLOT_SAVE_DIR",
    "state_file": "CARAVAN_PROXY_STATE_FILE",
    "mlx_dir": "CARAVAN_MLX_CACHE_DIR",
    "max_count": "CARAVAN_SLOT_MAX_COUNT",
    "max_gb": "CARAVAN_SLOT_MAX_GB",
    "protect_minutes": "CARAVAN_SLOT_PROTECT_MINUTES",
}

_FLOAT_KEYS = ("max_age_days", "interval_hours", "max_gb", "protect_minutes")


def _log(msg: str) -> None:
    sys.stderr.write(f"[slot-cleanup] {msg}\n")
    sys.stderr.flush()


def _config_file_path() -> Path:
    return Path(os.environ.get(
        "CARAVAN_CONFIG", str(Path.home() / ".caravan" / "config.json")
    )).expanduser()


def _load_file_settings(path: Optional[Path] = None) -> dict:
    path = path or _config_file_path()
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        _log(f"ignoring unreadable config {path}: {e}")
        return {}
    section = data.get("slot_cleanup") if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


class Settings(NamedTuple):
    mode: str
    max_age_days: float
    interval_hours: float
    archive_dir: Path
    slot_dir: Path
    state_file: Path
    mlx_dir: Optional[Path] = None     # MLX worker prompt caches (*.safetensors)
    max_count: int = 0                 # per-Mini cap, files (0 = none)
    max_gb: float = 0.0                # per-Mini cap, GB = 1e9 bytes (0 = none)
    protect_minutes: float = 30.0      # touched this recently = active, never evicted


def resolve_settings(overrides: Optional[dict] = None,
                     config_path: Optional[Path] = None) -> Settings:
    """overrides (CLI flags; None values ignored) > env > config file > defaults."""
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    file_vals = _load_file_settings(config_path)
    out = {}
    for key, default in DEFAULTS.items():
        if key in overrides:
            val = overrides[key]
        elif os.environ.get(ENV_VARS[key], "").strip():
            val = os.environ[ENV_VARS[key]].strip()
        elif key in file_vals and file_vals[key] not in (None, ""):
            val = file_vals[key]
        else:
            val = default
        out[key] = val

    mode = str(out["mode"]).strip().lower()
    if mode not in MODES:
        raise ValueError(f"slot cleanup mode must be one of {MODES}, got {out['mode']!r}")
    floats = {}
    for key in _FLOAT_KEYS:
        try:
            floats[key] = float(out[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number, got {out[key]!r}")
    if floats["max_age_days"] <= 0:
        raise ValueError("max_age_days must be > 0")
    for key in ("max_gb", "protect_minutes"):
        if floats[key] < 0:
            raise ValueError(f"{key} must be >= 0 (0 = no limit / no grace)")
    try:
        max_count = int(str(out["max_count"]).strip())
    except (TypeError, ValueError):
        raise ValueError(f"max_count must be a whole number, got {out['max_count']!r}")
    if max_count < 0:
        raise ValueError("max_count must be >= 0 (0 = no count cap)")

    return Settings(
        mode=mode,
        max_age_days=floats["max_age_days"],
        interval_hours=floats["interval_hours"],
        archive_dir=Path(str(out["archive_dir"])).expanduser(),
        slot_dir=Path(str(out["slot_dir"])).expanduser(),
        state_file=Path(str(out["state_file"])).expanduser(),
        mlx_dir=(None if str(out["mlx_dir"]).strip().lower() in ("", "off", "none")
                 else Path(str(out["mlx_dir"])).expanduser()),
        max_count=max_count,
        max_gb=floats["max_gb"],
        protect_minutes=floats["protect_minutes"],
    )


class StaleFile(NamedTuple):
    path: Path
    size: int
    mtime: float


def find_stale(slot_dir: Path, max_age_days: float,
               now: Optional[float] = None, suffix: str = ".bin") -> List[StaleFile]:
    """Regular *<suffix> files (.bin: llama.cpp slots; .safetensors: MLX
    prompt caches) directly in slot_dir whose mtime is older than
    max_age_days. Symlinks and subdirectories are never touched."""
    now = time.time() if now is None else now
    cutoff = now - max_age_days * 86400.0
    stale = []
    if not slot_dir.is_dir():
        return stale
    for p in slot_dir.iterdir():
        if p.suffix != suffix or p.is_symlink():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if not p.is_file():
            continue
        if st.st_mtime < cutoff:
            stale.append(StaleFile(p, st.st_size, st.st_mtime))
    stale.sort(key=lambda f: f.mtime)
    return stale


def list_slot_files(slot_dir: Path, suffix: str = ".bin") -> List[StaleFile]:
    """Every regular *<suffix> file directly in slot_dir (same rules as
    find_stale, no age filter), oldest first."""
    return find_stale(slot_dir, -1e9, now=0.0, suffix=suffix) if slot_dir.is_dir() else []


def plan_evictions(files: List[StaleFile], max_count: int, max_bytes: int,
                   active: Iterable[str] = (), protect_seconds: float = 0.0,
                   now: Optional[float] = None) -> tuple:
    """LRU eviction plan for the per-Mini cap.

    files: what's left after the age rule (llama.cpp + MLX together).
    Returns (evict, kept_active, over_after): evict oldest-first until
    len <= max_count and total <= max_bytes (0 = that limit is off);
    a file whose session is in `active` or was touched in the last
    protect_seconds is never picked; over_after is True when the cap
    still isn't met because everything left is active."""
    now = time.time() if now is None else now
    active = set(active)
    count, total = len(files), sum(f.size for f in files)

    def over(c, t):
        return (max_count > 0 and c > max_count) or (max_bytes > 0 and t > max_bytes)

    evict, kept_active = [], []
    for f in sorted(files, key=lambda f: (f.mtime, f.path.name)):
        if not over(count, total):
            break
        if f.path.stem in active or now - f.mtime < protect_seconds:
            kept_active.append(f)
            continue
        evict.append(f)
        count -= 1
        total -= f.size
    return evict, kept_active, over(count, total)


def state_file_active(state_file: Path) -> List[str]:
    """Fingerprints session_slots.json says are in a llama.cpp slot now
    (standalone CLI's notion of active; the proxy asks its live state)."""
    try:
        data = json.loads(state_file.read_text())
    except (OSError, ValueError):
        return []
    out = set()
    if isinstance(data, dict):
        for entry in data.get("slots") or []:
            if isinstance(entry, dict) and isinstance(entry.get("fingerprint"), str):
                out.add(entry["fingerprint"])
        if not data.get("slots") and isinstance(data.get("assignments"), dict):
            out.update(k for k in data["assignments"] if isinstance(k, str))
    return sorted(out)


class CleanupResult(NamedTuple):
    candidates: List[StaleFile]        # age rule + cap, everything planned
    removed: List[StaleFile]
    bytes_removed: int
    dropped_assignments: List[str]
    errors: List[str]
    evicted: List[StaleFile] = []      # the cap's share of candidates / removed
    over_cap_active: bool = False      # cap still exceeded, only active sessions left
    kept_total: int = 0                # bytes left after this pass (planned)
    kept_count: int = 0


def _archive_target(archive_dir: Path, name: str) -> Path:
    target = archive_dir / name
    if not target.exists():
        return target
    stem, suffix = Path(name).stem, Path(name).suffix
    return archive_dir / f"{stem}.{time.strftime('%Y%m%d-%H%M%S')}{suffix}"


def prune_state_file(state_file: Path, fingerprints: Iterable[str],
                     dry_run: bool = False) -> List[str]:
    """Drops `fingerprints` from session_slots.json (atomic tmp+rename).
    Returns the fingerprints actually present/dropped. Used by the
    standalone CLI; inside the proxy, SessionSlotAssigner.forget() does
    this on the in-memory map instead (otherwise its next save would
    write the stale entries straight back)."""
    fingerprints = set(fingerprints)
    if not fingerprints or not state_file.exists():
        return []
    try:
        data = json.loads(state_file.read_text())
    except (OSError, ValueError) as e:
        _log(f"could not read {state_file}: {e}")
        return []
    assignments = data.get("assignments") if isinstance(data, dict) else None
    if not isinstance(assignments, dict):
        return []
    dropped = sorted(fp for fp in assignments if fp in fingerprints)
    if dropped and not dry_run:
        for fp in dropped:
            del assignments[fp]
        # v2 state (2026-10-30): per-slot occupants too.
        for entry in data.get("slots") or []:
            if isinstance(entry, dict) and entry.get("fingerprint") in fingerprints:
                entry["fingerprint"] = None
        tmp = state_file.with_suffix(".cleanup.tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(state_file)
    return dropped


def cleanup(settings: Settings, dry_run: bool = False,
            gate: Optional[Callable[[], "object"]] = None,
            forget: Optional[Callable[[List[str]], List[str]]] = None,
            now: Optional[float] = None,
            drop: Optional[Callable[[List[str]], object]] = None,
            active: Optional[Callable[[], Iterable[str]]] = None) -> CleanupResult:
    """Removes/archives stale slot files per `settings`.

    gate: optional context-manager factory; held while files are actually
    removed so nothing can be mid save/restore (the proxy passes its FIFO
    gate). Each file's mtime is re-checked under the gate, so a session
    that came back to life between the scan and the removal is spared.

    forget: optional callable that drops fingerprints from the live
    session->slot map (proxy). Without it, session_slots.json is pruned
    directly on disk.

    drop: optional callable told which MLX session caches were removed
    (the proxy asks the MLX worker to forget its in-memory copy too).

    active: optional callable -> fingerprints of live sessions, never
    evicted by the cap (proxy). Without it, the slot occupants recorded
    in state_file are treated as active. Files touched within
    protect_minutes are always spared.

    dry_run: report only -- no file, directory or state change at all.
    """
    if settings.mode == "off":
        return CleanupResult([], [], 0, [], [])
    if settings.mode == "archive" and settings.archive_dir.resolve() == settings.slot_dir.resolve():
        raise ValueError("archive_dir must differ from slot_dir")

    candidates = find_stale(settings.slot_dir, settings.max_age_days, now)
    mlx_dir = getattr(settings, "mlx_dir", None)
    scan_mlx = mlx_dir is not None and mlx_dir.resolve() != settings.slot_dir.resolve()
    if scan_mlx:
        candidates += find_stale(mlx_dir, settings.max_age_days, now, suffix=".safetensors")

    # Per-Mini cap over what the age rule leaves.
    t_now = time.time() if now is None else now
    max_count = int(getattr(settings, "max_count", 0) or 0)
    max_bytes = int(float(getattr(settings, "max_gb", 0.0) or 0.0) * 1e9)
    protect_s = float(getattr(settings, "protect_minutes", 0.0) or 0.0) * 60.0

    def _active_now() -> set:
        if active is not None:
            return set(active())
        return set(state_file_active(settings.state_file))

    evicted, over_cap = [], False
    aged = {f.path for f in candidates}
    left = [f for f in list_slot_files(settings.slot_dir) if f.path not in aged]
    if scan_mlx:
        left += [f for f in list_slot_files(mlx_dir, ".safetensors") if f.path not in aged]
    if max_count > 0 or max_bytes > 0:
        evicted, _, over_cap = plan_evictions(left, max_count, max_bytes,
                                              _active_now(), protect_s, t_now)
    kept_count = len(left) - len(evicted)
    kept_total = sum(f.size for f in left) - sum(f.size for f in evicted)
    candidates = candidates + evicted
    if dry_run or not candidates:
        return CleanupResult(candidates, [], 0, [], [], evicted, over_cap, kept_total, kept_count)
    cap_paths = {f.path: f for f in evicted}

    removed, errors = [], []
    cutoff = (time.time() if now is None else now) - settings.max_age_days * 86400.0

    class _NullCtx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    removed_cap = []
    with (gate() if gate is not None else _NullCtx()):
        if settings.mode == "archive":
            settings.archive_dir.mkdir(parents=True, exist_ok=True)
        live = _active_now() if cap_paths else set()
        for f in candidates:
            try:
                st = f.path.stat()
            except FileNotFoundError:
                continue
            if f.path in cap_paths:
                # Cap eviction: spare it if it was saved again since the
                # scan or its session became active meanwhile.
                if st.st_mtime != f.mtime or f.path.stem in live \
                        or t_now - st.st_mtime < protect_s:
                    continue
            elif st.st_mtime >= cutoff:
                continue  # touched since the scan -- in use again, keep it
            try:
                if settings.mode == "delete":
                    f.path.unlink()
                elif f.path.suffix == ".safetensors":
                    (settings.archive_dir / "mlx").mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f.path), str(_archive_target(settings.archive_dir / "mlx", f.path.name)))
                else:
                    shutil.move(str(f.path), str(_archive_target(settings.archive_dir, f.path.name)))
                removed.append(StaleFile(f.path, st.st_size, st.st_mtime))
                if f.path in cap_paths:
                    removed_cap.append(removed[-1])
            except OSError as e:
                errors.append(f"{f.path.name}: {e}")

        fps = sorted({f.path.stem for f in removed})
        mlx_fps = [f.path.stem for f in removed if f.path.suffix == ".safetensors"]
        if drop is not None and mlx_fps:
            try:
                drop(mlx_fps)
            except Exception as e:  # the worker may be down; files are gone anyway
                errors.append(f"mlx drop: {e!r}")
        if forget is not None:
            dropped = forget(fps)
        else:
            try:
                dropped = prune_state_file(settings.state_file, fps)
            except OSError as e:
                errors.append(f"{settings.state_file}: {e}")
                dropped = []

    return CleanupResult(candidates, removed, sum(f.size for f in removed), dropped, errors,
                         removed_cap, over_cap, kept_total, kept_count)


def _fmt_bytes(n: int) -> str:
    return f"{n / 1e9:.2f} GB"


def _cap_desc(settings) -> str:
    c, g = int(getattr(settings, "max_count", 0) or 0), float(getattr(settings, "max_gb", 0) or 0)
    parts = ([f"{c} files"] if c > 0 else []) + ([f"{g:g} GB"] if g > 0 else [])
    return " / ".join(parts) if parts else "none"


def log_result(settings: Settings, result: CleanupResult, dry_run: bool) -> None:
    if settings.mode == "off":
        _log("disabled (mode=off)")
        return
    total = sum(f.size for f in result.candidates)
    ev = list(getattr(result, "evicted", []) or [])
    cap = _cap_desc(settings)
    if dry_run:
        _log(f"dry run: {len(result.candidates) - len(ev)} slot file(s) older than "
             f"{settings.max_age_days:g} day(s) in {settings.slot_dir}"
             + (f" + {len(ev)} over the cap ({cap}, LRU first)" if ev else "")
             + f", {_fmt_bytes(total)} would be {settings.mode}d")
        return
    verb = "deleted" if settings.mode == "delete" else f"archived to {settings.archive_dir}"
    for f in ev:
        _log(f"evicted (over cap {cap}, least recently used "
             f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(f.mtime))}): "
             f"{f.path.name} {_fmt_bytes(f.size)} {verb}")
    _log(f"{len(result.removed)} slot file(s) {verb} ({len(result.removed) - len(ev)} stale, "
         f"{len(ev)} over cap), {_fmt_bytes(result.bytes_removed)}; "
         f"dropped {len(result.dropped_assignments)} session->slot assignment(s)")
    if getattr(result, "over_cap_active", False):
        _log(f"still over cap ({cap}): {getattr(result, 'kept_count', 0)} file(s), "
             f"{_fmt_bytes(getattr(result, 'kept_total', 0))} left; the rest are active sessions")
    for e in result.errors:
        _log(f"error: {e}")


def start_background(settings: Settings,
                     gate: Optional[Callable[[], "object"]] = None,
                     forget: Optional[Callable[[List[str]], List[str]]] = None,
                     drop: Optional[Callable[[List[str]], object]] = None,
                     active: Optional[Callable[[], Iterable[str]]] = None,
                     ) -> Optional[threading.Thread]:
    """Daemon thread: one pass at startup, then every interval_hours
    (<= 0 means startup only). Never raises into the proxy."""
    if settings.mode == "off":
        _log("automatic slot cleanup disabled (mode=off)")
        return None

    def _loop():
        while True:
            try:
                log_result(settings, cleanup(settings, gate=gate, forget=forget, drop=drop,
                                                   active=active), dry_run=False)
            except Exception as e:  # never let cleanup kill the proxy
                _log(f"cleanup pass failed: {e!r}")
            if settings.interval_hours <= 0:
                return
            time.sleep(settings.interval_hours * 3600.0)

    _log(f"automatic slot cleanup: mode={settings.mode} max_age_days={settings.max_age_days:g} "
         f"interval_hours={settings.interval_hours:g} cap={_cap_desc(settings)} "
         f"slot_dir={settings.slot_dir}"
         + (f" mlx_dir={settings.mlx_dir}" if getattr(settings, "mlx_dir", None) else "")
         + (f" archive_dir={settings.archive_dir}" if settings.mode == "archive" else ""))
    t = threading.Thread(target=_loop, name="slot-cleanup", daemon=True)
    t.start()
    return t


def add_cli_args(parser: argparse.ArgumentParser, proxy: bool = False) -> None:
    """Adds the cleanup flags. Standalone CLI: --mode/--max-age-days/...;
    inside slot_pin_proxy.py they're namespaced: --slot-cleanup,
    --slot-max-age-days, --slot-archive-dir, --slot-cleanup-interval-hours."""
    names = {
        "mode": "--slot-cleanup" if proxy else "--mode",
        "age": "--slot-max-age-days" if proxy else "--max-age-days",
        "archive": "--slot-archive-dir" if proxy else "--archive-dir",
        "interval": "--slot-cleanup-interval-hours" if proxy else "--interval-hours",
        "count": "--slot-max-count" if proxy else "--max-count",
        "gb": "--slot-max-gb" if proxy else "--max-gb",
        "protect": "--slot-protect-minutes" if proxy else "--protect-minutes",
    }
    parser.add_argument(names["mode"], dest="cleanup_mode", choices=MODES, default=None,
                        help="delete | archive | off (env CARAVAN_SLOT_CLEANUP, default delete)")
    parser.add_argument(names["age"], dest="max_age_days", type=float, default=None,
                        help="slot files not written for this many days are stale "
                             "(env CARAVAN_SLOT_MAX_AGE_DAYS, default 30)")
    parser.add_argument(names["archive"], dest="archive_dir", default=None,
                        help="where archive mode moves files (env CARAVAN_SLOT_ARCHIVE_DIR, "
                             "default ~/.caravan/llama-server/slots-archive)")
    parser.add_argument(names["interval"], dest="interval_hours", type=float, default=None,
                        help="proxy: hours between automatic passes, <=0 = startup only "
                             "(env CARAVAN_SLOT_CLEANUP_INTERVAL_HOURS, default 6)")
    parser.add_argument(names["count"], dest="max_count", type=int, default=None,
                        help="per-Mini cap: keep at most this many saved chats, llama.cpp + MLX, "
                             "least recently used evicted first (env CARAVAN_SLOT_MAX_COUNT, "
                             "default 200, 0 = no count cap)")
    parser.add_argument(names["gb"], dest="max_gb", type=float, default=None,
                        help="per-Mini cap: keep at most this many GB of saved chats "
                             "(env CARAVAN_SLOT_MAX_GB, default 50, 0 = no size cap)")
    parser.add_argument(names["protect"], dest="protect_minutes", type=float, default=None,
                        help="files written this recently count as active and are never evicted "
                             "by the cap (env CARAVAN_SLOT_PROTECT_MINUTES, default 30)")
    if not proxy:
        parser.add_argument("--slot-dir", dest="slot_dir", default=None,
                            help="slot save dir (env CARAVAN_SLOT_SAVE_DIR, "
                                 "default ~/.caravan/llama-server/slots)")
        parser.add_argument("--mlx-dir", dest="mlx_dir", default=None,
                            help="also clean MLX worker prompt caches (*.safetensors) here "
                                 "(env CARAVAN_MLX_CACHE_DIR, e.g. ~/.caravan/mlx/prompt-cache)")


def overrides_from_args(args: argparse.Namespace) -> dict:
    return {
        "mode": getattr(args, "cleanup_mode", None),
        "max_age_days": getattr(args, "max_age_days", None),
        "archive_dir": getattr(args, "archive_dir", None),
        "interval_hours": getattr(args, "interval_hours", None),
        "slot_dir": getattr(args, "slot_dir", None),
        "state_file": getattr(args, "state_file", None),
        "mlx_dir": getattr(args, "mlx_dir", None),
        "max_count": getattr(args, "max_count", None),
        "max_gb": getattr(args, "max_gb", None),
        "protect_minutes": getattr(args, "protect_minutes", None),
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove or archive Caravan disk KV slot files older than N days, "
                    "then enforce the per-Mini cap (count / GB, least recently used first).")
    add_cli_args(parser)
    parser.add_argument("--state-file", dest="state_file", default=None,
                        help="session_slots.json to prune (env CARAVAN_PROXY_STATE_FILE)")
    parser.add_argument("--config", default=None, help="JSON config file (default ~/.caravan/config.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="only list what would be removed and the total size; change nothing")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every candidate file")
    args = parser.parse_args(argv)

    try:
        settings = resolve_settings(overrides_from_args(args),
                                    Path(args.config).expanduser() if args.config else None)
    except ValueError as e:
        parser.error(str(e))

    if settings.mode == "off" and not args.dry_run:
        print("slot cleanup mode is 'off' -- nothing to do (use --mode to override).")
        return 0
    if settings.mode == "off":
        # A dry run is still useful for sizing up the backlog.
        settings = settings._replace(mode="delete")

    result = cleanup(settings, dry_run=args.dry_run)
    files = result.candidates if args.dry_run else result.removed
    if args.dry_run or args.verbose:
        for f in files:
            print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(f.mtime))}  "
                  f"{f.size / 1e9:7.2f} GB  {f.path}")
    total = sum(f.size for f in files)
    if args.dry_run:
        ev = result.evicted
        print(f"DRY RUN: {len(files) - len(ev)} file(s) older than {settings.max_age_days:g} day(s) "
              f"+ {len(ev)} over the cap ({_cap_desc(settings)}, {sum(f.size for f in ev)} bytes) in "
              f"{settings.slot_dir}" + (f" + {settings.mlx_dir}" if settings.mlx_dir else "")
              + f", total {total} bytes ({_fmt_bytes(total)}) would be "
              f"{'deleted' if settings.mode == 'delete' else 'archived to ' + str(settings.archive_dir)}; "
              f"{result.kept_count} file(s), {_fmt_bytes(result.kept_total)} would be kept"
              + (" (still over the cap: the rest are active)" if result.over_cap_active else "")
              + ". Nothing was changed.")
    else:
        verb = "deleted" if settings.mode == "delete" else f"archived to {settings.archive_dir}"
        print(f"{len(result.removed)} file(s) {verb}, {_fmt_bytes(result.bytes_removed)} freed "
              f"from {settings.slot_dir}; dropped {len(result.dropped_assignments)} "
              f"session->slot assignment(s).")
        for e in result.errors:
            print(f"error: {e}", file=sys.stderr)
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
