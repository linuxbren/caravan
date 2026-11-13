#!/usr/bin/env python3
"""Daily update check: is a newer published pin available?

Stdlib-only. Fetches only the channel manifest (two short hashes), never
the package itself. A failed or offline check is quiet and keeps any
cached result. The model-reload preview uses the public commit comparison
when that is cheaply available, and the same path prefixes as
`caravan_update.plan_update`.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


CHANNEL_BRANCH = "caravan-v3-mlx-split"
CHANNEL_REPO = "linuxbren/caravan"
MANIFEST_URL = (
    f"https://raw.githubusercontent.com/{CHANNEL_REPO}/{CHANNEL_BRANCH}/"
    "packaging-version"
)
COMPARE_URL = (
    f"https://api.github.com/repos/{CHANNEL_REPO}/compare/{{old}}...{{new}}"
)
USER_AGENT = "Caravan-Update-Check/1"
INTERVAL_S = 24 * 60 * 60
FETCH_TIMEOUT = 10

# Same prefixes as tools/caravan_update.py WORKER_CODE_PATHS.
WORKER_CODE_PATHS = (
    "agent/",
    "runtime/",
    "requirements-mac.lock",
    "requirements-mac.txt",
)

UP_TO_DATE = "Caravan is already up to date."
NEWER_PREFIX = "A {label} update is ready."
KEEP_MODEL = "Your model stays loaded."
RELOAD_MODEL = "Caravan will reload the model."
HELPER = (
    "The 2nd Mac needs this update too. After this Mac is done, open "
    "Caravan on the 2nd Mac and click Update now, or run caravan update there."
)
NOT_LOCAL = (
    "To update, open Caravan on this Mac and click Update now, "
    "or run caravan update in Terminal."
)
SOURCE_CHECKOUT = (
    "This is a source checkout. Update it with git pull --ff-only, "
    "then rerun scripts/install.sh with the same options. No checkout changed."
)
OFFLINE = "Could not check for updates right now."
OPENING = "Updating Caravan, the page will be back in a few seconds."
FAILED = (
    "The update failed. Caravan is back on the previous version. "
    "Check your internet connection and try again."
)
DONE = "Done."
BUSY_REPLY = "Wait for the current reply, then try Update again."
BUSY_TUNE = "Wait for Auto-tune to finish, then try Update again."
BUSY_LOAD = "Wait for the model to finish loading, then try Update again."

PIN_SUBJECT = re.compile(r"^Publish .+ source pin\s*$")

_check_lock = threading.Lock()


def ui_dir(home):
    return Path(home) / ".caravan" / "web-ui"


def prefs_path(home):
    return ui_dir(home) / "update-prefs.json"


def cache_path(home):
    return ui_dir(home) / "update-check.json"


def progress_path(home):
    return ui_dir(home) / "update-progress.json"


def installed_ref(repo):
    path = Path(repo) / ".caravan-package"
    try:
        if not path.is_file():
            return None
        text = path.read_text().strip().split()[0]
        return text.lower() if text else None
    except OSError:
        return None


def is_package_install(repo):
    return bool(installed_ref(repo)) and not (Path(repo) / ".git").is_dir()


def parse_manifest(text):
    """Parse a packaging-version line: 40-char source sha, 64-char sha256."""
    if not isinstance(text, str):
        return None
    parts = text.strip().split()
    if len(parts) < 2:
        return None
    ref, sha = parts[0].lower(), parts[1].lower()
    if len(ref) != 40 or len(sha) != 64:
        return None
    if any(c not in "0123456789abcdef" for c in ref + sha):
        return None
    return {"ref": ref, "sha256": sha}


def load_json(path, default=None):
    try:
        raw = Path(path).read_text()
        data = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return default
    return data if isinstance(data, dict) else default


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def load_prefs(home):
    data = load_json(prefs_path(home), {}) or {}
    # Missing file or missing key: on by default.
    return {"check_daily": data.get("check_daily", True) is not False}


def save_prefs(home, *, check_daily):
    save_json(prefs_path(home), {"check_daily": bool(check_daily)})
    return load_prefs(home)


def load_cache(home):
    return load_json(cache_path(home), None)


def save_cache(home, data):
    save_json(cache_path(home), data)
    return data


def load_progress(home):
    return load_json(progress_path(home), None)


def save_progress(home, data):
    save_json(progress_path(home), data)
    return data


def clear_progress(home):
    path = progress_path(home)
    try:
        path.unlink()
    except OSError:
        pass


def due_for_check(cache, now=None, interval=INTERVAL_S, installed=None):
    """True when there is no fresh cache for this installed version."""
    now = time.time() if now is None else now
    if not cache or not isinstance(cache, dict):
        return True
    if cache.get("error") and not cache.get("available"):
        # A failed check should be retried, but not more than once an hour
        # so an offline Mac is not hammered.
        checked = cache.get("checked_at") or 0
        try:
            return (now - float(checked)) >= min(interval, 3600)
        except (TypeError, ValueError):
            return True
    if installed and cache.get("installed") and cache.get("installed") != installed:
        return True
    try:
        checked = float(cache.get("checked_at") or 0)
    except (TypeError, ValueError):
        return True
    return (now - checked) >= interval


def _opener(url, timeout=FETCH_TIMEOUT, opener=None):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain",
        },
    )
    open_url = opener or urllib.request.urlopen
    return open_url(req, timeout=timeout)


def fetch_published(*, opener=None, url=None, clock=time.time):
    target = url or (MANIFEST_URL + "?channel=" + str(int(clock() * 1000)))
    try:
        with _opener(target, opener=opener) as response:
            raw = response.read()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return None
    return parse_manifest(text)


def plain_date(iso, tz_name="America/Chicago"):
    """Friendly date in the user's zone, e.g. 'November 13'. No hash."""
    if not iso:
        return None
    text = str(iso).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if ZoneInfo is not None:
        try:
            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            dt = dt.astimezone(timezone.utc)
    return dt.strftime("%B ") + str(dt.day)


