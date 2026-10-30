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
}

ENV_VARS = {
    "mode": "CARAVAN_SLOT_CLEANUP",
    "max_age_days": "CARAVAN_SLOT_MAX_AGE_DAYS",
    "interval_hours": "CARAVAN_SLOT_CLEANUP_INTERVAL_HOURS",
    "archive_dir": "CARAVAN_SLOT_ARCHIVE_DIR",
    "slot_dir": "CARAVAN_SLOT_SAVE_DIR",
    "state_file": "CARAVAN_PROXY_STATE_FILE",
}

_FLOAT_KEYS = ("max_age_days", "interval_hours")


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

    return Settings(
        mode=mode,
        max_age_days=floats["max_age_days"],
        interval_hours=floats["interval_hours"],
        archive_dir=Path(str(out["archive_dir"])).expanduser(),
        slot_dir=Path(str(out["slot_dir"])).expanduser(),
        state_file=Path(str(out["state_file"])).expanduser(),
    )


class StaleFile(NamedTuple):
    path: Path
    size: int
    mtime: float


def find_stale(slot_dir: Path, max_age_days: float,
               now: Optional[float] = None) -> List[StaleFile]:
    """Regular *.bin files directly in slot_dir whose mtime is older than
    max_age_days. Symlinks and subdirectories are never touched."""
    now = time.time() if now is None else now
    cutoff = now - max_age_days * 86400.0
    stale = []
    if not slot_dir.is_dir():
        return stale
    for p in slot_dir.iterdir():
        if p.suffix != ".bin" or p.is_symlink():
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


class CleanupResult(NamedTuple):
    candidates: List[StaleFile]
    removed: List[StaleFile]
    bytes_removed: int
    dropped_assignments: List[str]
    errors: List[str]


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
        tmp = state_file.with_suffix(".cleanup.tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(state_file)
    return dropped


def cleanup(settings: Settings, dry_run: bool = False,
            gate: Optional[Callable[[], "object"]] = None,
            forget: Optional[Callable[[List[str]], List[str]]] = None,
            now: Optional[float] = None) -> CleanupResult:
    """Removes/archives stale slot files per `settings`.

    gate: optional context-manager factory; held while files are actually
    removed so nothing can be mid save/restore (the proxy passes its FIFO
    gate). Each file's mtime is re-checked under the gate, so a session
    that came back to life between the scan and the removal is spared.

    forget: optional callable that drops fingerprints from the live
    session->slot map (proxy). Without it, session_slots.json is pruned
    directly on disk.

    dry_run: report only -- no file, directory or state change at all.
    """
    if settings.mode == "off":
        return CleanupResult([], [], 0, [], [])
    if settings.mode == "archive" and settings.archive_dir.resolve() == settings.slot_dir.resolve():
        raise ValueError("archive_dir must differ from slot_dir")

    candidates = find_stale(settings.slot_dir, settings.max_age_days, now)
    if dry_run or not candidates:
        return CleanupResult(candidates, [], 0, [], [])

    removed, errors = [], []
    cutoff = (time.time() if now is None else now) - settings.max_age_days * 86400.0

    class _NullCtx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    with (gate() if gate is not None else _NullCtx()):
        if settings.mode == "archive":
            settings.archive_dir.mkdir(parents=True, exist_ok=True)
        for f in candidates:
            try:
                st = f.path.stat()
            except FileNotFoundError:
                continue
            if st.st_mtime >= cutoff:
                continue  # touched since the scan -- in use again, keep it
            try:
                if settings.mode == "delete":
                    f.path.unlink()
                else:
                    shutil.move(str(f.path), str(_archive_target(settings.archive_dir, f.path.name)))
                removed.append(StaleFile(f.path, st.st_size, st.st_mtime))
            except OSError as e:
                errors.append(f"{f.path.name}: {e}")

        fps = [f.path.stem for f in removed]
        if forget is not None:
            dropped = forget(fps)
        else:
            try:
                dropped = prune_state_file(settings.state_file, fps)
            except OSError as e:
                errors.append(f"{settings.state_file}: {e}")
                dropped = []

    return CleanupResult(candidates, removed, sum(f.size for f in removed), dropped, errors)


def _fmt_bytes(n: int) -> str:
    return f"{n / 1e9:.2f} GB"


def log_result(settings: Settings, result: CleanupResult, dry_run: bool) -> None:
    if settings.mode == "off":
        _log("disabled (mode=off)")
        return
    total = sum(f.size for f in result.candidates)
    if dry_run:
        _log(f"dry run: {len(result.candidates)} slot file(s) older than "
             f"{settings.max_age_days:g} day(s) in {settings.slot_dir}, "
             f"{_fmt_bytes(total)} would be {settings.mode}d")
        return
    verb = "deleted" if settings.mode == "delete" else f"archived to {settings.archive_dir}"
    _log(f"{len(result.removed)} stale slot file(s) {verb}, {_fmt_bytes(result.bytes_removed)}; "
         f"dropped {len(result.dropped_assignments)} session->slot assignment(s)")
    for e in result.errors:
        _log(f"error: {e}")


def start_background(settings: Settings,
                     gate: Optional[Callable[[], "object"]] = None,
                     forget: Optional[Callable[[List[str]], List[str]]] = None,
                     ) -> Optional[threading.Thread]:
    """Daemon thread: one pass at startup, then every interval_hours
    (<= 0 means startup only). Never raises into the proxy."""
    if settings.mode == "off":
        _log("automatic slot cleanup disabled (mode=off)")
        return None

    def _loop():
        while True:
            try:
                log_result(settings, cleanup(settings, gate=gate, forget=forget), dry_run=False)
            except Exception as e:  # never let cleanup kill the proxy
                _log(f"cleanup pass failed: {e!r}")
            if settings.interval_hours <= 0:
                return
            time.sleep(settings.interval_hours * 3600.0)

    _log(f"automatic slot cleanup: mode={settings.mode} max_age_days={settings.max_age_days:g} "
         f"interval_hours={settings.interval_hours:g} slot_dir={settings.slot_dir}"
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
    if not proxy:
        parser.add_argument("--slot-dir", dest="slot_dir", default=None,
                            help="slot save dir (env CARAVAN_SLOT_SAVE_DIR, "
                                 "default ~/.caravan/llama-server/slots)")


def overrides_from_args(args: argparse.Namespace) -> dict:
    return {
        "mode": getattr(args, "cleanup_mode", None),
        "max_age_days": getattr(args, "max_age_days", None),
        "archive_dir": getattr(args, "archive_dir", None),
        "interval_hours": getattr(args, "interval_hours", None),
        "slot_dir": getattr(args, "slot_dir", None),
        "state_file": getattr(args, "state_file", None),
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove or archive Caravan disk KV slot files older than N days.")
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
        print(f"DRY RUN: {len(files)} file(s) older than {settings.max_age_days:g} day(s) in "
              f"{settings.slot_dir}, total {total} bytes ({_fmt_bytes(total)}) would be "
              f"{'deleted' if settings.mode == 'delete' else 'archived to ' + str(settings.archive_dir)}. "
              "Nothing was changed.")
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
