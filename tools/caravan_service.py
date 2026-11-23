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
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agent"))
import service_config as SC
from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text)


def run_launchctl(args):
    return subprocess.run(["/bin/launchctl"]+list(args), capture_output=True, text=True)


def domain():
    return f"gui/{os.getuid()}"


def check_platform():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError(T("cli.service.real_service_changes_need_native_apple"))
    if int((platform.mac_ver()[0] or "0").split(".")[0]) < 14:
        raise ValueError(T("cli.service.macos_14_or_newer_is_required"))
    if os.getuid() == 0:
        raise ValueError(T("cli.service.use_your_normal_logged_in_mac"))


def gui_ready(run=run_launchctl):
    result = run(["print",domain()])
    if result.returncode:
        raise ValueError(T("cli.service.no_gui_login_session_is_available"))


def validate_files(plan):
    root = Path(plan["repo"])
    script = root/({"web": "proxy/web_server.py", "proxy": "proxy/slot_pin_proxy.py"}.get(plan["kind"], "agent/caravan_agent.py"))
    if not script.is_file() or not Path(plan["python"]).is_file():
        raise ValueError(T("cli.service.repository_or_python_is_missing_run"))
    if plan["kind"] in ("web", "proxy"):
        return
    d = Path(plan["model"])
    from mlx_split import check_local_shards, safetensors_expected_size
    from mlx_split_fetch import n_layers_of
    cfg = json.loads((d/"config.json").read_text())
    if not any((d/name).is_file() for name in ("tokenizer.json","tokenizer.model")):
        raise ValueError(T("cli.service.this_workers_model_folder_needs_its"))
    if (d/"model.safetensors.index.json").is_file():
        counts = plan.get("counts") or [n_layers_of(cfg)]
        check_local_shards(d,"head" if plan["role"] in ("lead","single") else "front",
                           counts=counts, stage_index=plan.get("stage_index",0))
    elif plan["role"] == "single":
        files = list(d.glob("*.safetensors"))
        if not files or any(safetensors_expected_size(p) != p.stat().st_size for p in files):
            raise ValueError(T("cli.service.single_mini_model_has_missing_or"))
    else:
        raise ValueError(T("cli.service.split_auto_start_requires_model_safetensors"))


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
            raise ValueError(T("cli.service.port_number_is_already_busy_or", number=number, host=host, e=e)) from None


def assert_owned(plan, require=False, *, staged=None):
    p = SC.paths(plan, staged=staged)
    for key in ("config","plist"):
        if not p[key].exists():
            if require:
                raise ValueError(T("cli.service.owned_key_is_missing_refusing_to", key_=key))
            continue
        if key == "config":
            value = SC.load(p[key])
            expected = plan
        else:
            value = plistlib.loads(p[key].read_bytes())
            expected = SC.render(plan, staged=staged)
        if key == "plist" and isinstance(value, dict) and 'Comment' not in value:
            expected = {k: v for k, v in expected.items() if k != 'Comment'}
        if value != expected:
            raise ValueError(T("cli.service.old_caravan_startup_files_point_to"))


def backup_old_service(plan, run=run_launchctl):
    """Explicit opt-in only. Validate identity, preserve bytes, then unload."""
    paths = SC.paths(plan)
    plist = paths['plist']
    if not plist.is_file() or plist.is_symlink() or paths['config'].is_symlink():
        raise ValueError(T("cli.service.cannot_verify_the_old_caravan_startup"))
    old = plistlib.loads(plist.read_bytes())
    args = old.get('ProgramArguments') or []
    scripts = {'web': 'proxy/web_server.py', 'worker': 'agent/caravan_agent.py', 'proxy': 'proxy/slot_pin_proxy.py'}
    suffix = scripts.get(plan['kind'])
    if (old.get('Label') != plan['label'] or not suffix or len(args) < 2
            or not Path(args[0]).name.lower().startswith('python') or not str(args[1]).endswith('/' + suffix)):
        raise ValueError(T("cli.service.the_existing_startup_file_could_not"))
    if paths['config'].exists():
        prior = SC.load(paths['config'])
        if prior['label'] != plan['label'] or prior['home'] != plan['home']:
            raise ValueError(T("cli.service.old_startup_settings_belong_to_another"))
    import shutil
    import tempfile
    folder = Path(plan['home']) / '.caravan/service-backups'
    folder.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='previous-', dir=folder))
    for key in ('config', 'plist'):
        if paths[key].exists():
            shutil.copy2(paths[key], backup / paths[key].name)
    target = domain() + '/' + plan['label']
    if run(['print', target]).returncode == 0:
        result = run(['bootout', target])
        if result.returncode:
            raise ValueError(T("cli.service.could_not_stop_the_old_caravan", backup=backup))
    # Verified files are now backed up; the following install writes new plans.
    for key in ('config', 'plist'):
        if paths[key].exists():
            paths[key].unlink()
    print(T("cli.service.caravan_previous_startup_files_saved_at", backup=backup))


