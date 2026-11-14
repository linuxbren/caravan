#!/usr/bin/env python3
"""Tell every other Caravan Mac in the group to update, over the existing SSH link.

The 1st Mac is the coordinator. It asks each Mac it already knows about
(2nd, 3rd, 4th, …) to run the same update, using the SSH identity already
set up when that Mac was added. There is no new unauthenticated address.
A Mac that is off or that fails is listed plainly; the others, and this
Mac, still update. Designed for any number of Macs, not only two.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

# Short connect; the update itself may take several minutes (download + swap).
CONNECT_TIMEOUT = 10
UPDATE_TIMEOUT = 600
CHECK_TIMEOUT = 20

DEFAULT_REPO = "~/.caravan/src/caravan"
DEFAULT_COMMAND = "~/.caravan/bin/caravan"


def ordinal_mac(index):
    """1st Mac, 2nd Mac, 3rd Mac, … — never a hostname."""
    n = int(index) + 1
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf} Mac"


def is_local_node(node):
    if not isinstance(node, dict):
        return True
    host = (node.get("host") or "").strip().lower()
    ssh = (node.get("ssh") or node.get("packer_ssh") or "").strip().lower()
    if host in ("local", "localhost", "127.0.0.1", "::1", ""):
        if not ssh or ssh in ("local", "localhost", "127.0.0.1", "::1"):
            return True
        # A remote node should not be tagged host=local.
        if host in ("local", "localhost", "127.0.0.1", "::1", ""):
            return host != "" or not ssh
    return host in ("local", "localhost", "127.0.0.1", "::1")


def _ssh_target(node):
    if not isinstance(node, dict):
        return ""
    return (node.get("ssh") or node.get("packer_ssh") or node.get("host") or "").strip()


def friendly_label(node, index, *, total=None):
    """Prefer an already-friendly Mac name; otherwise 2nd Mac, 3rd Mac, …"""
    raw = (node.get("label") or "").strip()
    if raw == "My Mac":
        return raw
    if raw.endswith(" Mac") and raw[0].isdigit():
        return raw
    return ordinal_mac(index)


def discover_peers(home=None, nodes=None):
    """Unique non-local Macs this coordinator already knows about.

    Sources: the nodes list (config / the running page), then a few
    saved connection files. Deduped by SSH target. Order is kept.
    """
    home = Path(home) if home is not None else Path.home()
    collected = []
    if nodes:
        collected.extend(n for n in nodes if isinstance(n, dict))
    ui = home / ".caravan" / "web-ui"
    for name, ssh_key in (
        ("remote-worker.json", "ssh"),
        ("packer-ssh.json", "packer_ssh"),
        ("pipeline-balance.json", "ssh"),
    ):
        path = ui / name
        try:
            import json
            data = json.loads(path.read_text())
        except (OSError, ValueError, TypeError):
            data = None
        if isinstance(data, dict) and (data.get(ssh_key) or data.get("ssh") or data.get("host")):
            collected.append({
                "id": data.get("id") or name,
                "label": data.get("label") or "",
                "role": data.get("role") or "packer",
                "host": data.get("host") or "",
                "ssh": data.get(ssh_key) or data.get("ssh") or data.get("host"),
                "repo": data.get("repo") or DEFAULT_REPO,
                "ssh_config": data.get("ssh_config") or "",
            })
    seen = set()
    peers = []
    for node in collected:
        if is_local_node(node):
            continue
        target = _ssh_target(node)
        if not target or target.lower() in ("local", "localhost", "127.0.0.1", "::1"):
            continue
        key = target.lower()
        if key in seen:
            continue
        seen.add(key)
        # Peers start at 2nd Mac: the 1st Mac is the coordinator, not in this list.
        index = len(peers) + 1
        label = ordinal_mac(index)
        peers.append({
            "id": str(node.get("id") or target),
            "label": label,
            "role": (node.get("role") or "packer"),
            "host": node.get("host") or "",
            "ssh": target,
            "repo": (node.get("repo") or DEFAULT_REPO).rstrip("/"),
            "ssh_config": node.get("ssh_config") or "",
            "python": node.get("python") or "",
            "index": index,
        })
    return peers


def load_nodes(home, repo=None):
    """Configured nodes from this Mac's settings, if they can be read."""
    home = Path(home)
    cfg = home / ".caravan" / "config.toml"
    nodes = []
    if cfg.is_file():
        try:
            proxy = str(Path(__file__).resolve().parents[1] / "proxy")
            if proxy not in sys.path:
                sys.path.insert(0, proxy)
            import web_nodes
            nodes = web_nodes.nodes_from_config({"path": str(cfg)}) or []
        except Exception:
            nodes = []
    return discover_peers(home, nodes)


