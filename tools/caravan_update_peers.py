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
from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text)

# Short connect; the update itself may take several minutes (download + swap).
CONNECT_TIMEOUT = 10
UPDATE_TIMEOUT = 600
# First source build of the own-part engine can take up to the cmake timeout
# (1800 s) plus install work. Used only when no checksummed prebuilt is pinned.
SOURCE_BUILD_UPDATE_TIMEOUT = 2400
CHECK_TIMEOUT = 20


def peer_update_timeout():
    """10 minutes when a prebuilt engine can be downloaded; longer for a first source build."""
    try:
        root = Path(__file__).resolve().parents[1]
        import sys
        sys.path.insert(0, str(root / "agent"))
        from gguf_runtime import prebuilt_configured
        if prebuilt_configured():
            return UPDATE_TIMEOUT
    except Exception:  # noqa: BLE001 - never block an update on the pin file
        pass
    return SOURCE_BUILD_UPDATE_TIMEOUT

DEFAULT_REPO = "~/.caravan/src/caravan"
DEFAULT_COMMAND = "~/.caravan/bin/caravan"


def ordinal_mac(index):
    """1st Mac, 2nd Mac, 3rd Mac, … — never a hostname."""
    return T("cli.update_peers.nth_mac", nth=T.ordinal(int(index) + 1))


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
    if raw in ("My Mac", T("cli.update_check.my_mac")):  # saved English or this language
        return raw
    if (raw.endswith(" Mac") and raw[0].isdigit()) or raw in {ordinal_mac(i) for i in range(32)}:
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
    config = (node.get("ssh_config") or "").strip()
    route_opts = []
    if not config:
        # Link-order fix: update-all-Macs uses the same link order as loads.
        try:
            import peer_route as PR
            route_opts = PR.host_opts(target, (PR.route_for(target, label=node.get("label")) or {}).get("address"))
        except Exception:  # noqa: BLE001 - never block an update on the picker
            route_opts = []
    argv = [
        "ssh", *route_opts,
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={CONNECT_TIMEOUT}",
        "-o", "StrictHostKeyChecking=yes",
    ]
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
    label = label or T("cli.update_peers.mac")
    if kind == "offline":
        return [
            T("cli.update_peers.check_that_the_label_is_on", label=label),
            T("cli.update_peers.check_that_its_on_the_same"),
            T("cli.update_peers.then_click_try_again_or_on", label=label),
            T("cli.update_peers.after_that_mac_is_updated_load"),
        ]
    if kind == "failed":
        return [
            T("cli.update_peers.the_update_on_the_label_didnt", label=label),
            T("cli.update_peers.check_that_the_label_is_on_2", label=label),
            T("cli.update_peers.click_try_again_or_on_the", label=label),
            T("cli.update_peers.after_that_mac_is_updated_load"),
        ]
    if kind == "still_old":
        return [
            T("cli.update_peers.the_label_is_still_on_the", label=label),
            T("cli.update_peers.check_that_the_label_is_on_2", label=label),
            T("cli.update_peers.click_try_again_or_on_the", label=label),
            T("cli.update_peers.after_that_mac_is_updated_load"),
        ]
    if kind == "no_model":
        return [
            T("cli.update_peers.the_label_updated_but_the_model", label=label),
            T("cli.update_peers.on_this_mac_open_models_and"),
            T("cli.update_peers.if_that_doesnt_work_on_the", label=label),
        ]
    return []


STATUS_WORDS = {
    "done": "current",
    "current": "current",
    "updating": T("cli.update_peers.updating"),
    "waiting": T("cli.update_check.update_needed"),
    "behind": T("cli.update_check.update_needed"),
    "offline": "failed",
    "failed": "failed",
    "still_old": "failed",
    "no_model": "failed",
}


def short_help(kind, label):
    """At most one short line under a Mac that failed."""
    if kind == "no_model":
        return [T("cli.update_peers.load_your_model_again_in_models")]
    if kind in ("offline", "failed", "still_old"):
        return [T("cli.update_peers.on_the_label_run_caravan_update", label=label)]
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
    label = node.get("label") or T("cli.update_peers.mac")
    for secret in {_ssh_target(node), (node.get("host") or "").strip()}:
        if secret:
            tail = tail.replace(secret, label)
    code = getattr(result, "returncode", None)
    if code not in (None, 0):
        tail = (f"exit {code}: " + tail).strip().rstrip(":")
    return tail


