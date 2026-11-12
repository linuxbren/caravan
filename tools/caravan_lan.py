#!/usr/bin/env python3
"""Opt-in local-network access to this Mac's Caravan page.

Off by default. When off, the page stays only on this Mac. When on,
devices on the same network can open it. Anyone on that network can
use Caravan, and there is no login. This never opens the page to the
public internet.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

WARNING = "Anyone on the same network can use Caravan, and there is no login."
QUESTION = "Open Caravan on your local network? (y/N) "
OFF_MESSAGE = "Open on the local network is off."
ON_PREFIX = "Open on the local network at "


class LanError(Exception):
    """A plain-language failure the user can act on."""


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
        return bool(re.search(r'(?ms)^\[lan\][^\n]*\n(?:(?!\[).)*^enabled\s*=\s*true\b', text))
    lan = raw.get("lan") if isinstance(raw, dict) else None
    return bool(isinstance(lan, dict) and lan.get("enabled") is True)


def set_enabled(enabled, path=None):
    path = Path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise LanError("Settings file is a link; inspect it manually.")
    text = path.read_text() if path.is_file() else ""
    value = "true" if enabled else "false"
    pattern = re.compile(r'(?ms)^(\[lan\][^\n]*\n)(.*?)(?=^\[|\Z)')

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
        new += f"[lan]\nenabled = {value}\n"
    if new != text:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(new)
        tmp.replace(path)
    return path


def _octets(ip):
    if not ip or not isinstance(ip, str):
        return None
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 or n > 255 for n in nums):
        return None
    return nums


def _is_loopback(ip):
    n = _octets(ip)
    return bool(n) and n[0] == 127


def _is_link_local(ip):
    n = _octets(ip)
    return bool(n) and n[0] == 169 and n[1] == 254


def _is_cgnat(ip):
    """Tailscale and other carrier-grade NAT use 100.64.0.0/10."""
    n = _octets(ip)
    return bool(n) and n[0] == 100 and 64 <= n[1] <= 127


def _is_rfc1918(ip):
    n = _octets(ip)
    if not n:
        return False
    if n[0] == 10:
        return True
    if n[0] == 192 and n[1] == 168:
        return True
    if n[0] == 172 and 16 <= n[1] <= 31:
        return True
    return False


def _ok_ipv4(ip):
    """True for a private IPv4 address other devices on this network may use.

    Excludes loopback, wildcard, broadcast, link-local (169.254), and
    100.64/10 (Tailscale and other carrier-grade NAT). Those last two
    would either be unreachable from a phone on Wi-Fi or collide with
    Tailscale remote access.
    """
    if not ip or ip in ("0.0.0.0", "255.255.255.255"):
        return False
    if _is_loopback(ip) or _is_link_local(ip) or _is_cgnat(ip):
        return False
    return _is_rfc1918(ip)


def _ips_from_interfaces():
    """Every IPv4 address currently assigned to an interface."""
    found = []

    def add(ip):
        if _ok_ipv4(ip) and ip not in found:
            found.append(ip)

    import subprocess
    commands = (
        ("ifconfig", "-a"),
        ("ip", "-4", "-o", "addr", "show"),
    )
    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=2)
        except (OSError, subprocess.SubprocessError):
            continue
        for m in re.finditer(r"\binet(?:\s+addr:|/)\s*(\d+\.\d+\.\d+\.\d+)|\binet\s+(\d+\.\d+\.\d+\.\d+)", out):
            add(m.group(1) or m.group(2))
        if found:
            return found
    return found


def lan_ips():
    """IPv4 addresses on this Mac that other devices on the same network may use."""
    found = []

    def add(ip):
        if _ok_ipv4(ip) and ip not in found:
            found.append(ip)

    for ip in _ips_from_interfaces():
        add(ip)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("1.1.1.1", 80))
            add(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            add(info[4][0])
    except OSError:
        pass
    return found


def addresses(port):
    return [f"http://{ip}:{int(port)}" for ip in lan_ips()]


def listen_host(requested=None, path=None):
    """Primary host the page listens on.

    When local-network access is on, this is always 127.0.0.1 so Tailscale
    serve (which forwards to 127.0.0.1) and the open page stay up. LAN
    addresses are extra sockets from listen_hosts(), never 0.0.0.0 (which
    would also claim the Tailscale address and fail with 'address already
    in use').
    """
    if enabled_in_config(path):
        return "127.0.0.1"
    if requested:
        return requested
    return "127.0.0.1"


def listen_hosts(requested=None, path=None):
    """Every address the page should listen on, given the saved choice.

    Local-network access and Tailscale remote access can both be on: the
    page stays on 127.0.0.1 (for this Mac and for Tailscale) and also
    listens on each private LAN address. It never binds 0.0.0.0 while
    local-network access is on.
    """
    if enabled_in_config(path):
        hosts = ["127.0.0.1"]
        for ip in lan_ips():
            if ip not in hosts:
                hosts.append(ip)
        return hosts
    if requested:
        return [requested]
    return ["127.0.0.1"]


def inspect(*, port=None, home=None, path=None):
    port = int(port or web_port(home))
    path = path or config_path(home)
    on = enabled_in_config(path)
    addrs = addresses(port) if on else []
    binds = listen_hosts(path=path)
    if on and addrs:
        message = "Open at " + " or ".join(addrs) + " from a device on the same network. " + WARNING
    elif on:
        message = (
            "On. The page is open on the local network, but this Mac's "
            "network address could not be found right now. " + WARNING
        )
    else:
        message = "Off. The page is not open on the local network."
    return {
        "enabled": on,
        "addresses": addrs,
        "message": message,
        "warning": WARNING,
        "port": port,
        "bind": listen_host(path=path),
        "binds": binds,
    }


def turn_on(*, port=None, home=None, path=None):
    path = path or config_path(home)
    port = int(port or web_port(home))
    set_enabled(True, path)
    return inspect(port=port, home=home, path=path)


def turn_off(*, port=None, home=None, path=None, missing_ok=True):
    path = path or config_path(home)
    port = int(port or web_port(home))
    try:
        set_enabled(False, path)
    except (OSError, LanError):
        if not missing_ok:
            raise
    info = inspect(port=port, home=home, path=path)
    info["enabled"] = False
    info["addresses"] = []
    info["bind"] = "127.0.0.1"
    info["binds"] = ["127.0.0.1"]
    info["message"] = OFF_MESSAGE.replace(" is off.", " is off.")  # stable
    info["message"] = "Off. The page is not open on the local network."
    return info


def status_line(info):
    if info.get("enabled") and info.get("addresses"):
        return ON_PREFIX + " and ".join(info["addresses"])
    if info.get("enabled"):
        return "Open on the local network is on. " + (info.get("message") or WARNING)
    return OFF_MESSAGE


def doctor_line(*, port=None, home=None, path=None):
    try:
        info = inspect(port=port, home=home, path=path)
    except LanError as e:
        return f"Open on the local network: {e}"
    if info.get("enabled") and info.get("addresses"):
        return "Open on the local network is on at " + " and ".join(info["addresses"]) + ". " + WARNING
    if info.get("enabled"):
        return "Open on the local network is on. " + WARNING
    return OFF_MESSAGE


def can_ask(tty_path="/dev/tty"):
    try:
        fd = os.open(tty_path, os.O_RDWR)
        os.close(fd)
        return True
    except OSError:
        return False


def maybe_prompt(*, port=8190, home=None, path=None, tty_path="/dev/tty",
                 infile=None, outfile=None, ask=None):
    """Ask the optional install question. Default is No. Skip if no terminal."""
    if ask is None:
        ask = can_ask(tty_path)
    if not ask:
        return "skipped"
    path = path or config_path(home)
    if enabled_in_config(path):
        return "already-on"
    out = outfile or sys.stdout
    out.write(WARNING + "\n")
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
    info = turn_on(port=port, home=home, path=path)
    out.write(status_line(info) + "\n")
    out.flush()
    return "on"


RESTART_MESSAGE = "The page will be back in a few seconds. The model stays loaded."


def notify_running_web(*, port, enabled, timeout=3):
    """Tell a running page to apply the new listen address. Returns the JSON body or None."""
    body = json.dumps({"enabled": bool(enabled)}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}/api/lan",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Open this Mac's Caravan page on your local network. "
                    + WARNING)
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
            applied = notify_running_web(port=port, enabled=True)
            if applied and applied.get("restarting"):
                info["restarting"] = True
                info["message"] = applied.get("message") or RESTART_MESSAGE
                print(status_line(info))
                print(info["message"])
            else:
                print(status_line(info))
            return 0
        if args.action == "off":
            info = turn_off(port=port, home=args.home)
            applied = notify_running_web(port=port, enabled=False)
            if applied and applied.get("restarting"):
                print(status_line(info))
                print(applied.get("message") or RESTART_MESSAGE)
            else:
                print(status_line(info))
            return 0
        info = inspect(port=port, home=args.home)
        print(status_line(info))
        return 0
    except LanError as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