def install(plan, *, start=True, dry_run=False, stage_login=False, replace_old=False, run=run_launchctl):
    if stage_login and start:
        raise ValueError(T("cli.service.stage_login_requires_no_start"))
    staged = True if stage_login else None
    paths = SC.paths(plan, staged=staged)
    if stage_login and SC.paths(plan, staged=False)["config"].exists():
        raise ValueError(T("cli.service.this_service_already_has_a_normal"))
    if dry_run:
        print(json.dumps({"preview_only":True,"plan":plan,"plist":SC.render(plan, staged=staged),
                          "files":{k:str(v) for k,v in paths.items()},"start":start},indent=2))
        return
    check_platform()
    validate_files(plan)
    try:
        assert_owned(plan, staged=staged)
    except ValueError:
        if not replace_old or stage_login:
            raise
        backup_old_service(plan, run)
    validate_files(plan)
    target = domain()+"/"+plan["label"]
    if start:
        gui_ready(run)
        loaded = run(["print",target]).returncode == 0
        if loaded:
            # A job with our label but no matching on-disk files is not ours to adopt.
            assert_owned(plan,require=True)
            print(T("cli.service.caravan_name_is_already_installed_and", name=plan['name']))
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
            raise ValueError(T("cli.service.another_owned_service_name_reserves_this", name=other['name']))
    for key in ("config","plist","log","runtime"):
        paths[key].parent.mkdir(parents=True,exist_ok=True)
    # Refuse to replace unrelated files. Repeated identical installs are safe.
    paths["config"].write_text(json.dumps(plan,indent=2)+"\n")
    paths["config"].chmod(0o600)
    paths["plist"].write_bytes(plistlib.dumps(SC.render(plan, staged=staged)))
    if start:
        result = run(["bootstrap",domain(),str(paths["plist"])])
        if result.returncode:
            raise ValueError(T("cli.service.launchd_could_not_start_name_v", name=plan['name'], v=(result.stderr or result.stdout).strip()))
    print(T("cli.service.caravan_name_v_it_starts_at", name=plan['name'], v='installed and started' if start else 'installed, not started'))
    print(T("cli.service.caravan_log_log", log=paths['log']))
    if stage_login:
        print(T("cli.service.caravan_staged_for_next_user_login"))


def stored(name,home):
    if not name or not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",name):
        raise ValueError(T("cli.service.choose_an_installed_service_name"))
    root = Path(home)/".caravan/services"
    paths = [p for p in (root/f"{name}.json",root/"login"/f"{name}.json") if p.exists()]
    if len(paths) != 1:
        raise ValueError(T("cli.service.service_plan_missing_or_ambiguous_refusing"))
    path = paths[0]
    plan = SC.load(path)
    if SC.paths(plan)["config"].resolve() != path.resolve():
        raise ValueError(T("cli.service.service_plan_points_outside_this_users"))
    return plan


def retry_bootstrap(plan, result, run, *, timeout=35, clock=time.monotonic,
                    wait=None):
    """launchd can acknowledge bootout before its old job is fully removed.

    Retry only native transient bootstrap error 5, never privilege errors.
    Do not bootstrap over a loaded job or occupied socket; never kill a PID.
    """
    wait = wait or threading.Event().wait
    deadline = clock() + timeout
    target = domain()+"/"+plan["label"]
    def transient(r):
        return r.returncode == 5 or "Bootstrap failed: 5:" in (r.stderr or r.stdout)
    while transient(result) and clock() < deadline:
        wait(.25)
        if run(["print",target]).returncode == 0:
            continue
        try:
            ensure_port_free(plan)
        except ValueError:
            continue  # allow our old child its normal graceful-exit window
        result = run(["bootstrap",domain(),str(SC.paths(plan)["plist"])])
    if transient(result):
        raise ValueError(T("cli.service.launchd_did_not_finish_unloading_restarting"))
    return result