def _row(node, *, phase, kind=None, status=None, message=None, can_retry=None, detail=None):
    label = node.get("label") or T("cli.update_peers.mac")
    help_steps = short_help(kind, label) if kind and phase != "behind" else []
    if can_retry is None:
        can_retry = bool(kind)
    if status is None:
        status = STATUS_WORDS.get(phase, phase)
    if message is None:
        message = {
            "offline": T("cli.update_peers.couldnt_reach_the_label", label=label),
            "failed": T("cli.update_peers.the_update_on_the_label_failed", label=label),
            "still_old": T("cli.update_peers.the_label_is_still_on_the", label=label),
            "no_model": T("cli.update_peers.the_label_updated_but_the_model", label=label),
            "done": T("cli.update_peers.the_label_done", label=label),
            "updating": T("cli.update_peers.the_label_updating", label=label),
            "waiting": T("cli.update_peers.the_label_waiting", label=label),
            "behind": T("cli.update_peers.the_label_is_on_an_older", label=label),
            "current": T("cli.update_peers.the_label_is_up_to_date", label=label),
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


def local_row(*, phase="waiting", label=T("cli.update_check.1st_mac"), message=None, kind=None, detail=None):
    node = {"id": "local", "label": label}
    row = _row(node, phase=phase, kind=kind, message=message, can_retry=False, detail=detail)
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
                       message=T("cli.update_peers.couldnt_check_the_v_right_now", v=node.get('label') or 'Mac'),
                       detail=T("cli.update_peers.couldnt_reach_it_to_read_its"))
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


def update_peer(node, *, expected=None, runner=None, timeout=None):
    """Run caravan update on one already-paired Mac. Never raises."""
    if timeout is None:
        timeout = peer_update_timeout()
    label = node.get("label") or T("cli.update_peers.mac")
    probe = ssh_run(node, "true", runner=runner, timeout=CONNECT_TIMEOUT + 5)
    if probe is None or getattr(probe, "returncode", 1) != 0:
        return _row(node, phase="offline", kind="offline",
                    detail=_detail_text(probe, node) or T("cli.update_peers.couldnt_reach_it"))
    result = ssh_run(
        node, peer_update_command(), runner=runner, timeout=timeout,
    )
    if result is None:
        return _row(node, phase="failed", kind="failed",
                    message=T("cli.update_peers.the_update_on_the_label_didnt_2", label=label),
                    detail=T("cli.update_peers.no_answer_before_the_time_limit"))
    if result.returncode == 127:
        return _row(
            node, phase="failed", kind="failed",
            message=T("cli.update_peers.caravan_on_the_label_could_not", label=label),
            detail=_detail_text(result, node),
        )
    if result.returncode != 0:
        return _row(node, phase="failed", kind="failed", detail=_detail_text(result, node))
    if expected:
        ref = read_peer_ref(node, runner=runner)
        if ref and ref != str(expected).strip().lower():
            return _row(node, phase="still_old", kind="still_old",
                        detail=T("cli.update_peers.it_finished_but_is_still_on"))
    return _row(node, phase="done", can_retry=False)


def coordinator_label(peer_count):
    return T("cli.update_check.1st_mac") if peer_count else T("cli.update_check.my_mac")


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
    timeout=None,
):
    """Update every known other Mac. Returns the per-Mac rows.

    Peers are updated one at a time, in order. Failures do not stop the rest.
    """
    home = Path(home)
    if peers is None:
        peers = load_nodes(home)
    if timeout is None:
        timeout = peer_update_timeout()
    rows = []
    for node in peers or []:
        label = node.get("label") or T("cli.update_peers.mac")
        if out is not None:
            print(T("cli.update_peers.updating_the_label", label=label), file=out, flush=True)
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


def no_model_help(label=T("cli.update_peers.macs")):
    return short_help("no_model", label)


if __name__ == "__main__":
    sys.exit(0)