def is_pin_subject(subject):
    return bool(PIN_SUBJECT.match((subject or "").strip()))


def first_line(message):
    if not message:
        return ""
    return str(message).strip().splitlines()[0].strip()


def matches_worker_path(path):
    path = str(path).replace("\\", "/").lstrip("./")
    for prefix in WORKER_CODE_PATHS:
        if prefix.endswith("/"):
            if path.startswith(prefix) or path + "/" == prefix:
                return True
        elif path == prefix:
            return True
    return False


def reload_model_from_files(filenames):
    return any(matches_worker_path(name) for name in (filenames or []))


def preview_from_compare(payload):
    """Turn a GitHub compare JSON into plain change lines and a reload flag."""
    if not isinstance(payload, dict):
        return {"changes": [], "reload_model": None, "available_date": None, "current_date": None}
    changes = []
    dates = []
    for commit in payload.get("commits") or []:
        if not isinstance(commit, dict):
            continue
        info = commit.get("commit") or {}
        subject = first_line(info.get("message"))
        if not subject or is_pin_subject(subject):
            continue
        changes.append(subject)
        date = None
        for who in ("committer", "author"):
            block = info.get(who) or {}
            date = block.get("date") or date
        if date:
            dates.append(date)
    files = []
    for entry in payload.get("files") or []:
        if isinstance(entry, dict) and entry.get("filename"):
            files.append(entry["filename"])
    available_date = dates[-1] if dates else None
    return {
        "changes": changes[:8],
        "reload_model": reload_model_from_files(files) if files else None,
        "available_date": available_date,
    }


def fetch_compare(old, new, *, opener=None):
    if not old or not new or old == new:
        return None
    url = COMPARE_URL.format(old=old, new=new)
    try:
        with _opener(url, opener=opener) as response:
            raw = response.read()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        return json.loads(text)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return None


