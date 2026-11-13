#!/usr/bin/env python3
"""Small per-user Mac control command. Never manages unverified jobs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import caravan_service as service
import service_config as SC


def simple_status(name="web"):
    try:
        plan = service.stored(name, Path.home())
        service.assert_owned(plan, require=True)
    except (OSError, ValueError, KeyError):
        print("Caravan is not running: setup is missing or needs repair. Run the install command again.")
        return 1
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{plan['port']}/api/status", timeout=3) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not isinstance(data.get('worker'), dict):
            raise ValueError("Unexpected status response")
    except (OSError, ValueError):
        print("Caravan is not running: its browser service is stopped or not responding. Run caravan start; if that fails, run caravan doctor.")
        return 1
    worker = data['worker']
    if worker.get('error'):
        problem = ' '.join(str(worker['error']).split())
        print(f"Caravan is not running: {problem.rstrip('.')}. Open Caravan and load the model again; run caravan doctor if it fails.")
        return 1
    print("Caravan is running")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "remote":
        from caravan_remote import main as remote
        return remote(argv[1:])
    if argv and argv[0] == "lan":
        from caravan_lan import main as lan
        return lan(argv[1:])
    if argv and argv[0] == "bench":
        from caravan_bench import main as bench
        return bench(argv[1:])
    if argv and argv[0] == "models":
        from caravan_models import main as models
        return models(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "doctor", "update", "uninstall", "add-mini", "open", "remote", "lan", "bench", "models"))
    parser.add_argument("--name", default="web", help="one owned service; default web")
    parser.add_argument("--full", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--everything", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--yes", action="store_true", help="with uninstall: confirm removal of all Caravan data")
    parser.add_argument("--check", action="store_true", help="with update: only check for a newer version, do not install it")
    args = parser.parse_args(argv)
    try:
        if args.action == "remote":
            from caravan_remote import main as remote
            return remote([])
        if args.action == "lan":
            from caravan_lan import main as lan
            return lan([])
        if args.action == "doctor":
            from caravan_doctor import main as doctor
            try:
                port = service.stored("web", Path.home())["port"]
            except (OSError, ValueError):
                port = 8190
            return doctor(["--port", str(port)])
        if args.action == "add-mini":
            plan = service.stored(args.name, Path.home())
            service.assert_owned(plan, require=True)
            from caravan_pairing import launch_file
            print("On the new Mac, run the same install command. In Topology → Add a Mac on the new Mac, turn on Remote Login and show a code. Here, choose Add this Mac and enter that code. No manual SSH or settings-file edits.")
            return subprocess.run(["open", str(launch_file(plan["port"]))]).returncode
        if args.action == "update":
            if args.check:
                from caravan_update_check import cli_check
                return cli_check(ROOT, name=args.name)
            if not (ROOT / ".caravan-package").exists():
                raise ValueError("This is a source checkout. Update it with git pull --ff-only, then rerun scripts/install.sh with the same options. No checkout changed.")
            role_file = ROOT / ".caravan-role"
            role = role_file.read_text().strip() if role_file.exists() else "lead"
            if role not in ("lead", "worker"): raise ValueError("Unknown saved installation role; no update attempted")
            # Fetch to a file: a failed HTTP request can never run a partial shell script.
            with urllib.request.urlopen("https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/install?channel=" + str(time.time_ns()), timeout=30) as response:
                data = response.read()
            with tempfile.NamedTemporaryFile(suffix=".sh") as script:
                script.write(data); script.flush()
                cmd = ["bash", script.name, "--update", "--role", role]
                if role in ("lead", "worker"):
                    plan = service.stored(args.name, Path.home())
                    cmd += ["--port", str(plan["port"]), "--name", args.name]
                result = subprocess.run(cmd)
            return result.returncode
        if args.action == "status":
            return simple_status(args.name)
        if args.action == "uninstall":
            from caravan_uninstall import uninstall
            print(uninstall(yes=args.yes))
            return 0
        plan = service.stored(args.name, Path.home())
        service.assert_owned(plan, require=True)
        if args.action == "open":
            if plan["kind"] != "web": raise ValueError("Choose the web service to open the browser")
            from caravan_pairing import launch_file
            return subprocess.run(["open", str(launch_file(plan["port"], next_home=True))]).returncode
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
            print("Caravan started. Run caravan open to open it in your browser.")
        else:
            print("Caravan is running. Run caravan open to open it in your browser.")
    except (OSError, ValueError, KeyError) as error:
        print(f"[Caravan] {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__": sys.exit(main())