def ssh_argv(node, command):
    target = _ssh_target(node)
    argv = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={CONNECT_TIMEOUT}",
        "-o", "StrictHostKeyChecking=yes",
    ]
    config = (node.get("ssh_config") or "").strip()
    if config:
        argv += ["-F", config]
    argv += [target, command]
    return argv


def ssh_run(node, command, *, runner=None, timeout=CHECK_TIMEOUT):
    """Run one command on a paired Mac. None if unreachable."""
    runner = runner or subprocess.run
    argv = ssh_argv(node, command)
    try:
        return runner(
            argv, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None


def _safe_repo(repo):
    repo = (repo or DEFAULT_REPO).strip() or DEFAULT_REPO
    if any(c in repo for c in("\n", "\r", "\x00", ";")):
        return DEFAULT_REPO
    return repo.rstrip("/")


def read_peer_ref(node, *, runner=None):
    repo = _safe_repo(node.get("repo"))
    command = "cat " + shlex.quote(repo + "/.caravan-package") + " 2>/dev/null"
    result = ssh_run(node, command, runner=runner, timeout=CHECK_TIMEOUT)
    if not result or result.returncode != 0:
        return None
    text = (result.stdout or "").strip().split()
    if not text:
        return None
    ref = text[0].lower()
    if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref):
        return ref
    return None


def peer_update_command():
    """Run the same update on that Mac, without asking it to fan out.

    CARAVAN_UPDATE_LOCAL is honored by this version and ignored by older
    ones, so a Mac that is not yet on this pin can still be updated.
    """
    # The variable is set with env inside the if: "VAR=1 if …" is a
    # parse error in zsh and bash (macOS login shells are zsh).
    return (
        "if [ -x \"$HOME/.caravan/bin/caravan\" ]; then "
        "env CARAVAN_UPDATE_LOCAL=1 \"$HOME/.caravan/bin/caravan\" update; "
        "else echo 'Caravan is not installed in ~/.caravan on this Mac.' >&2; exit 127; fi"
    )


def failure_help(kind, label):
    """Plain step-by-step help under a Mac's status. No hostnames, no jargon."""
    label = label or "Mac"
    if kind == "offline":
        return [
            f"Check that the {label} is on and awake.",
            "Check that it's on the same network as this Mac, or on Tailscale if you use that to reach it.",
            f"Then click Try again, or on the {label} open Terminal and run: caravan update",
            "After that Mac is updated, load your model again if it isn't already.",
        ]
    if kind == "failed":
        return [
            f"The update on the {label} didn't finish. That Mac should still be on the previous version.",
            f"Check that the {label} is on and awake, and that it's on the same network or on Tailscale.",
            f"Click Try again, or on the {label} open Terminal and run: caravan update",
            "After that Mac is updated, load your model again if it isn't already.",
        ]
    if kind == "still_old":
        return [
            f"The {label} is still on the previous version.",
            f"Check that the {label} is on and awake, and that it's on the same network or on Tailscale.",
            f"Click Try again, or on the {label} open Terminal and run: caravan update",
            "After that Mac is updated, load your model again if it isn't already.",
        ]
    if kind == "no_model":
        return [
            f"The {label} updated, but the model didn't come back.",
            "On this Mac, open Models and load your model again.",
            f"If that doesn't work, on the {label} open Terminal and run: caravan update, then load the model again here.",
        ]
    return []