def fetch_commit_date(ref, *, opener=None):
    if not ref:
        return None
    url = f"https://api.github.com/repos/{CHANNEL_REPO}/commits/{ref}"
    try:
        with _opener(url, opener=opener) as response:
            raw = response.read()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        data = json.loads(text)
        info = (data or {}).get("commit") or {}
        for who in ("committer", "author"):
            date = ((info.get(who) or {}).get("date"))
            if date:
                return date
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return None
    return None


def _empty_result(*, installed=None, offline=False, error=None, now=None, check_daily=True):
    return {
        "installed": installed,
        "available": None,
        "available_sha256": None,
        "newer": False,
        "current_label": None,
        "available_label": None,
        "changes": [],
        "reload_model": None,
        "offline": bool(offline),
        "error": error,
        "checked_at": now,
        "check_daily": check_daily,
        "helper": False,
    }


def _labels(current_date, available_date, newer):
    current = plain_date(current_date)
    available = plain_date(available_date)
    if current and available and current == available and newer:
        return (
            "an earlier " + current + " version",
            available,
            True,
        )
    return current, available, False


def has_helper(home=None, nodes=None):
    if nodes:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            host = (node.get("host") or "").strip().lower()
            role = (node.get("role") or "").strip().lower()
            if host and host not in ("local", "localhost", "127.0.0.1"):
                return True
            if role in ("packer", "helper", "worker") and host != "local":
                if node.get("ssh") or node.get("host"):
                    return True
    if home is None:
        return False
    ui = ui_dir(home)
    for name in ("remote-worker.json", "packer-ssh.json", "pipeline-balance.json"):
        data = load_json(ui / name, None)
        if not data:
            continue
        if data.get("ssh") or data.get("packer_ssh") or data.get("host"):
            return True
    return False


def _build_result(
    *,
    installed,
    published,
    preview=None,
    current_date=None,
    now=None,
    check_daily=True,
    helper=False,
    offline=False,
    error=None,
):
    preview = preview or {}
    newer = bool(
        installed
        and published
        and published.get("ref")
        and published["ref"] != installed
    )
    available_date = preview.get("available_date")
    current_label, available_label, same_day = _labels(
        current_date, available_date, newer
    )
    if newer and available_label and same_day:
        available_label = available_label  # "November 13"; current already says "earlier"
    return {
        "installed": installed,
        "available": (published or {}).get("ref") if published else None,
        "available_sha256": (published or {}).get("sha256") if published else None,
        "newer": newer,
        "current_label": current_label,
        "available_label": available_label,
        "changes": list(preview.get("changes") or []),
        "reload_model": preview.get("reload_model"),
        "offline": bool(offline),
        "error": error,
        "checked_at": now,
        "check_daily": check_daily,
        "helper": bool(helper),
    }


def check(
    home,
    repo,
    *,
    force=False,
    opener=None,
    now=None,
    interval=INTERVAL_S,
    nodes=None,
    manifest_url=None,
):
    """Return a result dict. Never raises for network errors."""
    now = time.time() if now is None else now
    prefs = load_prefs(home)
    installed = installed_ref(repo)
    helper = has_helper(home, nodes=nodes)
    cache = load_cache(home)
    if installed and cache and not force and not due_for_check(
        cache, now=now, interval=interval, installed=installed
    ):
        out = dict(cache)
        out["check_daily"] = prefs["check_daily"]
        out["helper"] = helper
        out["offline"] = bool(out.get("offline"))
        return out
    if not installed:
        result = _empty_result(
            installed=None, now=now, check_daily=prefs["check_daily"],
            error="not-packaged",
        )
        result["helper"] = helper
        return result

    with _check_lock:
        published = fetch_published(opener=opener, url=manifest_url, clock=lambda: now)
        if not published:
            if cache and cache.get("installed") == installed:
                out = dict(cache)
                out["check_daily"] = prefs["check_daily"]
                out["helper"] = helper
                out["offline"] = True
                return out
            result = _empty_result(
                installed=installed, offline=True, error="offline",
                now=now, check_daily=prefs["check_daily"],
            )
            result["helper"] = helper
            save_cache(home, result)
            return result

        preview = {}
        current_date = None
        if published["ref"] != installed:
            payload = fetch_compare(installed, published["ref"], opener=opener)
            preview = preview_from_compare(payload) if payload else {}
            current_date = fetch_commit_date(installed, opener=opener)
            if not preview.get("available_date"):
                preview = dict(preview)
                preview["available_date"] = fetch_commit_date(
                    published["ref"], opener=opener
                )
        else:
            current_date = fetch_commit_date(installed, opener=opener)
            preview = {"changes": [], "reload_model": False, "available_date": current_date}

        result = _build_result(
            installed=installed,
            published=published,
            preview=preview,
            current_date=current_date,
            now=now,
            check_daily=prefs["check_daily"],
            helper=helper,
        )
        save_cache(home, result)
        return result


