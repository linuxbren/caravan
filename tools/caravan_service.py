#!/usr/bin/env python3
"""Install/uninstall/status/restart Caravan's own user LaunchAgents.

No sudo, LaunchDaemons, model downloads, remote SSH commands or plist templates
with somebody else's home directory. --dry-run is portable and writes nothing.
"""
from __future__ import annotations
import argparse
import json
import os
import platform
import plistlib
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agent"))
import service_config as SC


def run_launchctl(args):
    return subprocess.run(["/bin/launchctl"]+list(args), capture_output=True, text=True)


def domain():
    return f"gui/{os.getuid()}"


def check_platform():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Real service changes need native Apple Silicon macOS; --dry-run works here")
    if int((platform.mac_ver()[0] or "0").split(".")[0]) < 14:
        raise ValueError("macOS 14 or newer is required")
    if os.getuid() == 0:
        raise ValueError("Use your normal logged-in Mac user, not sudo/root")


def gui_ready(run=run_launchctl):
    result = run(["print",domain()])
    if result.returncode:
        raise ValueError("No GUI login session is available. Log in to this Mac first, or use install --no-start")


def validate_files(plan):
    root = Path(plan["repo"])
    script = root/("proxy/web_server.py" if plan["kind"] == "web" else "agent/caravan_agent.py")
    if not script.is_file() or not Path(plan["python"]).is_file():
        raise ValueError("Repository or Python is missing; run scripts/install.sh first")
    if plan["kind"] == "web":
        return
    d = Path(plan["model"])
    from mlx_split import check_local_shards, safetensors_expected_size
    from mlx_split_fetch import n_layers_of
    cfg = json.loads((d/"config.json").read_text())
    if not any((d/name).is_file() for name in ("tokenizer.json","tokenizer.model")):
        raise ValueError("This worker's model folder needs its own tokenizer")
    if (d/"model.safetensors.index.json").is_file():
        counts = plan.get("counts") or [n_layers_of(cfg)]
        check_local_shards(d,"head" if plan["role"] in ("lead","single") else "front",
                           counts=counts, stage_index=plan.get("stage_index",0))
    elif plan["role"] == "single":
        files = list(d.glob("*.safetensors"))
        if not files or any(safetensors_expected_size(p) != p.stat().st_size for p in files):
            raise ValueError("Single-Mini model has missing or incomplete safetensors weights")
    else:
        raise ValueError("Split auto-start requires model.safetensors.index.json")


def ensure_port_free(plan):
    if plan["kind"] == "worker" and plan["role"] == "packer":
        from mlx_split import _hostport
        from service_endpoints import resolve
        host, number = _hostport(resolve(plan["listen"]))
    else:
        host, number = plan["host"], plan["port"]
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as sock:
        # Match the real servers: TIME_WAIT from our last child is not a live
        # listener. This does not enable SO_REUSEPORT or bypass another listener.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host,number))
        except OSError as e:
            raise ValueError(f"Port {number} is already busy or {host} is not a local interface. Nothing was stopped: {e}") from None


def assert_owned(plan, require=False, *, staged=None):
    p = SC.paths(plan, staged=staged)
    for key in ("config","plist"):
        if not p[key].exists():
            if require:
                raise ValueError(f"Owned {key} is missing; refusing to act on an unverified job")
            continue
        if key == "config":
            value = SC.load(p[key])
            expected = plan
        else:
            value = plistlib.loads(p[key].read_bytes())
            expected = SC.render(plan, staged=staged)
        if value != expected:
            raise ValueError("Service definition differs. Uninstall the existing owned job before changing its plan; nothing was overwritten")


def install(plan, *, start=True, dry_run=False, stage_login=False, run=run_launchctl):
    if stage_login and start:
        raise ValueError("--stage-login requires --no-start; it must not take over running workers")
    staged = True if stage_login else None
    paths = SC.paths(plan, staged=staged)
    if stage_login and SC.paths(plan, staged=False)["config"].exists():
        raise ValueError("This service already has a normal installed plan; nothing was moved or overwritten")
    if dry_run:
        print(json.dumps({"preview_only":True,"plan":plan,"plist":SC.render(plan, staged=staged),
                          "files":{k:str(v) for k,v in paths.items()},"start":start},indent=2))
        return
    check_platform()
    assert_owned(plan, staged=staged)
    validate_files(plan)
    target = domain()+"/"+plan["label"]
    if start:
        gui_ready(run)
        loaded = run(["print",target]).returncode == 0
        if loaded:
            # A job with our label but no matching on-disk files is not ours to adopt.
            assert_owned(plan,require=True)
            print(f"[Caravan] {plan['name']} is already installed and loaded; no restart needed.")
            return
        ensure_port_free(plan)
    # Check for another installed worker service reserving the same endpoint.
    root = Path(plan["home"])/".caravan/services"
    for path in SC.plan_files(plan["home"]):
        other = SC.load(path)
        if other["name"] == plan["name"]:
            continue
        def address(p):
            return int(p["listen"].rsplit(":",1)[1]) if p.get("role") == "packer" else p["port"]
        if (address(other) == address(plan) or (other["kind"] == plan["kind"] == "worker"
                and other["role"] in ("single","lead") and plan["role"] in ("single","lead"))):
            raise ValueError(f"Another owned service ({other['name']}) reserves this port; no job was changed")
    for key in ("config","plist","log","runtime"):
        paths[key].parent.mkdir(parents=True,exist_ok=True)
    # Refuse to replace unrelated files. Repeated identical installs are safe.
    paths["config"].write_text(json.dumps(plan,indent=2)+"\n")
    paths["config"].chmod(0o600)
    paths["plist"].write_bytes(plistlib.dumps(SC.render(plan, staged=staged)))
    if start:
        result = run(["bootstrap",domain(),str(paths["plist"])])
        if result.returncode:
            raise ValueError(f"launchd could not start {plan['name']}: {(result.stderr or result.stdout).strip()}. Files kept; inspect status, then rerun install")
    print(f"[Caravan] {plan['name']} {'installed and started' if start else 'installed, not started'}. It starts at user login.")
    print(f"[Caravan] Log: {paths['log']}")
    if stage_login:
        print("[Caravan] Staged for next user login; current workers and web control were not adopted or restarted.")