def control(action,plan,*,dry_run=False,run=run_launchctl):
    assert_owned(plan,require=True)
    target = domain()+"/"+plan["label"]
    if dry_run:
        print(T("cli.service.caravan_would_action_only_target_models", action=action, target=target))
        return
    check_platform()
    gui_ready(run)
    loaded = run(["print",target])
    if action == "status":
        print(T("cli.service.caravan_name_v", name=plan['name'], v='loaded' if loaded.returncode == 0 else 'installed, not loaded'))
        if loaded.returncode == 0:
            print(loaded.stdout.strip())
        print(T("cli.service.caravan_log_log", log=SC.paths(plan)['log']))
        if SC.paths(plan)["config"].parent.name == "login" and loaded.returncode != 0:
            print(T("cli.service.caravan_staged_for_next_login_current"))
        return
    if action == "restart":
        if loaded.returncode != 0:
            ensure_port_free(plan)
            result = run(["bootstrap",domain(),str(SC.paths(plan)["plist"])])
        else:
            result = run(["bootout",target])
            if result.returncode == 0:
                result = run(["bootstrap",domain(),str(SC.paths(plan)["plist"])])
        result = retry_bootstrap(plan,result,run)
        if result.returncode:
            raise ValueError((result.stderr or result.stdout).strip() or T("cli.service.launchd_restart_failed"))
        print(T("cli.service.caravan_restarted_only_name", name=plan['name']))
        return
    if loaded.returncode == 0:
        result = run(["bootout",target])
        if result.returncode:
            raise ValueError((result.stderr or result.stdout).strip() or T("cli.service.launchd_unload_failed_files_kept"))
    p = SC.paths(plan)
    p["plist"].unlink()
    p["config"].unlink()
    print(T("cli.service.caravan_uninstalled_only_name_models_caches", name=plan['name']))
    if plan["kind"] == "web":
        print(T("cli.service.caravan_web_owned_workers_were_kept"))


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action",choices=("install","uninstall","status","restart"))
    ap.add_argument("--kind",choices=("web","worker","proxy"),default="web")
    ap.add_argument("--name")
    ap.add_argument("--repo",default=str(ROOT))
    ap.add_argument("--python")
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,help=T("cli.service.web_or_worker_http_port"))
    ap.add_argument("--lead-port",type=int,default=8194)
    ap.add_argument("--model")
    ap.add_argument("--counts")
    ap.add_argument("--stage-index",type=int)
    ap.add_argument("--listen")
    ap.add_argument("--upstream")
    ap.add_argument("--peer")
    ap.add_argument("--no-start",action="store_true")
    ap.add_argument("--stage-login",action="store_true",help=T("cli.service.with_no_start_stage_future_login"))
    ap.add_argument("--replace-old-services", action="store_true", help=T("cli.service.back_up_verified_old_startup_files"))
    ap.add_argument("--dry-run",action="store_true")
    return ap


def main(argv=None):
    ap = parser(); args = ap.parse_args(argv)
    try:
        if args.action == "install":
            p = SC.make_plan(kind=args.kind,name=args.name,repo=args.repo,python=args.python,host=args.host,
                             web_port=args.port if args.port is not None else (8090 if args.kind == "proxy" else 8190),
                             lead_port=(args.port if args.port is not None else args.lead_port) if args.kind == "worker" else args.lead_port,
                             model=args.model,counts=args.counts,stage_index=args.stage_index,
                             listen=args.listen,upstream=args.upstream,peer=args.peer)
            install(p,start=not args.no_start,dry_run=args.dry_run,stage_login=args.stage_login,replace_old=args.replace_old_services)
        else:
            if args.name:
                plans = [stored(args.name,Path.home())]
            elif args.action == "status":
                plans = [stored(p.stem,Path.home()) for p in SC.plan_files(Path.home())]
            else:
                raise ValueError(T("cli.service.name_is_required"))
            if not plans:
                print(T("cli.service.caravan_no_managed_services_installed"))
            for p in plans:
                control(args.action,p,dry_run=args.dry_run)
    except (ValueError,OSError,KeyError,TypeError) as e:
        print(T("cli.service.caravan_e", e=e),file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__": sys.exit(main())
