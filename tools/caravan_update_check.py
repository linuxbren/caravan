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
    "Caravan will also update the other Macs it knows about. "
    "If one is off, this Mac still updates, and that Mac is listed in Settings."
)
NOT_LOCAL = (
    "To update, open Caravan on this Mac or from a device on your Tailscale "
    "network, and click Update now. On the local network, run caravan update "
    "in Terminal on this Mac."
)
NOT_LAN = NOT_LOCAL
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


def _with_peers(result, home, *, nodes=None, ssh_runner=None, published_ref=None):
    """Attach per-Mac rows (2nd, 3rd, …) without putting hashes in the public payload."""
    try:
        import caravan_update_peers as P
        peers = P.discover_peers(home, nodes) if nodes is not None else P.load_nodes(home)
    except Exception:
        peers = []
    result = dict(result or {})
    result["helper"] = bool(peers) or bool(result.get("helper"))
    if not peers:
        result["macs"] = result.get("macs") or []
        result["peers_behind"] = False
        return result
    want = published_ref or result.get("available") or result.get("installed")
    try:
        rows = P.check_peers(peers, want, runner=ssh_runner)
    except Exception:
        rows = []
    result["macs"] = rows
    result["peers_behind"] = any(r.get("behind") for r in rows)
    return result


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
    ssh_runner=None,
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
        result = _with_peers(
            result, home, nodes=nodes, ssh_runner=ssh_runner,
            published_ref=(published or {}).get("ref"),
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


def local_status_row(result, *, newer, peers=0):
    """This Mac's line, in the same format as the other Macs."""
    label = "1st Mac" if peers else "My Mac"
    if newer:
        status = "update available"
    elif result.get("available") or (result.get("checked_at") and not result.get("error")):
        status = "current"
    else:
        return None
    return {
        "id": "local", "label": label, "mine": True, "phase": "current" if not newer else "behind",
        "kind": None, "status": status, "message": f"{label}: {status}.",
        "help": [], "can_retry": False,
    }


def public_status(
    result,
    *,
    local=False,
    via_tailscale=False,
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
    # Otherwise no summary line: each Mac gets its own status line below.
    macs = []
    peer_rows = []
    # A finished run's rows are shown only while they are about the
    # version that is still the newest one; a newer check replaces them.
    expected = ((progress or {}).get("expected") or "").strip().lower()
    use_progress = bool(progress and progress.get("macs") and (
        phase == "updating"
        or (expected and expected == str(result.get("available") or "").strip().lower())
    ))
    if use_progress:
        macs = []
        for m in progress["macs"]:
            m = dict(m)
            if m.get("mine") and m.get("phase") in ("done", "no_model"):
                m["status"] = "current"
            macs.append(m)
        peer_rows = [m for m in macs if not m.get("mine")]
    else:
        peer_rows = [m for m in (result.get("macs") or []) if not m.get("mine")]
        mine = local_status_row(result, newer=newer, peers=len(peer_rows)) if packaged else None
        macs = ([mine] if mine else []) + peer_rows
    peers_behind = bool(result.get("peers_behind") or any(m.get("behind") for m in peer_rows))
    via_tailscale = bool(via_tailscale)
    allowed = bool(local or via_tailscale)
    needs = bool(newer or peers_behind)
    can_apply = bool(packaged and needs and allowed and not busy and phase != "updating")
    any_updating = phase == "updating" or any(m.get("phase") == "updating" for m in macs)
    step = None
    if any_updating and progress:
        now = time.time()
        raw = progress.get("step") or {}
        try:
            started = float(progress.get("started_at") or raw.get("since") or now)
        except (TypeError, ValueError):
            started = now
        try:
            since = float(raw.get("since") or started)
        except (TypeError, ValueError):
            since = started
        step = {
            "text": raw.get("text") or "Updating…",
            "elapsed_s": max(0, int(now - since)),
            "total_s": max(0, int(now - started)),
        }
    can_retry = bool(allowed and not busy and not any_updating and any(m.get("can_retry") for m in macs))
    payload = {
        "packaged": bool(packaged),
        "check_daily": bool(check_daily if result.get("check_daily") is None else result.get("check_daily")),
        "newer": newer,
        "current_label": current_label,
        "available_label": available_label,
        "changes": list(result.get("changes") or []),
        "reload_model": result.get("reload_model"),
        "keep_model_text": keep_model_text(result.get("reload_model")),
        "helper": bool(result.get("helper") or peer_rows),
        "helper_text": HELPER if (result.get("helper") or peer_rows) and needs else None,
        "local": bool(local),
        "via_tailscale": via_tailscale,
        "can_apply": can_apply,
        "busy": busy,
        "offline": bool(result.get("offline")),
        "message": message,
        "not_local_text": None if allowed else NOT_LOCAL,
        "progress": progress,
        "checked_at": result.get("checked_at"),
        "macs": macs,
        "peers_behind": peers_behind,
        "show": allowed,
        "can_retry": can_retry,
        "updating": bool(any_updating),
        "step": step,
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


def _tailnet_ipv4(ip):
    """Tailscale uses CGNAT 100.64.0.0/10 for tailnet IPv4."""
    parts = (ip or "").strip().split(".")
    if len(parts) != 4:
        return False
    try:
        a, b, c, d = (int(x) for x in parts)
    except ValueError:
        return False
    return a == 100 and 64 <= b <= 127 and 0 <= c <= 255 and 0 <= d <= 255


def _tailnet_ipv6(ip):
    ip = (ip or "").strip().lower().lstrip("[").rstrip("]")
    return ip.startswith("fd7a:115c:a1e0:")


def _host_key(host):
    host = (host or "").strip().lower()
    if not host:
        return ""
    if host.startswith("["):
        end = host.find("]")
        inner = host[1:end] if end > 0 else host
        return inner
    if host.count(":") == 1:
        # hostname:port (not IPv6)
        host = host.split(":")[0]
    return host


def _addr_host(addr):
    """Host part of an http://host:port Tailscale address."""
    text = (addr or "").strip().lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0]
    return _host_key(text)


def known_tailscale_hosts(info):
    """Hosts from this Mac's live Tailscale share, not a guess from the name."""
    hosts = set()
    if not isinstance(info, dict):
        return hosts
    for addr in info.get("addresses") or []:
        host = _addr_host(addr)
        if host:
            hosts.add(host)
    for key in ("ips", "TailscaleIPs", "ip"):
        raw = info.get(key)
        if isinstance(raw, str):
            raw = [raw]
        for item in raw or []:
            host = _host_key(str(item))
            if host:
                hosts.add(host)
    return hosts


def is_tailscale_owner(handler, *, inspect_info=None):
    """True when the request arrived through this Mac's Tailscale share.

    The share is a TCP forward to loopback, so Tailscale identity headers
    (Tailscale-User-Login) are usually absent. A spoofable Host name is
    not enough: Host must match a live address from Tailscale itself,
    the share must be on, and the client must be the serve forward
    (loopback) or a tailnet address. A local-network client cannot
    present a loopback or tailnet client address.

    If Tailscale-User-Login is present (HTTPS serve), it is extra
    identity and is only accepted together with the same Host and
    share checks.
    """
    if not inspect_info or not inspect_info.get("enabled") or inspect_info.get("funnel"):
        return False
    known = known_tailscale_hosts(inspect_info)
    if not known:
        return False
    try:
        addr = handler.client_address[0]
    except (AttributeError, IndexError, TypeError):
        return False
    try:
        headers = handler.headers
    except AttributeError:
        return False
    host = _host_key(headers.get("Host") or headers.get("host") or "")
    if not host or host not in known:
        return False
    login = (
        headers.get("Tailscale-User-Login")
        or headers.get("tailscale-user-login")
        or ""
    ).strip()
    client_ok = _loopback_ip(addr) or _tailnet_ipv4(addr) or _tailnet_ipv6(addr)
    if not client_ok:
        return False
    # Identity header, when present, is extra confirmation. Its absence
    # is normal for TCP serve and is not a rejection.
    return True


def can_apply_from(handler, *, inspect_info=None):
    """Local on this Mac, or a verified Tailscale share. Never plain LAN."""
    if is_local_owner(handler):
        return True, "local"
    if is_tailscale_owner(handler, inspect_info=inspect_info):
        return True, "tailscale"
    return False, None


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


def _run_cli_update(repo, *, name="web", local_only=True):
    """Same path as `caravan update`: fetch the install script and run it."""
    tools = str(Path(repo) / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import caravan as cli
    # Point the CLI at this package so it does not refuse a test checkout.
    previous = getattr(cli, "ROOT", None)
    try:
        cli.ROOT = Path(repo)
        argv = ["update", "--name", str(name)]
        if local_only:
            argv.append("--local-only")
        return int(cli.main(argv) or 0)
    finally:
        if previous is not None:
            cli.ROOT = previous


def apply_job(home, repo, *, name="web", peers=None, runner=None, status_fn=None):
    """Foreground job: update every other Mac first, then this Mac.

    Other Macs are asked over the existing SSH link, with
    CARAVAN_UPDATE_LOCAL so they do not try to update anyone else.
    A Mac that is off or that fails is recorded with plain help; this
    Mac still updates. The local step uses --local-only so we do not
    fan out twice.
    """
    import caravan_update_peers as P
    progress = load_progress(home) or {}
    expected = (progress.get("expected") or "").strip().lower() or None
    if peers is None:
        try:
            peers = P.load_nodes(home)
        except Exception:
            peers = []
    local_label = P.coordinator_label(len(peers or []))
    macs = P.initial_progress(peers, local_phase="waiting", local_label=local_label)
    progress["phase"] = "updating"
    progress["message"] = (
        "Updating the other Macs first, then this Mac." if peers else OPENING
    )
    progress["macs"] = macs
    save_progress(home, progress)

    def persist():
        progress["macs"] = macs
        save_progress(home, progress)

    def set_step(text):
        progress["step"] = {"text": text, "since": time.time()}

    def set_local(phase, message=None, kind=None):
        nonlocal macs
        row = P.local_row(phase=phase, label=local_label, message=message, kind=kind)
        macs = P.replace_mac(macs, "local", row)
        if message:
            progress["message"] = message
        if phase == "updating":
            set_step(f"Updating the {local_label}…")
        persist()

    def on_progress(row):
        nonlocal macs
        macs = P.replace_mac(macs, row.get("id"), row)
        if row.get("phase") == "updating":
            set_step(f"Updating the {row.get('label') or 'Mac'}…")
        persist()

    if peers:
        P.update_other_macs(
            home, peers, expected=expected, runner=runner, on_progress=on_progress,
            out=sys.stdout,
        )

    set_local("updating", OPENING)
    try:
        code = _run_cli_update(repo, name=name, local_only=True)
    except Exception as error:
        set_local("failed", FAILED)
        progress["phase"] = "failed"
        progress["message"] = FAILED
        progress["error"] = str(error)[:300]
        progress["finished_at"] = time.time()
        persist()
        return 1
    current = installed_ref(repo)
    expected_ref = expected
    final_msg = DONE
    local_phase = "done"
    if code == 0:
        if expected_ref and current and current != expected_ref and current == (progress.get("old") or ""):
            final_msg = UP_TO_DATE
        else:
            final_msg = DONE
            progress["new"] = current
        try:
            if P.model_did_not_return(home, status_fn=status_fn):
                # If a peer already has failure help, still note the model.
                peer_trouble = any(
                    (not m.get("mine")) and m.get("phase") in
                    ("offline", "failed", "still_old") for m in macs
                )
                if not peer_trouble:
                    final_msg = "The Macs updated, but the model didn't come back."
                    set_local("no_model", final_msg, kind="no_model")
                    local_phase = "no_model"
        except Exception:
            pass
        peer_trouble = any(
            (not m.get("mine")) and m.get("phase") in
            ("offline", "failed", "still_old", "no_model") for m in macs
        )
        if peer_trouble and local_phase != "no_model":
            final_msg = "This Mac is updated. Some Macs failed."
        set_local(local_phase, final_msg, kind=("no_model" if local_phase == "no_model" else None))
        # Local no_model still means the update itself finished; page should show Done-ish help.
        progress["phase"] = "done"
        progress["message"] = final_msg
        progress["finished_at"] = time.time()
        persist()
        return 0
    set_local("failed", FAILED)
    progress["phase"] = "failed"
    progress["message"] = FAILED
    progress["finished_at"] = time.time()
    persist()
    return code or 1


def retry_peer(home, mac_id, *, expected=None, peers=None, runner=None, timeout=None):
    """Try one Mac again. Used by the Try again button. Never updates this Mac."""
    import caravan_update_peers as P
    if peers is None:
        try:
            peers = P.load_nodes(home)
        except Exception:
            peers = []
    node = next((n for n in peers if str(n.get("id")) == str(mac_id)), None)
    if node is None:
        return None
    progress = load_progress(home) or {}
    macs = list(progress.get("macs") or [])
    updating = P._row(node, phase="updating", can_retry=False)
    macs = P.replace_mac(macs, node.get("id"), updating)
    progress["macs"] = macs
    progress["phase"] = progress.get("phase") or "updating"
    save_progress(home, progress)
    kw = {}
    if timeout is not None:
        kw["timeout"] = timeout
    expected = expected or (progress.get("expected") or None)
    progress["step"] = {"text": f"Updating the {node.get('label') or 'Mac'}…", "since": time.time()}
    save_progress(home, progress)
    row = P.update_peer(node, expected=expected, runner=runner, **kw)
    P.record_peer_result(home, row)
    print(f"Try again on the {row.get('label')}: {row.get('status')}. {row.get('detail') or ''}".strip(), flush=True)
    progress = load_progress(home) or progress
    macs = P.replace_mac(list(progress.get("macs") or []), node.get("id"), row)
    progress["macs"] = macs
    if not any(m.get("phase") == "updating" for m in macs):
        progress.pop("step", None)
    save_progress(home, progress)
    return row


def failed_mac_ids(home):
    progress = load_progress(home) or {}
    return [m.get("id") for m in progress.get("macs") or []
            if not m.get("mine") and m.get("can_retry") and m.get("id")]


def mark_retrying(home, mac_ids, *, peers=None):
    """Show 'updating…' right away for the Macs being tried again."""
    import caravan_update_peers as P
    if peers is None:
        try:
            peers = P.load_nodes(home)
        except Exception:
            peers = []
    progress = load_progress(home) or {}
    macs = list(progress.get("macs") or [])
    found = []
    for node in peers:
        if str(node.get("id")) in {str(i) for i in mac_ids}:
            macs = P.replace_mac(macs, node.get("id"), P._row(node, phase="updating", can_retry=False))
            found.append(node.get("id"))
            if len(found) == 1:
                progress["step"] = {"text": f"Updating the {node.get('label') or 'Mac'}…", "since": time.time()}
    progress["macs"] = macs
    save_progress(home, progress)
    return found


def cli_check(repo, *, home=None, name="web", opener=None, file=None, nodes=None, ssh_runner=None):
    """`caravan update --check`. Returns 0 up to date, 1 newer, 2 error."""
    file = sys.stdout if file is None else file
    home = Path(home) if home is not None else Path.home()
    repo = Path(repo)
    if not (repo / ".caravan-package").exists():
        print(SOURCE_CHECKOUT, file=file)
        return 2
    result = check(home, repo, force=True, opener=opener, nodes=nodes, ssh_runner=ssh_runner)
    if result.get("error") == "offline" and not result.get("available") and not result.get("newer"):
        print(OFFLINE, file=file)
        return 2
    behind = [m for m in (result.get("macs") or []) if m.get("behind")]
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
        if result.get("helper") or behind:
            print(HELPER, file=file)
        for m in (result.get("macs") or []):
            if m.get("behind") or m.get("phase") == "offline":
                print(m["message"], file=file)
        print("Run caravan update to install it. Other Macs are updated first.", file=file)
        return 1
    if behind:
        for m in (result.get("macs") or []):
            print(m["message"], file=file)
            for step in m.get("help") or []:
                print("  " + step, file=file)
        print("Run caravan update to update the other Macs.", file=file)
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