def maybe_auto_check(home, repo, *, opener=None, now=None, interval=INTERVAL_S, nodes=None):
    """Run a check only when the daily switch is on and a check is due."""
    prefs = load_prefs(home)
    if not prefs["check_daily"]:
        cache = load_cache(home)
        if cache:
            out = dict(cache)
            out["check_daily"] = False
            return out
        return None
    return check(
        home, repo, force=False, opener=opener, now=now, interval=interval, nodes=nodes,
    )


def keep_model_text(reload_model):
    if reload_model is True:
        return RELOAD_MODEL
    if reload_model is False:
        return KEEP_MODEL
    return None


def public_status(
    result,
    *,
    local=False,
    busy=None,
    progress=None,
    packaged=True,
    check_daily=True,
):
    """JSON-safe payload for GET /api/update. No hashes up front."""
    result = result or {}
    newer = bool(result.get("newer"))
    progress = progress or None
    phase = (progress or {}).get("phase") if progress else None
    message = None
    current_label = result.get("current_label")
    available_label = result.get("available_label")
    if not packaged:
        message = SOURCE_CHECKOUT
        newer = False
    elif phase == "updating":
        message = (progress or {}).get("message") or OPENING
    elif phase == "failed":
        message = (progress or {}).get("message") or FAILED
    elif phase == "done":
        if (progress or {}).get("message"):
            message = progress["message"]
        elif current_label:
            message = f"Done. This Mac is on the {current_label} version."
        else:
            message = "Done. This Mac is on the new version."
    elif newer:
        if available_label:
            message = NEWER_PREFIX.format(label=available_label)
        else:
            message = "A newer version is ready."
    elif result.get("offline") and not result.get("available"):
        message = None  # automatic checks stay quiet
    elif current_label:
        message = f"This Mac is on the {current_label} version."
    elif result.get("installed"):
        message = "This Mac is on the version that's installed."
        if not newer:
            # After a successful check with no date and no newer pin.
            if result.get("checked_at") and not result.get("error"):
                message = UP_TO_DATE
    can_apply = bool(packaged and newer and local and not busy and phase != "updating")
    payload = {
        "packaged": bool(packaged),
        "check_daily": bool(check_daily if result.get("check_daily") is None else result.get("check_daily")),
        "newer": newer,
        "current_label": current_label,
        "available_label": available_label,
        "changes": list(result.get("changes") or []),
        "reload_model": result.get("reload_model"),
        "keep_model_text": keep_model_text(result.get("reload_model")),
        "helper": bool(result.get("helper")),
        "helper_text": HELPER if result.get("helper") and newer else None,
        "local": bool(local),
        "can_apply": can_apply,
        "busy": busy,
        "offline": bool(result.get("offline")),
        "message": message,
        "not_local_text": None if local else NOT_LOCAL,
        "progress": progress,
        "checked_at": result.get("checked_at"),
    }
    return payload