def stored(name,home):
    if not name or not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",name):
        raise ValueError("choose an installed service --name")
    root = Path(home)/".caravan/services"
    paths = [p for p in (root/f"{name}.json",root/"login"/f"{name}.json") if p.exists()]
    if len(paths) != 1:
        raise ValueError("Service plan missing or ambiguous; refusing to act")
    path = paths[0]
    plan = SC.load(path)
    if SC.paths(plan)["config"].resolve() != path.resolve():
        raise ValueError("Service plan points outside this user's managed folder; refusing to act")
    return plan


def control(action,plan,*,dry_run=False,run=run_launchctl):
    assert_owned(plan,require=True)
    target = domain()+"/"+plan["label"]
    if dry_run:
        print(f"[Caravan] Would {action} only {target}; models, caches, dependencies and repository are kept.")
        return
    check_platform()
    gui_ready(run)
    loaded = run(["print",target])
    if action == "status":
        print(f"[Caravan] {plan['name']}: {'loaded' if loaded.returncode == 0 else 'installed, not loaded'}")
        if loaded.returncode == 0:
            print(loaded.stdout.strip())
        print(f"[Caravan] Log: {SC.paths(plan)['log']}")
        if SC.paths(plan)["config"].parent.name == "login" and loaded.returncode != 0:
            print("[Caravan] Staged for next login; current workers remain unmanaged by this job.")
        return
    if action == "restart":
        if loaded.returncode != 0:
            ensure_port_free(plan)
            result = run(["bootstrap",domain(),str(SC.paths(plan)["plist"])])
        else:
            result = run(["bootout",target])
            if result.returncode == 0:
                result = run(["bootstrap",domain(),str(SC.paths(plan)["plist"])])
        if result.returncode:
            raise ValueError((result.stderr or result.stdout).strip() or "launchd restart failed")
        print(f"[Caravan] Restarted only {plan['name']}.")
        return
    if loaded.returncode == 0:
        result = run(["bootout",target])
        if result.returncode:
            raise ValueError((result.stderr or result.stdout).strip() or "launchd unload failed; files kept")
    p = SC.paths(plan)
    p["plist"].unlink()
    p["config"].unlink()
    print(f"[Caravan] Uninstalled only {plan['name']}. Models, caches, logs, dependencies and repository are kept.")
    if plan["kind"] == "web":
        print("[Caravan] Web-owned workers were kept running (CARAVAN_WEB_KEEP_WORKERS=1).")


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action",choices=("install","uninstall","status","restart"))
    ap.add_argument("--kind",choices=("web","worker"),default="web")
    ap.add_argument("--name")
    ap.add_argument("--repo",default=str(ROOT))
    ap.add_argument("--python")
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,help="web or worker HTTP port")
    ap.add_argument("--lead-port",type=int,default=8194)
    ap.add_argument("--model")
    ap.add_argument("--counts")
    ap.add_argument("--stage-index",type=int)
    ap.add_argument("--listen")
    ap.add_argument("--upstream")
    ap.add_argument("--peer")
    ap.add_argument("--no-start",action="store_true")
    ap.add_argument("--stage-login",action="store_true",help="with --no-start, stage future-login plans without taking over current workers")
    ap.add_argument("--dry-run",action="store_true")
    return ap


def main(argv=None):
    ap = parser(); args = ap.parse_args(argv)
    try:
        if args.action == "install":
            p = SC.make_plan(kind=args.kind,name=args.name,repo=args.repo,python=args.python,host=args.host,
                             web_port=args.port if args.port is not None else 8190,
                             lead_port=(args.port if args.port is not None else args.lead_port) if args.kind == "worker" else args.lead_port,
                             model=args.model,counts=args.counts,stage_index=args.stage_index,
                             listen=args.listen,upstream=args.upstream,peer=args.peer)
            install(p,start=not args.no_start,dry_run=args.dry_run,stage_login=args.stage_login)
        else:
            if args.name:
                plans = [stored(args.name,Path.home())]
            elif args.action == "status":
                plans = [stored(p.stem,Path.home()) for p in SC.plan_files(Path.home())]
            else:
                raise ValueError("--name is required; this command never acts on every service implicitly")
            if not plans:
                print("[Caravan] No managed services installed.")
            for p in plans:
                control(args.action,p,dry_run=args.dry_run)
    except (ValueError,OSError,KeyError,TypeError) as e:
        print(f"[Caravan] {e}",file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__": sys.exit(main())
