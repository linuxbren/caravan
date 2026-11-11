#!/usr/bin/env python3
"""Small per-user Mac control command. Never manages unverified jobs."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import caravan_service as service
import service_config as SC


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "doctor", "update", "uninstall", "add-mini", "open"))
    parser.add_argument("--name", default="web", help="one owned service; default web")
    args = parser.parse_args(argv)
    try:
        if args.action == "doctor":
            from caravan_doctor import main as doctor
            try:
                port = service.stored("web", Path.home())["port"]
            except (OSError, ValueError):
                port = 8190
            return doctor(["--port", str(port)])
        if args.action == "add-mini":
            print("On each extra Apple Silicon Mac, run:\n(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/install | bash -s -- --role worker)\nThen enable Remote Login and configure trusted SSH from the lead.\nOpen " + str(ROOT / "INSTALL.md") + " → Add Minis. Discovery is read-only, not automatic pairing.")
            return 0
        if args.action == "update":
            if not (ROOT / ".caravan-package").exists():
                raise ValueError("This is a source checkout. Update it with git pull --ff-only, then rerun scripts/install.sh with the same options. No checkout changed.")
            role_file = ROOT / ".caravan-role"
            role = role_file.read_text().strip() if role_file.exists() else "lead"
            if role not in ("lead", "worker"): raise ValueError("Unknown saved installation role; no update attempted")
            # Fetch to a file: a failed HTTP request can never run a partial shell script.
            with urllib.request.urlopen("https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/install", timeout=30) as response:
                data = response.read()
            with tempfile.NamedTemporaryFile(suffix=".sh") as script:
                script.write(data); script.flush()
                cmd = ["bash", script.name, "--update", "--role", role, "--no-start"]
                if role == "lead":
                    plan = service.stored(args.name, Path.home())
                    cmd += ["--port", str(plan["port"]), "--name", args.name]
                result = subprocess.run(cmd)
            if result.returncode == 0: print("Updated; run caravan start when ready. Old source backup kept; models/settings unchanged.")
            return result.returncode
        if args.action == "status":
            return service.main(["status"])
        plan = service.stored(args.name, Path.home())
        service.assert_owned(plan, require=True)
        if args.action == "open":
            if plan["kind"] != "web": raise ValueError("Choose the web service to open the browser")
            return subprocess.run(["open", f"http://127.0.0.1:{plan['port']}/"]).returncode
        if args.action == "uninstall":
            print("Removing only this service. Models, settings, runtime, source and command are kept. No model deletion is offered.")
            return service.main(["uninstall", "--name", args.name])
        service.check_platform(); service.gui_ready()
        target = service.domain() + "/" + plan["label"]
        loaded = service.run_launchctl(["print", target]).returncode == 0
        if args.action == "stop":
            if loaded:
                result = service.run_launchctl(["bootout", target])
                if result.returncode: raise ValueError(result.stderr or "launchd could not stop the service")
            print("Web service stopped until next login or caravan start. Model workers stay running; use Unload in the UI first to free their memory.")
            return 0
        if not loaded:
            service.ensure_port_free(plan)
            result = service.run_launchctl(["bootstrap", service.domain(), str(SC.paths(plan)["plist"])])
            if result.returncode: raise ValueError(result.stderr or "launchd could not start the service")
        print("Service started (or already running). Use caravan open to open the browser.")
    except (OSError, ValueError, KeyError) as error:
        print(f"[Caravan] {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__": sys.exit(main())
