"""SSH local forwards for a worker on another Mac.

A leftover forward can hold 127.0.0.1:<port> after the web page restarts
(the ssh process is reparented to launchd / init). The next load must
reuse that forward when it is still ours and still works, or stop only
that process and open a new one. A process that is not Caravan's own
forward is never killed.
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import signal
import socket
import subprocess
import time
from pathlib import Path

log = logging.getLogger("caravan.tunnel")

# Flags we ourselves pass when opening a worker forward.
_SSH_FLAGS = ("BatchMode=yes", "ExitOnForwardFailure=yes")


def forward_spec(port) -> str:
    return f"{int(port)}:127.0.0.1:{int(port)}"


def _L_ports(spec):
    """Local and remote ports from an ssh -L argument, or (None, None)."""
    if not spec:
        return None, None
    parts = str(spec).split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]), int(parts[2])
        if len(parts) == 4:
            # 127.0.0.1:8194:127.0.0.1:8194
            return int(parts[1]), int(parts[3])
    except ValueError:
        return None, None
    return None, None


def tunnel_matches(command, target, port) -> bool:
    """True when this command is our ssh -N -L <port> to this host alias."""
    try:
        args = shlex.split(command or "")
    except ValueError:
        return False
    if not args or Path(args[0]).name != "ssh" or "-N" not in args:
        return False
    if target and args[-1] != str(target):
        return False
    try:
        from worker_ownership import option
        spec = option(args, "-L")
    except Exception:
        spec = None
        for i, a in enumerate(args):
            if a == "-L" and i + 1 < len(args):
                spec = args[i + 1]
                break
            if a.startswith("-L") and len(a) > 2:
                spec = a[2:]
                break
    local, remote = _L_ports(spec)
    want = int(port)
    return local == want and remote == want


def is_ours(command, *, port=None, target=None) -> bool:
    """A Caravan worker forward, optionally pinned to a port and host alias."""
    if port is not None and target is not None:
        return tunnel_matches(command, target, port)
    try:
        args = shlex.split(command or "")
    except ValueError:
        return False
    if not args or Path(args[0]).name != "ssh" or "-N" not in args:
        return False
    if not any(f in command for f in _SSH_FLAGS):
        # Still accept a minimal -N -L to 127.0.0.1, used by older / tests.
        if "-L" not in command and not any(a.startswith("-L") for a in args):
            return False
    if port is None:
        return True
    return tunnel_matches(command, target or (args[-1] if args else ""), port)


def command_of(pid, *, inspect=None) -> str:
    if inspect is not None:
        try:
            return inspect(pid) or ""
        except Exception:
            return ""
    try:
        from worker_ownership import command_of as _cmd
        return _cmd(pid) or ""
    except Exception:
        return ""


def listeners_on_port(port, *, lsof=None) -> list:
    """PIDs with a TCP LISTEN on 127.0.0.1:<port> (or any interface)."""
    port = int(port)
    if lsof is not None:
        return list(lsof(port) or [])
    pids = []
    for bin in ("/usr/sbin/lsof", "lsof", "/usr/bin/lsof"):
        try:
            r = subprocess.run(
                [bin, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True, text=True, timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid not in pids:
                    pids.append(pid)
        break
    return pids


def ours_on_port(port, target, *, inspect=None, lsof=None) -> list:
    """Our ssh forwards to this host alias and port that currently listen."""
    found = []
    for pid in listeners_on_port(port, lsof=lsof):
        if pid <= 1:
            continue
        cmd = command_of(pid, inspect=inspect)
        if tunnel_matches(cmd, target, port):
            found.append(int(pid))
    return found


def foreign_on_port(port, target, *, inspect=None, lsof=None) -> list:
    """Listeners on the port that are not our forward to this target."""
    foreign = []
    for pid in listeners_on_port(port, lsof=lsof):
        if pid <= 1:
            continue
        cmd = command_of(pid, inspect=inspect)
        if not tunnel_matches(cmd, target, port):
            foreign.append(int(pid))
    return foreign


def tcp_connects(port, *, timeout=0.8, opener=None) -> bool:
    """True when something accepts a TCP connection on 127.0.0.1:<port>."""
    if opener is not None:
        return bool(opener(port))
    s = None
    try:
        s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
        return True
    except OSError:
        return False
    finally:
        if s is not None:
            try:
                s.close()
            except OSError:
                pass


def probe_forward(port, *, timeout=0.8, opener=None) -> bool:
    """A working forward: the local port accepts a connection."""
    return tcp_connects(port, timeout=timeout, opener=opener)


def stop_owned(pid, target, port, *, inspect=None, send=None, pause=None, timeout=3.0) -> bool:
    """Stop this pid only if it is still our forward. Returns True if gone.

    Never signals a process whose command line no longer matches.
    """
    send = send or os.kill
    pause = pause or time.sleep
    pid = int(pid)
    if pid <= 1:
        return False
    cmd = command_of(pid, inspect=inspect)
    if not tunnel_matches(cmd, target, port):
        return False
    try:
        send(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        log.warning("no permission to stop owned tunnel pid %s", pid)
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cmd = command_of(pid, inspect=inspect)
        if not cmd or not tunnel_matches(cmd, target, port):
            return True
        pause(0.05)
    # Still ours: one polite kill. Recheck identity first.
    cmd = command_of(pid, inspect=inspect)
    if tunnel_matches(cmd, target, port):
        try:
            send(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        pause(0.05)
    cmd = command_of(pid, inspect=inspect)
    return not cmd or not tunnel_matches(cmd, target, port)


def tunnel_argv(target, port) -> list:
    p = str(int(port))
    return [
        "ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=15", "-N",
        "-L", f"{p}:127.0.0.1:{p}", str(target),
    ]


def _spawn(target, port, *, popen=None):
    popen = popen or subprocess.Popen
    return popen(
        tunnel_argv(target, port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


class TunnelError(RuntimeError):
    """User-facing plain message; ``detail`` is for the log only."""

    def __init__(self, plain: str, detail: str = ""):
        super().__init__(plain)
        self.detail = detail or ""
        self.plain = plain


def plain_tunnel_error(exc=None, *, mac: str = "", detail: str = "") -> str:
    """One short line. No hostname, paired id, path, or ssh trace."""
    who = (mac or "").strip() or "the other Mac"
    if who.lower() in ("mac", "the other mac"):
        who = "the other Mac"
    elif not who.lower().startswith("the "):
        who = "the " + who
    text = " ".join(str(exc or "").split())
    low = text.lower()
    if "already in use" in low or "cannot listen" in low or "local forwarding" in low:
        return f"Couldn't start the model on {who}. Try loading again."
    if "permission" in low or "denied" in low:
        return f"Couldn't reach {who}. Try loading again."
    return f"Couldn't start the model on {who}. Try loading again."


def ensure_forward(
    target,
    port,
    *,
    inspect=None,
    lsof=None,
    probe=None,
    popen=None,
    send=None,
    pause=None,
    sleep=None,
    spawn_wait=0.4,
):
    """Reuse our working forward, or replace only our own, or raise TunnelError.

    Returns ``{"pid": int, "proc": Popen|None, "reused": bool}``.
    ``proc`` is set only when this call started a new ssh.
    """
    target = (target or "").strip()
    port = int(port)
    if not target:
        raise TunnelError(
            plain_tunnel_error(mac="the other Mac"),
            detail="no ssh target for worker tunnel",
        )
    pause = pause or sleep or time.sleep
    probe = probe or (lambda: probe_forward(port))

    def ours():
        return ours_on_port(port, target, inspect=inspect, lsof=lsof)

    held = ours()
    if held:
        pid = held[0]
        if probe():
            log.info("reusing worker tunnel pid %s to %s on port %s", pid, target, port)
            return {"pid": pid, "proc": None, "reused": True}
        log.info("owned worker tunnel pid %s is not usable; replacing it", pid)
        if not stop_owned(pid, target, port, inspect=inspect, send=send, pause=pause):
            # Still ours and still stuck: do not open a second forward, and
            # do not touch anyone else.
            detail = f"owned ssh tunnel pid {pid} still holds 127.0.0.1:{port}"
            log.error(detail)
            raise TunnelError(plain_tunnel_error("already in use"), detail=detail)
        # Fall through and open a new one.
    else:
        foreign = foreign_on_port(port, target, inspect=inspect, lsof=lsof)
        if foreign:
            detail = (
                f"port {port} is held by pid {foreign[0]} "
                f"({command_of(foreign[0], inspect=inspect)[:200]}); not ours, not killed"
            )
            log.error(detail)
            raise TunnelError(plain_tunnel_error("already in use"), detail=detail)

    proc = _spawn(target, port, popen=popen)
    pause(spawn_wait)
    if proc.poll() is not None:
        err = b""
        try:
            err = proc.stderr.read() if proc.stderr else b""
        except Exception:
            pass
        raw = (err or b"").decode(errors="replace")[:400]
        log.error("new worker tunnel exited: %s", raw)
        # A bind race: maybe our leftover appeared; try reuse once.
        held = ours()
        if held and probe():
            log.info("reusing worker tunnel pid %s after bind race", held[0])
            return {"pid": held[0], "proc": None, "reused": True}
        raise TunnelError(plain_tunnel_error(raw or "already in use"), detail=raw)
    return {"pid": int(proc.pid), "proc": proc, "reused": False}


def stop_forward(target, port, *, pids=None, inspect=None, lsof=None, send=None, pause=None):
    """Stop every owned forward to this host alias and port, plus given pids."""
    seen = set()
    for pid in list(pids or []) + ours_on_port(port, target, inspect=inspect, lsof=lsof):
        if not pid or pid in seen or int(pid) <= 1:
            continue
        seen.add(int(pid))
        stop_owned(int(pid), target, port, inspect=inspect, send=send, pause=pause)


# Host aliases and paths that must never appear in a user-facing line.
_HIDDEN = re.compile(
    r"(prf-hays[\w.-]*|caravan-[0-9a-f]{16,}|paired_[0-9a-f]{8,}|"
    r"/Users/[^\s)]+|/home/[^\s)]+|~/\.caravan/[^\s)]+|"
    r"bind\s*\[.*?\]:\d+|Address already in use|"
    r"channel_setup_fwd_listener[^\n]*|Could not request local forwarding|"
    r"EXO\d+)",
    re.I,
)


def plain_load_status(msg: str, *, mac: str = "") -> str:
    """Drop hostnames, paired ids, and paths from a load-progress line."""
    s = " ".join(str(msg or "").split())
    if not s:
        return s
    if _HIDDEN.search(s) or "/.caravan/" in s:
        # Known starting lines: keep the plain verb, name the Mac.
        low = s.lower()
        who = (mac or "the other Mac").strip()
        if "single-mini" in low or "single mini" in low:
            return f"starting single-Mini worker on {who}" if who else "starting single-Mini worker"
        if "tunnel" in low or "forward" in low or "already in use" in low:
            return plain_tunnel_error(s, mac=mac)
        # Strip hidden tokens and leftover punctuation.
        cleaned = _HIDDEN.sub("", s)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\(\s*\)", "", cleaned).strip(" ·-:")
        return cleaned or (f"starting the model on {who}" if who else "starting the model")
    return s