STATUS_WORDS = {
    "done": "current",
    "current": "current",
    "updating": "updating…",
    "waiting": "update needed",
    "behind": "update needed",
    "offline": "failed",
    "failed": "failed",
    "still_old": "failed",
    "no_model": "failed",
}


def short_help(kind, label):
    """At most one short line under a Mac that failed."""
    if kind == "no_model":
        return [f"Load your model again in Models."]
    if kind in ("offline", "failed", "still_old"):
        return [f"On the {label}, run caravan update in Terminal."]
    return []


def _detail_text(result, node):
    """Last few lines of what the other Mac printed, without its address."""
    if result is None:
        return ""
    text = "\n".join(
        s for s in ((getattr(result, "stderr", "") or ""), (getattr(result, "stdout", "") or "")) if s
    )
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tail = " ".join(lines[-3:])[-300:]
    label = node.get("label") or "Mac"
    for secret in {_ssh_target(node), (node.get("host") or "").strip()}:
        if secret:
            tail = tail.replace(secret, label)
    code = getattr(result, "returncode", None)
    if code not in (None, 0):
        tail = (f"exit {code}: " + tail).strip().rstrip(":")
    return tail


def _row(node, *, phase, kind=None, status=None, message=None, can_retry=None, detail=None):
    label = node.get("label") or "Mac"
    help_steps = short_help(kind, label) if kind and phase != "behind" else []
    if can_retry is None:
        can_retry = bool(kind)
    if status is None:
        status = STATUS_WORDS.get(phase, phase)
    if message is None:
        message = {
            "offline": f"Couldn't reach the {label}.",
            "failed": f"The update on the {label} failed.",
            "still_old": f"The {label} is still on the previous version.",
            "no_model": f"The {label} updated, but the model didn't come back.",
            "done": f"The {label}: done.",
            "updating": f"The {label}: updating…",
            "waiting": f"The {label}: waiting.",
            "behind": f"The {label} is on an older version.",
            "current": f"The {label} is up to date.",
        }.get(phase, f"The {label}: {status}.")
    return {
        "id": node.get("id"),
        "label": label,
        "mine": False,
        "phase": phase,
        "kind": kind,
        "status": status,
        "message": message,
        "help": help_steps,
        "can_retry": can_retry,
        "detail": detail or "",
    }


def local_row(*, phase="waiting", label="1st Mac", message=None, kind=None):
    node = {"id": "local", "label": label}
    row = _row(node, phase=phase, kind=kind, message=message, can_retry=False)
    row["mine"] = True
    row["id"] = "local"
    return row


def check_peers(peers, published_ref, *, runner=None):
    """Read each Mac's installed version. Offline is not treated as behind."""
    out = []
    published_ref = (published_ref or "").strip().lower() or None
    for node in peers or []:
        ref = read_peer_ref(node, runner=runner)
        if ref is None:
            row = _row(node, phase="offline", kind="offline",
                       message=f"Couldn't check the {node.get('label') or 'Mac'} right now.",
                       detail="Couldn't reach it to read its version.")
            # Checking is not a failed update; still offer Try again to re-check / update.
            row["behind"] = False
            out.append(row)
            continue
        if published_ref and ref != published_ref:
            row = _row(node, phase="behind", can_retry=False)
            row["behind"] = True
            # still_old help is right when they're behind and an update is needed.
            # For "behind" before an update attempt, slightly milder help is the same steps.
            out.append(row)
        else:
            row = _row(node, phase="current", can_retry=False)
            row["behind"] = False
            out.append(row)
    return out


def any_behind(peer_rows):
    return any(r.get("behind") or r.get("phase") == "behind" for r in (peer_rows or []))


