#!/usr/bin/env python3
"""Read-only, stdlib health checks. Never starts/stops services or downloads files."""
import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def checks(home=None, port=8190):
    home = Path(home or Path.home())
    rows = []
    def add(level, message): rows.append((level, message))
    mac = platform.system() == "Darwin"
    add("OK" if mac else "ERROR", "macOS required (Apple Silicon, macOS 14+).")
    add("OK" if platform.machine() == "arm64" else "ERROR", "Native Apple Silicon required; disable Rosetta for Terminal/Python.")
    if mac:
        version = platform.mac_ver()[0]
        add("OK" if version and int(version.split('.')[0]) >= 14 else "ERROR", f"macOS {version or 'unknown'}; upgrade to 14+ if older.")
        memory = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
        add("ERROR" if memory < 8*2**30 else "WARN" if memory < 16*2**30 else "OK", "Caravan checks what fits. More memory or additional Macs lets you run bigger models.")
    add("ERROR" if os.getuid() == 0 else "OK", "Use your normal Mac account, without sudo.")
    free = shutil.disk_usage(home).free
    add("OK" if free >= 8*2**30 else "ERROR", f"Free disk: {free/2**30:.1f} GB; setup needs 8 GB, models need extra.")
    add("OK" if os.access(home, os.W_OK) else "ERROR", "Home folder must be writable.")
    py = home / ".caravan/venvs/mlx/bin/python"
    if py.exists():
        result = subprocess.run([str(py), "-c", "import mlx.core,mlx_lm,huggingface_hub,spake2,cryptography"], capture_output=True, text=True)
        add("ERROR" if result.returncode else "OK", "MLX environment " + ("needs repair: rerun setup. " + result.stderr.strip()[-300:] if result.returncode else "imports correctly."))
    else:
        add("WARN", "MLX environment not installed yet. The Mac bootstrap supplies Python and MLX.")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            add("WARN", f"Port {port} is in use (possibly Caravan). Do not kill it; use caravan status or choose another setup --port.")
    except OSError:
        add("OK", f"Port {port} is available (or the web service is stopped).")
    add("INFO", "Login is required after reboot. FileVault must be unlocked first; setup does not change security or auto-login.")
    try:
        with socket.create_connection(("127.0.0.1", 8197), timeout=1):
            add("INFO", "Mac pairing address is in use (possibly Caravan). If Add Macs fails, check for another instance; do not kill unknown apps.")
    except OSError:
        add("INFO", "Mac pairing service is stopped or not installed yet. Start Caravan to use Add Macs.")
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=.5):
            add("INFO", "Remote Login is reachable. Add Macs verifies its identity with a one-use code.")
    except OSError:
        add("INFO", "To add this Mac to another, open Add Macs → Open the right Mac setting and turn on Remote Login for this account.")
    add("INFO", "Models, optional runtimes and trusted Mac connections are separate setup steps. See INSTALL.md.")
    add("INFO", "No network checks performed. Downloads require GitHub, PyPI and model-host access; check Wi-Fi/firewall if setup fails.")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8190)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535: parser.error("port must be 1–65535")
    rows = checks(port=args.port)
    for level, message in rows: print(f"[{level}] {message}")
    return int(any(level == "ERROR" for level, _ in rows))


if __name__ == "__main__": sys.exit(main())
