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
from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text)


def simple_status(name="web"):
    try:
        plan = service.stored(name, Path.home())
        service.assert_owned(plan, require=True)
    except (OSError, ValueError, KeyError):
        print(T("cli.caravan.caravan_is_not_running_setup_is"))
        return 1
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{plan['port']}/api/status", timeout=3) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not isinstance(data.get('worker'), dict):
            raise ValueError(T("cli.caravan.unexpected_status_response"))
    except (OSError, ValueError):
        print(T("cli.caravan.caravan_is_not_running_its_browser"))
        return 1
    worker = data['worker']
    if worker.get('error'):
        problem = ' '.join(str(worker['error']).split())
        print(T("cli.caravan.caravan_is_not_running_problem_open", problem=problem.rstrip('.')))
        return 1
    label = _version_label()
    print(T("cli.caravan.caravan_label_is_running", label=label) if label else T("cli.caravan.caravan_is_running"))
    for line in link_lines():
        print(line)
    return 0


def _version_label():
    """'v0.9.4' from the installed VERSION file ('' when unknown)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caravan_version as CV
        return CV.info(ROOT)["label"]
    except Exception:  # noqa: BLE001 - status must never fail on this
        return ""


def link_lines(home=None):
    """Link-order fix: which link reaches each other Mac (from the last check)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "proxy"))
        import peer_route as PR
        routes = PR.load_all()
    except Exception:  # noqa: BLE001 - status must never fail on this
        return []
    out = []
    for target, route in sorted(routes.items()):
        if not isinstance(route, dict):
            continue
        name = route.get("label") or target
        out.append(T("cli.caravan.link_to_name_describe", name=name, describe=PR.describe(route)))
        if route.get("warning"):
            out.append(f"  warning: {route['warning']}")
    return out



def _update_other_macs(home=None, out=None):
    """Ask every other known Mac to update. This Mac is updated by the caller."""
    home = Path(home) if home is not None else Path.home()
    out = sys.stdout if out is None else out
    from caravan_update_peers import update_other_macs, load_nodes
    peers = load_nodes(home)
    if peers:
        print(T("cli.caravan.updating_the_other_macs_first_then"), file=out, flush=True)
        update_other_macs(home, peers, out=out)
    return peers


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
    if argv and argv[0] == "jobs":
        from caravan_jobs import main as jobs
        return jobs(argv[1:])
    if argv and argv[0] == "models":
        from caravan_models import main as models
        return models(argv[1:])
    if argv and argv[0] in ("--version", "-V", "version"):
        import caravan_version as CV
        print(CV.text(ROOT))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "doctor", "update", "uninstall", "add-mini", "open", "remote", "lan", "bench", "models", "jobs"))
    parser.add_argument("--name", default="web", help=T("cli.caravan.one_owned_service_default_web"))
    parser.add_argument("--full", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--everything", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--yes", action="store_true", help=T("cli.caravan.with_uninstall_confirm_removal_of_all"))
    parser.add_argument("--check", action="store_true", help=T("cli.caravan.with_update_only_check_for_a"))
    parser.add_argument("--local-only", action="store_true", help=T("cli.caravan.with_update_only_this_mac_do"))
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
            print(T("cli.caravan.on_the_new_mac_run_the"))
            return subprocess.run(["open", str(launch_file(plan["port"]))]).returncode
        if args.action == "update":
            if args.check:
                from caravan_update_check import cli_check
                return cli_check(ROOT, name=args.name)
            if not (ROOT / ".caravan-package").exists():
                raise ValueError(T("cli.caravan.this_is_a_source_checkout_update"))
            role_file = ROOT / ".caravan-role"
            role = role_file.read_text().strip() if role_file.exists() else "lead"
            if role not in ("lead", "worker"): raise ValueError(T("cli.caravan.unknown_saved_installation_role_no_update"))
            local_only = bool(args.local_only) or os.environ.get("CARAVAN_UPDATE_LOCAL", "").strip() in ("1", "true", "yes")
            if not local_only:
                # Other Macs first, over the existing SSH link. A failure there
                # is printed and does not stop this Mac from updating.
                try:
                    _update_other_macs(Path.home(), out=sys.stdout)
                except Exception as peer_error:
                    print(T("cli.caravan.couldnt_update_the_other_macs_peer", peer_error=peer_error), flush=True)
            # Fetch to a file: a failed HTTP request can never run a partial shell script.
            from caravan_update_check import INSTALL_URL
            with urllib.request.urlopen(INSTALL_URL + "?channel=" + str(time.time_ns()), timeout=30) as response:
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
            if plan["kind"] != "web": raise ValueError(T("cli.caravan.choose_the_web_service_to_open"))
            from caravan_pairing import launch_file
            return subprocess.run(["open", str(launch_file(plan["port"], next_home=True))]).returncode
        service.check_platform(); service.gui_ready()
        target = service.domain() + "/" + plan["label"]
        loaded = service.run_launchctl(["print", target]).returncode == 0
        if args.action == "stop":
            if loaded:
                result = service.run_launchctl(["bootout", target])
                if result.returncode: raise ValueError(result.stderr or T("cli.caravan.launchd_could_not_stop_the_service"))
            print(T("cli.caravan.web_service_stopped_until_next_login"))
            return 0
        if not loaded:
            service.ensure_port_free(plan)
            result = service.run_launchctl(["bootstrap", service.domain(), str(SC.paths(plan)["plist"])])
            if result.returncode: raise ValueError(result.stderr or T("cli.caravan.launchd_could_not_start_the_service"))
            print(T("cli.caravan.caravan_started_run_caravan_open_to"))
        else:
            print(T("cli.caravan.caravan_is_running_run_caravan_open"))
    except (OSError, ValueError, KeyError) as error:
        print(T("cli.caravan.caravan_error", error=error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__": sys.exit(main())
