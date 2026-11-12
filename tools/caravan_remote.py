#!/usr/bin/env python3
"""Opt-in Tailscale access to this Mac's local Caravan page.

The web service stays bound to 127.0.0.1. This only asks Tailscale to
forward that loopback port to devices on the same tailnet. It never
enables Funnel, never binds 0.0.0.0, and only removes Caravan's own
serve entry.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

QUESTION = "Open Caravan from your other devices over Tailscale? (y/N) "
LOOPBACKS = ("127.0.0.1", "localhost", "::1", "[::1]")
BINARIES = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/tailscale",
    "/opt/homebrew/bin/tailscale",
    "/usr/local/bin/tailscale",
)
MISSING = "Tailscale is not installed on this Mac. Install the Tailscale app, sign in, then try again."
LOGGED_OUT = "Tailscale is installed but not signed in. Open Tailscale, sign in, then try again."
NOT_RUNNING = "Tailscale is installed but not running. Open Tailscale, sign in, then try again."
UNAVAILABLE = "Tailscale could not be reached. Open Tailscale, sign in, then try again."


class RemoteError(Exception):
    """A plain-language failure the user can act on."""


def find_binary(which=shutil.which, exists=os.path.isfile, usable=os.access):
    for path in BINARIES:
        if exists(path) and usable(path, os.X_OK):
            return path
    return which("tailscale")


def config_path(home=None):
    env = os.environ.get("CARAVAN_CONFIG_TOML")
    if env:
        return Path(env).expanduser()
    return Path(home or Path.home()) / ".caravan" / "config.toml"


def web_port(home=None, name="web", default=8190):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caravan_service as service
        return int(service.stored(name, Path(home or Path.home()))["port"])
    except (OSError, ValueError, KeyError, ImportError):
        return default


def run_tailscale(args, *, binary=None, runner=None, timeout=15):
    binary = binary or find_binary()
    if not binary:
        raise RemoteError(MISSING)
    try:
        if runner is None:
            # The Mac app's bundled binary tries to launch its GUI when started
            # from a background service unless told to act as a plain CLI.
            env = dict(os.environ, TAILSCALE_BE_CLI="1")
            return subprocess.run([binary, *args], capture_output=True, text=True,
                                  timeout=timeout, env=env)
        return runner([binary, *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise RemoteError(MISSING) from e
    except subprocess.TimeoutExpired as e:
        raise RemoteError(UNAVAILABLE) from e


def _decode_status(result):
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
    if result.returncode != 0 or not (result.stdout or "").strip():
        if "logged out" in text or "needslogin" in text or "log in" in text:
            return {"ok": False, "reason": "logged_out", "message": LOGGED_OUT}
        if "stopped" in text:
            return {"ok": False, "reason": "stopped", "message": NOT_RUNNING}
        return {"ok": False, "reason": "error", "message": UNAVAILABLE}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "error", "message": UNAVAILABLE}
    if not isinstance(data, dict):
        return {"ok": False, "reason": "error", "message": UNAVAILABLE}
    state = str(data.get("BackendState") or "")
    if state in ("NeedsLogin", "NeedsMachineAuth", "NoState"):
        return {"ok": False, "reason": "logged_out", "message": LOGGED_OUT}
    if state == "Stopped":
        return {"ok": False, "reason": "stopped", "message": NOT_RUNNING}
    self = data.get("Self") if isinstance(data.get("Self"), dict) else {}
    ips = self.get("TailscaleIPs") or []
    ipv4 = next((ip for ip in ips if isinstance(ip, str) and "." in ip), None)
    dns = str(self.get("DNSName") or "").rstrip(".")
    if not ipv4:
        return {"ok": False, "reason": "logged_out", "message": LOGGED_OUT}
    return {"ok": True, "ip": ipv4, "dns": dns, "state": state, "raw": data}


def identity(*, binary=None, runner=None):
    found = binary or find_binary()
    if not found:
        return {"ok": False, "installed": False, "reason": "missing", "message": MISSING}
    info = _decode_status(run_tailscale(["status", "--json"], binary=found, runner=runner))
    info["installed"] = True
    info["binary"] = found
    return info


def addresses(ident, port):
    out = []
    if ident.get("ip"):
        out.append(f"http://{ident['ip']}:{port}")
    if ident.get("dns"):
        out.append(f"http://{ident['dns']}:{port}")
    return out


def _handler_for(data, port):
    if not isinstance(data, dict):
        return None
    root = data.get("ServeConfig") if isinstance(data.get("ServeConfig"), dict) else data
    tcp = root.get("TCP") if isinstance(root.get("TCP"), dict) else {}
    handler = tcp.get(str(port), tcp.get(port))
    return handler if isinstance(handler, dict) else None


def _forward_of(handler):
    if not isinstance(handler, dict):
        return None
    return handler.get("TCPForward") or handler.get("tcpForward") or handler.get("TCP_Forward")


def _clean_target(forward):
    if not forward:
        return None, None
    text = str(forward).strip()
    if text.lower().startswith("tcp://"):
        text = text[6:]
    if text.startswith("["):
        host, _, port = text[1:].partition("]:")
        host = f"[{host}]"
        return host, port
    host, _, port = text.rpartition(":")
    return host, port


def is_caravan_forward(forward, port):
    host, number = _clean_target(forward)
    return host in LOOPBACKS and number == str(port)


def _funnel_on(data, port):
    if not isinstance(data, dict):
        return False
    root = data.get("ServeConfig") if isinstance(data.get("ServeConfig"), dict) else data
    funnel = root.get("AllowFunnel") or {}
    if not isinstance(funnel, dict):
        return False
    suffix = f":{port}"
    return any(str(key).endswith(suffix) and bool(value) for key, value in funnel.items())


def serve_status(*, port, binary=None, runner=None):
    result = run_tailscale(["serve", "status", "--json"], binary=binary, runner=runner)
    if result.returncode != 0 or not (result.stdout or "").strip():
        # An empty successful status is "nothing served".
        if result.returncode == 0:
            return {"ours": False, "forward": None, "data": {}, "funnel": False}
        raise RemoteError(UNAVAILABLE)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RemoteError(UNAVAILABLE) from e
    if data is None:
        data = {}
    handler = _handler_for(data, port)
    forward = _forward_of(handler)
    return {
        "ours": is_caravan_forward(forward, port),
        "forward": forward,
        "data": data,
        "funnel": _funnel_on(data, port),
        "present": handler is not None,
    }


def enabled_in_config(path=None):
    path = Path(path) if path else config_path()
    if not path.is_file():
        return False
    try:
        import tomllib
        raw = tomllib.loads(path.read_text())
    except (OSError, ValueError, ImportError):
        try:
            text = path.read_text()
        except OSError:
            return False
        return bool(re.search(r'(?ms)^\[remote\][^\n]*\n(?:(?!\[).)*^enabled\s*=\s*true\b', text))
    remote = raw.get("remote") if isinstance(raw, dict) else None
    return bool(isinstance(remote, dict) and remote.get("enabled") is True)


def set_enabled(enabled, path=None):
    path = Path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RemoteError("Settings file is a link; inspect it manually.")
    text = path.read_text() if path.is_file() else ""
    value = "true" if enabled else "false"
    pattern = re.compile(r'(?ms)^(\[remote\][^\n]*\n)(.*?)(?=^\[|\Z)')

    def repl(match):
        body = match.group(2)
        if re.search(r'(?m)^enabled\s*=', body):
            body = re.sub(r'(?m)^enabled\s*=\s*.*$', f"enabled = {value}", body, count=1)
        else:
            body = f"enabled = {value}\n" + body
        return match.group(1) + body

    if pattern.search(text):
        new = pattern.sub(repl, text, count=1)
    else:
        new = text
        if new and not new.endswith("\n"):
            new += "\n"
        if new:
            new += "\n"
        new += f"[remote]\nenabled = {value}\n"
    if new != text:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(new)
        tmp.replace(path)
    return path


def inspect(*, port=None, home=None, path=None, binary=None, runner=None, adopt=True):
    """Live Tailscale state, optionally recording an existing serve entry."""
    port = int(port or web_port(home))
    path = path or config_path(home)
    found = find_binary() if binary is None else binary
    if not found:
        return {
            "enabled": False, "available": False, "installed": False, "logged_in": False,
            "addresses": [], "message": MISSING, "port": port,
        }
    ident = identity(binary=found, runner=runner)
    if not ident.get("ok"):
        return {
            "enabled": False, "available": False, "installed": True,
            "logged_in": False,
            "addresses": [], "message": ident.get("message") or UNAVAILABLE, "port": port,
            "reason": ident.get("reason"),
        }
    # logged_in true only when actually signed in; the branch above already returned.
    try:
        served = serve_status(port=port, binary=found, runner=runner)
    except RemoteError as e:
        return {
            "enabled": False, "available": True, "installed": True, "logged_in": True,
            "addresses": addresses(ident, port), "message": str(e), "port": port,
        }
    if served["funnel"] and served["ours"]:
        message = "This port is shared more widely than Caravan expects. Turn that off in Tailscale first."
        return {
            "enabled": False, "available": True, "installed": True, "logged_in": True,
            "addresses": addresses(ident, port), "message": message, "port": port,
            "funnel": True,
        }
    on = bool(served["ours"])
    if on and adopt:
        set_enabled(True, path)
    elif not on and adopt and enabled_in_config(path) and not served["present"]:
        # Serve is gone; record the truth so Settings matches reality.
        set_enabled(False, path)
    addrs = addresses(ident, port) if on else []
    if on:
        message = "Open at " + " or ".join(addrs) + " from devices on your Tailscale network."
    else:
        message = "Off. Only this Mac can open the page."
    return {
        "enabled": on, "available": True, "installed": True, "logged_in": True,
        "addresses": addrs, "message": message, "port": port,
        "forward": served.get("forward"),
    }


def turn_on(*, port=None, home=None, path=None, binary=None, runner=None):
    port = int(port or web_port(home))
    path = path or config_path(home)
    info = inspect(port=port, home=home, path=path, binary=binary, runner=runner, adopt=True)
    if not info["available"]:
        raise RemoteError(info["message"])
    if info.get("funnel"):
        raise RemoteError(info["message"])
    if info["enabled"]:
        return info
    result = run_tailscale(
        ["serve", "--bg", "--tcp", str(port), f"tcp://127.0.0.1:{port}"],
        binary=binary or find_binary(),
        runner=runner,
    )
    if result.returncode != 0:
        err = " ".join((result.stderr or result.stdout or "Tailscale could not share the page.").split())
        raise RemoteError(err)
    set_enabled(True, path)
    return inspect(port=port, home=home, path=path, binary=binary, runner=runner, adopt=True)


def turn_off(*, port=None, home=None, path=None, binary=None, runner=None, missing_ok=True, quiet=False):
    port = int(port or web_port(home))
    path = path or config_path(home)
    found = binary or find_binary()
    if not found:
        if missing_ok:
            try:
                set_enabled(False, path)
            except (OSError, RemoteError):
                pass
            return {
                "enabled": False, "available": False, "installed": False, "logged_in": False,
                "addresses": [], "message": MISSING, "port": port,
            }
        raise RemoteError(MISSING)
    try:
        served = serve_status(port=port, binary=found, runner=runner)
    except RemoteError:
        served = {"ours": False, "present": False, "funnel": False, "forward": None}
    # Only remove a recognized Caravan loopback forward on this web port.
    if served.get("ours"):
        result = run_tailscale(["serve", f"--tcp={port}", "off"], binary=found, runner=runner)
        if result.returncode != 0 and not missing_ok:
            err = " ".join((result.stderr or result.stdout or "Tailscale could not stop sharing.").split())
            raise RemoteError(err)
    try:
        set_enabled(False, path)
    except (OSError, RemoteError):
        if not missing_ok:
            raise
    info = inspect(port=port, home=home, path=path, binary=found, runner=runner, adopt=False)
    info["enabled"] = False
    info["addresses"] = []
    info["message"] = "Open from other devices is off."
    return info


def status_line(info):
    if info.get("enabled") and info.get("addresses"):
        return "Open from other devices is on: " + " and ".join(info["addresses"])
    if not info.get("available") or info.get("funnel"):
        return info.get("message") or MISSING
    return "Open from other devices is off."


def doctor_line(*, port=None, home=None, path=None, binary=None, runner=None):
    try:
        info = inspect(port=port, home=home, path=path, binary=binary, runner=runner, adopt=False)
    except RemoteError as e:
        return f"Open from other devices: {e}"
    if info.get("enabled") and info.get("addresses"):
        return "Open from other devices is on at " + " and ".join(info["addresses"]) + "."
    if not info.get("available") or info.get("funnel"):
        return f"Open from other devices: {info.get('message') or MISSING}"
    return "Open from other devices is off."


def can_ask(tty_path="/dev/tty"):
    try:
        fd = os.open(tty_path, os.O_RDWR)
        os.close(fd)
        return True
    except OSError:
        return False


def maybe_prompt(*, port=8190, home=None, path=None, tty_path="/dev/tty",
                 infile=None, outfile=None, ask=None, binary=None, runner=None):
    """Ask the one optional install question. Skip silently unless ready."""
    if ask is None:
        ask = can_ask(tty_path)
    if not ask:
        return "skipped"
    ident = identity(binary=binary, runner=runner)
    if not ident.get("ok"):
        return "skipped"
    info = inspect(port=port, home=home, path=path, binary=ident.get("binary") or binary,
                   runner=runner, adopt=True)
    if info.get("enabled"):
        return "already-on"
    out = outfile or sys.stdout
    out.write(QUESTION)
    out.flush()
    close = False
    stream = infile
    if stream is None:
        try:
            stream = open(tty_path, "r")
            close = True
        except OSError:
            return "skipped"
    try:
        answer = (stream.readline() or "").strip().lower()
    finally:
        if close:
            stream.close()
    if answer not in ("y", "yes"):
        return "no"
    info = turn_on(port=port, home=home, path=path, binary=ident.get("binary") or binary, runner=runner)
    out.write(status_line(info) + "\n")
    out.flush()
    return "on"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Share this Mac's Caravan page with your other Tailscale devices.")
    parser.add_argument("action", nargs="?", default="status",
                        choices=("on", "off", "status", "maybe-prompt"))
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--name", default="web")
    parser.add_argument("--home", default=None)
    args = parser.parse_args(argv)
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("port must be 1–65535")
    port = args.port or web_port(args.home, name=args.name)
    try:
        if args.action == "maybe-prompt":
            maybe_prompt(port=port, home=args.home)
            return 0
        if args.action == "on":
            info = turn_on(port=port, home=args.home)
            print(status_line(info))
            return 0
        if args.action == "off":
            info = turn_off(port=port, home=args.home)
            print(status_line(info))
            return 0
        info = inspect(port=port, home=args.home)
        print(status_line(info))
        return 0
    except RemoteError as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