def update_peer(node, *, expected=None, runner=None, timeout=UPDATE_TIMEOUT):
    """Run caravan update on one already-paired Mac. Never raises."""
    label = node.get("label") or "Mac"
    probe = ssh_run(node, "true", runner=runner, timeout=CONNECT_TIMEOUT + 5)
    if probe is None or getattr(probe, "returncode", 1) != 0:
        return _row(node, phase="offline", kind="offline",
                    detail=_detail_text(probe, node) or "Couldn't reach it.")
    result = ssh_run(
        node, peer_update_command(), runner=runner, timeout=timeout,
    )
    if result is None:
        return _row(node, phase="failed", kind="failed",
                    message=f"The update on the {label} didn't finish.",
                    detail="No answer before the time limit.")
    if result.returncode == 127:
        return _row(
            node, phase="failed", kind="failed",
            message=f"Caravan on the {label} could not be found.",
            detail=_detail_text(result, node),
        )
    if result.returncode != 0:
        return _row(node, phase="failed", kind="failed", detail=_detail_text(result, node))
    if expected:
        ref = read_peer_ref(node, runner=runner)
        if ref and ref != str(expected).strip().lower():
            return _row(node, phase="still_old", kind="still_old",
                        detail="It finished, but is still on the previous version.")
    return _row(node, phase="done", can_retry=False)


def coordinator_label(peer_count):
    return "1st Mac" if peer_count else "My Mac"


def initial_progress(peers, *, local_phase="waiting", local_label=None):
    local_label = local_label or coordinator_label(len(peers or []))
    macs = [local_row(phase=local_phase, label=local_label)]
    for node in peers or []:
        macs.append(_row(node, phase="waiting", can_retry=False))
    return macs


def replace_mac(macs, mac_id, row):
    out = []
    found = False
    for item in macs or []:
        if not found and item.get("id") == mac_id:
            out.append(row)
            found = True
        else:
            out.append(item)
    if not found:
        out.append(row)
    return out


def update_other_macs(
    home,
    peers=None,
    *,
    expected=None,
    runner=None,
    on_progress=None,
    out=None,
    timeout=UPDATE_TIMEOUT,
):
    """Update every known other Mac. Returns the per-Mac rows.

    Peers are updated one at a time, in order. Failures do not stop the rest.
    """
    home = Path(home)
    if peers is None:
        peers = load_nodes(home)
    rows = []
    for node in peers or []:
        label = node.get("label") or "Mac"
        if out is not None:
            print(f"Updating the {label}…", file=out, flush=True)
        if on_progress:
            on_progress(_row(node, phase="updating", can_retry=False))
        row = update_peer(node, expected=expected, runner=runner, timeout=timeout)
        rows.append(row)
        record_peer_result(home, row)
        if out is not None:
            print(row["message"], file=out, flush=True)
            if row.get("detail"):
                print("  " + row["detail"], file=out, flush=True)
            for step in row.get("help") or []:
                print("  " + step, file=out, flush=True)
        if on_progress:
            on_progress(row)
    return rows


def peer_errors_path(home):
    return Path(home) / ".caravan" / "web-ui" / "peer-update-errors.json"


def record_peer_result(home, row):
    """Keep each Mac's last update error so it can be read later."""
    import json
    if not home or not isinstance(row, dict) or not row.get("id"):
        return
    path = peer_errors_path(home)
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    if row.get("phase") in ("done", "current"):
        data.pop(str(row["id"]), None)
    else:
        data[str(row["id"])] = {
            "label": row.get("label"),
            "phase": row.get("phase"),
            "detail": row.get("detail") or "",
            "at": time.time(),
        }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
    except OSError:
        pass


def model_did_not_return(home, *, status_fn=None, last_model_fn=None):
    """True when a model was saved and the page is back without it ready."""
    if last_model_fn is not None:
        has = last_model_fn()
    else:
        path = Path(home) / ".caravan" / "web-ui" / "last-model.json"
        try:
            has = path.is_file() and path.stat().st_size > 0
        except OSError:
            has = False
    if not has:
        return False
    if status_fn is None:
        return False
    try:
        snap = status_fn() or {}
    except Exception:
        return True
    status = snap.get("status") or (snap.get("worker") or {}).get("status") or ""
    return status not in ("ready",)


def no_model_help(label="Macs"):
    return short_help("no_model", label)


if __name__ == "__main__":
    sys.exit(0)