def _loopback_ip(ip):
    ip = (ip or "").strip().lower().lstrip("[").rstrip("]")
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    if ip.startswith("::ffff:") and ip.rsplit(":", 1)[-1] == "127.0.0.1":
        return True
    return False


def _loopback_host(host):
    host = (host or "").strip().lower()
    if not host:
        return False
    # Strip a port. IPv6 in brackets: [::1]:8190
    if host.startswith("["):
        end = host.find("]")
        host = host[1:end] if end > 0 else host
    elif host.count(":") == 1:
        host = host.split(":")[0]
    return _loopback_ip(host) or host == "localhost"


_FORWARDED = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "x-forwarded-server")


def is_local_owner(handler):
    """True only when the browser is on this Mac itself, not LAN or Tailscale.

    Tailscale serve proxies to loopback, so the client address can be
    127.0.0.1 while Host is the Tailscale name. Require both a loopback
    client and a loopback Host, and refuse forwarded requests.
    There is no login on LAN or Tailscale, so Update stays on this Mac.
    """
    try:
        addr = handler.client_address[0]
    except (AttributeError, IndexError, TypeError):
        return False
    if not _loopback_ip(addr):
        return False
    try:
        headers = handler.headers
    except AttributeError:
        return False
    host = headers.get("Host") or headers.get("host") or ""
    if not _loopback_host(host):
        return False
    for name in _FORWARDED:
        value = headers.get(name) or headers.get(name.title())
        if value and str(value).strip():
            return False
    return True


def busy_reason(app):
    """('reply'|'tune'|'load', message) or (None, None)."""
    if app is None:
        return None, None
    try:
        if int(getattr(app, "_inflight", 0) or 0) > 0:
            return "reply", BUSY_REPLY
    except (TypeError, ValueError):
        pass
    for name in ("optimizer", "gguf_optimizer", "mlx_optimizer"):
        opt = getattr(app, name, None)
        if opt is None:
            continue
        try:
            snap = opt.snapshot() or {}
        except Exception:
            snap = {}
        if snap.get("running"):
            return "tune", BUSY_TUNE
    try:
        snap = app.mgr.snapshot() or {}
    except Exception:
        snap = {}
    status = snap.get("status") or ""
    if status in ("starting_lead", "starting_packer", "stopping"):
        return "load", BUSY_LOAD
    return None, None


def resolve_progress(home, repo, progress=None):
    """Promote a leftover 'updating' file after the page comes back."""
    progress = progress if progress is not None else load_progress(home)
    if not progress or progress.get("phase") != "updating":
        return progress
    expected = (progress.get("expected") or "").strip().lower()
    current = installed_ref(repo) or ""
    if expected and current == expected:
        done = dict(progress)
        done["phase"] = "done"
        done["finished_at"] = time.time()
        if not done.get("message"):
            done["message"] = DONE
        save_progress(home, done)
        return done
    old = (progress.get("old") or "").strip().lower()
    started = float(progress.get("started_at") or 0)
    # If the previous version is still installed a few minutes later and
    # no installer is running, treat it as a failed update.
    lock = Path(home) / ".caravan" / "install.lock"
    if old and current == old and started and (time.time() - started) > 180 and not lock.exists():
        failed = dict(progress)
        failed["phase"] = "failed"
        failed["finished_at"] = time.time()
        failed["message"] = FAILED
        save_progress(home, failed)
        return failed
    return progress


