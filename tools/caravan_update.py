#!/usr/bin/env python3
"""Single-step package update: stop what is needed, swap, start, or roll back.

This module is stdlib-only at import time so the bootstrap can run it from a
freshly extracted package with the existing Caravan Python.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


OPENING = "Updating Caravan, the page will be back in a few seconds."
UP_TO_DATE = "Caravan is already up to date."
RELOADING = "The model is reloading."
FAILED = (
    "The update failed. Caravan is back on the previous version. "
    "Check your internet connection and try again."
)

# Hash changes under these paths mean the running model must be stopped and
# restored with the new code. agent/ is the model process (mlx_worker,
# llama runtime, split, the service agent). runtime/ is the llama.cpp pin
# and bundled helpers. The requirements files are the venv inputs; a
# changed lock means workers should reload against the new packages.
WORKER_CODE_PATHS = (
    "agent/",
    "runtime/",
    "requirements-mac.lock",
    "requirements-mac.txt",
)

# Optional LaunchAgent com.caravan.v3.proxy (slot-pin proxy).
PROXY_CODE_PATHS = (
    "proxy/slot_pin_proxy.py",
)

# Optional LaunchAgent com.caravan.v3.aux (auxiliary title worker).
AUX_CODE_PATHS = (
    "tools/aux_worker.py",
)

# A changed lock also refreshes the venv used by proxy and aux.
VENV_PATHS = (
    "requirements-mac.lock",
    "requirements-mac.txt",
)

KNOWN_OPTIONAL = ("proxy", "aux", "worker")


def normalize(path):
    text = str(path).replace("\\", "/").lstrip("./")
    return text


def load_hashes(path):
    """Parse a `.caravan-package-files` manifest (shasum -a 256 output)."""
    result = {}
    text = Path(path).read_text()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError("Package integrity list is unreadable")
        result[normalize(parts[1])] = parts[0].lower()
    return result


def matches_prefix(path, prefixes):
    path = normalize(path)
    for prefix in prefixes:
        prefix = normalize(prefix)
        if prefix.endswith("/"):
            if path.startswith(prefix) or path + "/" == prefix:
                return True
        elif path == prefix:
            return True
    return False


def changed_paths(old, new, prefixes):
    """Relpaths under prefixes whose hash changed, appeared, or disappeared."""
    keys = set()
    for collection in (old, new):
        keys.update(path for path in collection if matches_prefix(path, prefixes))
    return sorted(path for path in keys if old.get(path) != new.get(path))


def plan_update(old, new):
    """Decide what an update must restart, given two package-file manifests."""
    worker = changed_paths(old, new, WORKER_CODE_PATHS)
    venv = changed_paths(old, new, VENV_PATHS)
    proxy = changed_paths(old, new, PROXY_CODE_PATHS) or venv
    aux = changed_paths(old, new, AUX_CODE_PATHS) or venv or worker
    return {
        "reload_workers": bool(worker),
        "restart_proxy": bool(proxy),
        "restart_aux": bool(aux),
        "restart_web": True,
        "worker_changes": worker,
        "proxy_changes": changed_paths(old, new, PROXY_CODE_PATHS),
        "aux_changes": changed_paths(old, new, AUX_CODE_PATHS),
    }


def user_id():
    try:
        return int(subprocess.check_output(["id", "-u"], text=True).strip())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return os.getuid()


def domain():
    return f"gui/{user_id()}"


def default_launchctl(args, **kwargs):
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        timeout=kwargs.get("timeout", 30),
    )


def label_of(name):
    return f"com.caravan.v3.{name}"


def last_model_path(home):
    return Path(home) / ".caravan" / "web-ui" / "last-model.json"


def has_saved_model(home):
    path = last_model_path(home)
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        blob = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if isinstance(blob, dict) and blob.get("request"):
        return True
    return False


def service_plist(home, name):
    return Path(home) / "Library" / "LaunchAgents" / f"{label_of(name)}.plist"


def installed_service_names(home):
    names = []
    root = Path(home) / ".caravan" / "services"
    for path in list(root.glob("*.json")) + list((root / "login").glob("*.json")):
        if path.stem and path.stem not in names:
            names.append(path.stem)
    if "web" not in names:
        names.insert(0, "web")
    return names


def loaded_services(home, names=None, *, run=default_launchctl):
    found = []
    for name in names or installed_service_names(home):
        result = run(["print", f"{domain()}/{label_of(name)}"])
        if result.returncode == 0:
            found.append(name)
    return found


def stop_service(name, *, run=default_launchctl):
    target = f"{domain()}/{label_of(name)}"
    result = run(["print", target])
    if result.returncode != 0:
        return False
    result = run(["bootout", target])
    if result.returncode:
        raise ValueError(result.stderr or result.stdout or f"could not stop {name}")
    return True


def start_service(home, name, *, run=default_launchctl):
    target = f"{domain()}/{label_of(name)}"
    if run(["print", target]).returncode == 0:
        return False
    plist = service_plist(home, name)
    if not plist.is_file():
        raise ValueError(f"Startup file for {name} is missing")
    result = run(["bootstrap", domain(), str(plist)])
    if result.returncode:
        raise ValueError(result.stderr or result.stdout or f"could not start {name}")
    return True


def _command_of(pid):
    try:
        return subprocess.check_output(
            ["ps", "-o", "command=", "-p", str(pid)], text=True, timeout=5
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _term(pid, inspect=_command_of, send=os.kill, pause=time.sleep, timeout=8):
    pid = int(pid)
    if pid <= 1:
        return False
    try:
        send(pid, 15)
    except (ProcessLookupError, OSError, PermissionError):
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not inspect(pid):
            return True
        pause(0.05)
    try:
        if inspect(pid):
            send(pid, 9)
    except (ProcessLookupError, OSError, PermissionError):
        pass
    return True


def _ssh_stop(target, command, *, run_ssh=None, timeout=25):
    run_ssh = run_ssh or subprocess.run
    try:
        return run_ssh(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None


def _remote_ownership_command(repo, marker, *, pid=None, port=None, listen=None):
    repo = (repo or "~/cv3").rstrip("/")
    cmd = (
        "python3 "
        + repo
        + "/proxy/worker_ownership.py --worker "
        + repo
        + "/agent/mlx_worker.py --pid-file "
        + marker
    )
    if pid:
        cmd += " --pid " + str(int(pid))
    if port is not None:
        cmd += " --port " + str(int(port))
    if listen is not None:
        cmd += " --listen " + str(listen)
    return cmd


def _stop_tracked_mlx(home, repo, *, lead_port, inspect, send, pause, ownership_stop):
    """Stop a local mlx_worker recorded in lead.pid, fail-closed on identity."""
    worker = Path(repo) / "agent" / "mlx_worker.py"
    pid_file = Path(home) / ".caravan" / "web-ui" / "lead.pid"
    if ownership_stop is not None:
        ownership_stop(str(worker), pid_file=str(pid_file), port=lead_port)
        return
    try:
        sys.path.insert(0, str(Path(repo) / "proxy"))
        from worker_ownership import stop as owned_stop
        owned_stop(
            worker,
            pid_file=pid_file,
            port=lead_port,
            inspect=inspect,
            send=send,
            pause=pause,
        )
    except Exception:
        try:
            pid = int(pid_file.read_text().strip())
        except (OSError, ValueError):
            return
        command = inspect(pid)
        if "mlx_worker.py" in command:
            _term(pid, inspect=inspect, send=send, pause=pause)


def _stop_gguf(home, *, inspect, send, pause, run_ssh):
    meta_path = Path(home) / ".caravan" / "web-ui" / "gguf.json"
    if not meta_path.is_file():
        return
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return
    pid = meta.get("lead_pid")
    if pid and "llama-server" in inspect(pid):
        _term(pid, inspect=inspect, send=send, pause=pause)
    for tunnel in meta.get("tunnels") or []:
        if not isinstance(tunnel, dict):
            continue
        tp = tunnel.get("pid")
        if tp and ("ssh" in inspect(tp) and "-L" in inspect(tp)):
            _term(tp, inspect=inspect, send=send, pause=pause)
    for peer in meta.get("peers") or []:
        if not isinstance(peer, dict):
            continue
        target = (peer.get("ssh") or "").strip()
        command = peer.get("stop") or "pkill -f 'rpc-server' || true"
        if target:
            # Best-effort: a paired Mac that is offline must not fail the update.
            if run_ssh is not None:
                _ssh_stop(target, command if "rpc" in str(command) else command, run_ssh=run_ssh)
    # Leave the file; a new load rewrites it. Never touch last-model.json.


def _is_our_tunnel(command, target, port):
    """True when this command is Caravan's ssh -N -L <port> to this host alias.

    Stdlib-only: this module cannot import proxy/ at import time.
    """
    try:
        args = shlex.split(command or "")
    except ValueError:
        return False
    if not args or Path(args[0]).name != "ssh" or "-N" not in args:
        return False
    if target and args[-1] != str(target):
        return False
    flag = f"{int(port)}:127.0.0.1:{int(port)}"
    for i, a in enumerate(args):
        if a == "-L" and i + 1 < len(args) and args[i + 1] == flag:
            return True
        if a.startswith("-L") and flag in a:
            return True
    return False


def _stop_owned_local_tunnels(meta, lead_port, *, inspect=None, send=None, pause=None):
    """Stop leftover local ssh forwards recorded for a remote MLX worker.

    Only a pid whose command line still matches our forward is signaled.
    """
    inspect = inspect or _command_of
    send = send or os.kill
    pause = pause or time.sleep
    target = ((meta or {}).get("ssh") or "").strip()
    pids = []
    tid = (meta or {}).get("tunnel_pid")
    if tid:
        try:
            pids.append(int(tid))
        except (TypeError, ValueError):
            pass
    if not target or not pids:
        return
    import signal as _signal
    for pid in pids:
        if pid <= 1:
            continue
        try:
            cmd = inspect(pid) or ""
        except Exception:
            cmd = ""
        if not _is_our_tunnel(cmd, target, lead_port):
            continue
        try:
            send(pid, _signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                cmd = inspect(pid) or ""
            except Exception:
                cmd = ""
            if not cmd or not _is_our_tunnel(cmd, target, lead_port):
                break
            pause(0.05)


def _stop_remote_mlx(home, *, lead_port, run_ssh, inspect=None, send=None, pause=None):
    meta_path = Path(home) / ".caravan" / "web-ui" / "remote-worker.json"
    if not meta_path.is_file():
        return
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return
    # Local leftover forward first: does not need SSH to the other Mac.
    _stop_owned_local_tunnels(
        meta, lead_port, inspect=inspect, send=send, pause=pause)
    target = (meta.get("ssh") or "").strip()
    if not target or run_ssh is None:
        return
    command = _remote_ownership_command(
        meta.get("repo") or "~/cv3",
        "~/.caravan/web-ui/remote-lead.pid",
        pid=meta.get("pid"),
        port=lead_port,
    )
    _ssh_stop(target, command, run_ssh=run_ssh)


def _stop_remote_packer(home, *, run_ssh):
    # Recorded SSH helper used by the two-Mac split; same pid-file the app uses.
    for name in ("packer-ssh.json", "pipeline-balance.json"):
        path = Path(home) / ".caravan" / "web-ui" / name
        if not path.is_file():
            continue
        try:
            meta = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        target = (meta.get("ssh") or meta.get("packer_ssh") or "").strip()
        repo = meta.get("repo") or "~/cv3"
        if target and run_ssh is not None:
            command = _remote_ownership_command(repo, "~/.caravan/web-ui/packer.pid")
            _ssh_stop(target, command, run_ssh=run_ssh)


def stop_model_workers(
    home,
    repo,
    *,
    lead_port=8194,
    inspect=None,
    send=os.kill,
    pause=time.sleep,
    run_ssh=None,
    ownership_stop=None,
):
    """Stop web-owned model processes without clearing last-model.json.

    Local mlx_worker and llama-server processes are stopped only when their
    recorded pid still matches a Caravan worker. A paired Mac is asked to
    stop its worker with the same SSH command the app already uses. A
    failed or missing remote stop does not raise; the lead continues, and
    the other Mac is updated separately.
    """
    inspect = inspect or _command_of
    run_ssh = subprocess.run if run_ssh is None else run_ssh
    before = None
    path = last_model_path(home)
    if path.is_file():
        before = path.read_bytes()
    _stop_tracked_mlx(
        home, repo, lead_port=lead_port, inspect=inspect, send=send,
        pause=pause, ownership_stop=ownership_stop,
    )
    _stop_gguf(home, inspect=inspect, send=send, pause=pause, run_ssh=run_ssh)
    _stop_remote_mlx(
        home, lead_port=lead_port, run_ssh=run_ssh,
        inspect=inspect, send=send, pause=pause,
    )
    _stop_remote_packer(home, run_ssh=run_ssh)
    if path.is_file() and before is not None and path.read_bytes() != before:
        raise ValueError("Update must not clear the saved model")
    return has_saved_model(home) or (before is not None)


def swap_source(repo, new_source, backup_dir=None, *, clock=time.time):
    repo = Path(repo)
    new_source = Path(new_source)
    if backup_dir is None:
        backup_dir = repo.parent / f"caravan-backup-{int(clock())}"
    backup_dir = Path(backup_dir)
    if repo.exists():
        if backup_dir.exists():
            raise ValueError(f"Backup folder already exists: {backup_dir}")
        shutil.move(str(repo), str(backup_dir))
        try:
            shutil.move(str(new_source), str(repo))
        except (OSError, ValueError):
            if not repo.exists() and backup_dir.exists():
                shutil.move(str(backup_dir), str(repo))
            raise
    else:
        shutil.move(str(new_source), str(repo))
    return backup_dir


def restore_source(repo, backup):
    repo = Path(repo)
    backup = Path(backup)
    if not backup.exists():
        return False
    if repo.exists():
        shutil.rmtree(repo)
    shutil.move(str(backup), str(repo))
    return True


def run_installer(repo, *, home, python, role, name, port, log=None, runner=None):
    script = Path(repo) / "scripts" / "install.sh"
    cmd = [
        "bash",
        str(script),
        "--use-existing",
        "--update",
        "--repo",
        str(repo),
        "--python",
        str(python),
        "--role",
        role,
        "--name",
        name,
        "--port",
        str(port),
        "--no-start",
    ]
    env = {**os.environ, "HOME": str(home)}
    runner = runner or subprocess.run
    result = runner(cmd, env=env, capture_output=True, text=True)
    if log is not None:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        Path(log).write_text(
            (result.stdout or "") + (result.stderr or ""), encoding="utf-8"
        )
    if result.returncode:
        raise ValueError(
            (result.stderr or result.stdout or "Installer failed").strip()[:500]
        )
    return result


def wait_for_web(port, *, timeout=30, opener=None, pause=time.sleep):
    opener = opener or urllib.request.urlopen
    deadline = time.monotonic() + timeout
    last = None
    url = f"http://127.0.0.1:{int(port)}/api/status"
    while time.monotonic() < deadline:
        try:
            with opener(url, timeout=2) as response:
                data = json.load(response)
            if isinstance(data, dict) and isinstance(data.get("worker"), dict):
                return True
        except (OSError, urllib.error.URLError, ValueError) as error:
            last = error
        pause(0.25)
    raise ValueError(f"The page did not come back in time{': ' + str(last) if last else ''}")


def print_status(home, name="web", *, opener=None, file=None):
    """Same one-line result as `caravan status`."""
    file = sys.stdout if file is None else file
    port = 8190
    try:
        plan_path = Path(home) / ".caravan" / "services" / f"{name}.json"
        login = Path(home) / ".caravan" / "services" / "login" / f"{name}.json"
        path = plan_path if plan_path.is_file() else login
        if path.is_file():
            port = int(json.loads(path.read_text())["port"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    opener = opener or urllib.request.urlopen
    try:
        with opener(f"http://127.0.0.1:{int(port)}/api/status", timeout=3) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not isinstance(data.get("worker"), dict):
            raise ValueError("Unexpected status response")
        if data["worker"].get("error"):
            problem = " ".join(str(data["worker"]["error"]).split())
            print(
                f"Caravan is not running: {problem.rstrip('.')}. "
                "Open Caravan and load the model again; run caravan doctor if it fails.",
                file=file,
            )
            return 1
        print("Caravan is running", file=file)
        return 0
    except (OSError, ValueError, urllib.error.URLError):
        print(
            "Caravan is not running: its browser service is stopped or not responding. "
            "Run caravan start; if that fails, run caravan doctor.",
            file=file,
        )
        return 1


def lead_port_of(home, name="web"):
    try:
        path = Path(home) / ".caravan" / "services" / f"{name}.json"
        plan = json.loads(path.read_text())
        return int(plan.get("lead_port") or plan.get("port") or 8194)
    except (OSError, ValueError, KeyError, TypeError):
        return 8194


def apply_update(
    home,
    repo,
    new_source,
    *,
    name="web",
    port=8190,
    role="lead",
    python=None,
    start=True,
    run=default_launchctl,
    installer=None,
    stop_workers=None,
    wait=wait_for_web,
    status=print_status,
    clock=time.time,
    out=None,
    log=None,
):
    """Stop, swap, install, start; roll back and restart the old version on failure.

    `start` is the --no-start flag inverted. Services that were running are
    always brought back, even when start is False (the previous CLI passed
    --no-start). If nothing was running and start is False, services stay
    stopped — that is the developer/test path.
    """
    out = sys.stdout if out is None else out
    home = Path(home)
    repo = Path(repo)
    new_source = Path(new_source)
    python = python or (home / ".caravan" / "venvs" / "mlx" / "bin" / "python")
    log = Path(log) if log else home / ".caravan" / "logs" / "update.log"
    old_files = load_hashes(repo / ".caravan-package-files")
    new_files = load_hashes(new_source / ".caravan-package-files")
    plan = plan_update(old_files, new_files)
    names = installed_service_names(home)
    running = loaded_services(home, names, run=run)
    should_start = set(running)
    if start or running:
        should_start.add(name)
    if plan["restart_proxy"] and "proxy" in running:
        should_start.add("proxy")
    if plan["restart_aux"] and "aux" in running:
        should_start.add("aux")
    if plan["reload_workers"] and "worker" in running:
        should_start.add("worker")

    print(OPENING, file=out, flush=True)

    backup = None
    stopped = []
    workers_stopped = False
    moved = False
    finished = False

    def rollback():
        nonlocal moved
        if moved and backup is not None:
            try:
                restore_source(repo, backup)
                moved = False
            except (OSError, ValueError):
                pass
            try:
                (installer or run_installer)(
                    repo, home=home, python=python, role=role,
                    name=name, port=port, log=log,
                )
            except (OSError, ValueError):
                pass
        for svc in stopped:
            if svc in should_start or svc in running:
                try:
                    start_service(home, svc, run=run)
                except (OSError, ValueError):
                    pass
        print(FAILED, file=out, flush=True)

    try:
        if plan["reload_workers"]:
            stopper = stop_workers or stop_model_workers
            will_restore = stopper(
                str(home), str(repo), lead_port=lead_port_of(home, name)
            )
            workers_stopped = True
            if will_restore is not False:
                print(RELOADING, file=out, flush=True)
        to_stop = set()
        if name in running:
            to_stop.add(name)  # rewrite its startup file, then start it again
        for optional in KNOWN_OPTIONAL:
            if optional in running and (
                (optional == "proxy" and plan["restart_proxy"])
                or (optional == "aux" and plan["restart_aux"])
                or (optional == "worker" and plan["reload_workers"])
            ):
                to_stop.add(optional)
        for svc in [name, *KNOWN_OPTIONAL]:
            if svc in to_stop:
                if stop_service(svc, run=run):
                    stopped.append(svc)
        backup = swap_source(repo, new_source, clock=clock)
        moved = True
        (installer or run_installer)(
            repo, home=home, python=python, role=role,
            name=name, port=port, log=log,
        )
        for svc in [name, *KNOWN_OPTIONAL]:
            if svc in should_start:
                start_service(home, svc, run=run)
        if name in should_start:
            wait(port)
        finished = True
        return status(home, name, file=out)
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        if not finished:
            rollback()
            return 1
        raise


def already_current(repo, ref):
    path = Path(repo) / ".caravan-package"
    try:
        return path.is_file() and path.read_text().strip() == str(ref).strip()
    except OSError:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--old", required=True)
    d.add_argument("--new", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--home", required=True)
    a.add_argument("--repo", required=True)
    a.add_argument("--new", required=True, dest="new_source")
    a.add_argument("--name", default="web")
    a.add_argument("--port", type=int, default=8190)
    a.add_argument("--role", default="lead")
    a.add_argument("--python")
    a.add_argument("--no-start", action="store_true")
    a.add_argument("--log")
    u = sub.add_parser("already")
    u.add_argument("--repo", required=True)
    u.add_argument("--ref", required=True)
    args = parser.parse_args(argv)
    if args.command == "decide":
        plan = plan_update(load_hashes(args.old), load_hashes(args.new))
        json.dump(plan, sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "already":
        if already_current(args.repo, args.ref):
            print(UP_TO_DATE)
            return 0
        return 1
    return apply_update(
        args.home,
        args.repo,
        args.new_source,
        name=args.name,
        port=args.port,
        role=args.role,
        python=args.python,
        start=not args.no_start,
        log=args.log,
    )


if __name__ == "__main__":
    sys.exit(main())