def start_apply(home, repo, *, name="web", python=None, runner=None, now=None, expected=None):
    """Start the same update path as `caravan update`, in a detached process."""
    now = time.time() if now is None else now
    installed = installed_ref(repo)
    progress = {
        "phase": "updating",
        "message": OPENING,
        "started_at": now,
        "old": installed,
        "expected": expected,
        "finished_at": None,
    }
    save_progress(home, progress)
    python = python or sys.executable
    script = Path(__file__).resolve()
    cmd = [
        str(python),
        str(script),
        "apply-job",
        "--home",
        str(home),
        "--repo",
        str(repo),
        "--name",
        str(name),
    ]
    if runner is not None:
        runner(cmd)
        return progress
    log_dir = Path(home) / ".caravan" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "update-ui.log", "ab")  # noqa: SIM115 — kept for the child's life
    try:
        import subprocess
        subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(repo),
            env={**os.environ, "HOME": str(home)},
        )
    except Exception:
        log.close()
        failed = dict(progress)
        failed["phase"] = "failed"
        failed["message"] = FAILED
        failed["finished_at"] = time.time()
        save_progress(home, failed)
        raise
    return progress


def _run_cli_update(repo, *, name="web"):
    """Same path as `caravan update`: fetch the install script and run it."""
    tools = str(Path(repo) / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import caravan as cli
    # Point the CLI at this package so it does not refuse a test checkout.
    previous = getattr(cli, "ROOT", None)
    try:
        cli.ROOT = Path(repo)
        return int(cli.main(["update", "--name", str(name)]) or 0)
    finally:
        if previous is not None:
            cli.ROOT = previous


def apply_job(home, repo, *, name="web"):
    """Foreground job for the detached process. Writes done or failed."""
    progress = load_progress(home) or {}
    progress["phase"] = "updating"
    progress["message"] = OPENING
    save_progress(home, progress)
    try:
        code = _run_cli_update(repo, name=name)
    except Exception as error:
        failed = dict(progress)
        failed["phase"] = "failed"
        failed["message"] = FAILED
        failed["error"] = str(error)[:300]
        failed["finished_at"] = time.time()
        save_progress(home, failed)
        return 1
    current = installed_ref(repo)
    expected = (progress.get("expected") or "").strip().lower()
    final = dict(progress)
    final["finished_at"] = time.time()
    if code == 0:
        final["phase"] = "done"
        if expected and current and current != expected and current == (progress.get("old") or ""):
            # Already up to date: the installed ref did not change.
            final["message"] = UP_TO_DATE
        else:
            final["message"] = DONE
            final["new"] = current
        save_progress(home, final)
        return 0
    final["phase"] = "failed"
    final["message"] = FAILED
    save_progress(home, final)
    return code or 1


def cli_check(repo, *, home=None, name="web", opener=None, file=None):
    """`caravan update --check`. Returns 0 up to date, 1 newer, 2 error."""
    file = sys.stdout if file is None else file
    home = Path(home) if home is not None else Path.home()
    repo = Path(repo)
    if not (repo / ".caravan-package").exists():
        print(SOURCE_CHECKOUT, file=file)
        return 2
    result = check(home, repo, force=True, opener=opener)
    if result.get("error") == "offline" and not result.get("available") and not result.get("newer"):
        print(OFFLINE, file=file)
        return 2
    if result.get("newer"):
        label = result.get("available_label") or "newer"
        print(NEWER_PREFIX.format(label=label), file=file)
        keep = keep_model_text(result.get("reload_model"))
        if keep:
            print(keep, file=file)
        changes = result.get("changes") or []
        if changes:
            print("What's new:", file=file)
            for line in changes:
                print("  " + line, file=file)
        if result.get("helper"):
            print(HELPER, file=file)
        print("Run caravan update to install it.", file=file)
        return 1
    print(UP_TO_DATE, file=file)
    return 0


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("--home")
    c.add_argument("--repo", required=True)
    c.add_argument("--force", action="store_true")
    a = sub.add_parser("apply-job")
    a.add_argument("--home", required=True)
    a.add_argument("--repo", required=True)
    a.add_argument("--name", default="web")
    args = parser.parse_args(argv)
    if args.command == "check":
        return cli_check(args.repo, home=args.home)
    if args.command == "apply-job":
        return apply_job(args.home, args.repo, name=args.name)
    return 2


if __name__ == "__main__":
    sys.exit(main())
