"""Portable service plans. No launchctl, MLX, network or filesystem writes here."""
from __future__ import annotations
import json
import os
import plistlib
import re
from pathlib import Path

OWNER = "caravan-service-v1"
ROOT = Path(__file__).resolve().parents[1]


def absolute(path):
    return str(Path(path).expanduser().resolve())


def port(value):
    n = int(value)
    if not 1 <= n <= 65535:
        raise ValueError("ports must be between 1 and 65535")
    return n


def endpoint(value):
    from mlx_split import _hostport
    host, number = _hostport(value)
    if not host:
        raise ValueError("use a private HOST:PORT, not just a port")
    port(number)
    return str(value)


def make_plan(*, kind, name=None, repo=ROOT, python=None, home=None, host="127.0.0.1",
              web_port=8190, lead_port=8194, model=None, counts=None, stage_index=None,
              listen=None, upstream=None, peer=None):
    home = Path(home or Path.home()).expanduser().resolve()
    repo = Path(repo).expanduser().resolve()
    name = name or ("web" if kind == "web" else "worker")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("service name must use 1-64 letters, numbers, _ or -")
    if kind not in ("web", "worker"):
        raise ValueError("choose web or worker")
    # A venv's Python is commonly a symlink to Homebrew/system Python. Resolving
    # that symlink changes sys.prefix and silently loses all venv dependencies.
    py = os.path.abspath(os.path.expanduser(str(python or home/".caravan/venvs/mlx/bin/python")))
    plan = {"managed_by": OWNER, "schema": 1, "kind": kind, "name": name,
            "label": f"com.caravan.v3.{name}", "repo": str(repo), "python": py,
            "home": str(home), "host": str(host), "port": port(web_port if kind == "web" else lead_port)}
    if kind == "web":
        if model or counts or stage_index is not None or listen or upstream or peer:
            raise ValueError("web service does not load a model; install a separate worker plan")
        plan["lead_port"] = port(lead_port)
    else:
        if not model:
            raise ValueError("worker auto-start needs an installed local --model folder")
        plan["model"] = absolute(model)
        plan["cache_dir"] = str(home/".caravan/mlx"/f"service-{name}"/"sessions")
        if counts:
            from mlx_split import parse_counts, plan_ranges
            counts = parse_counts(counts) if isinstance(counts,str) else list(counts)
            plan_ranges(sum(counts), counts)
            if len(counts) < 2 or type(stage_index) is not int or not 0 <= stage_index < len(counts):
                raise ValueError("split counts need a valid zero-based stage index")
            plan.update(counts=counts, stage_index=stage_index,
                        role="lead" if stage_index == len(counts)-1 else "packer")
            if plan["role"] == "lead":
                if not peer or listen or upstream:
                    raise ValueError("split lead needs --peer, not --listen/--upstream")
                plan["peer"] = endpoint(peer)
            else:
                if not listen or peer or bool(stage_index) != bool(upstream):
                    raise ValueError("packer needs --listen; only middle packers also need --upstream")
                plan["listen"] = endpoint(listen)
                if upstream:
                    plan["upstream"] = endpoint(upstream)
        else:
            if stage_index is not None or listen or upstream or peer:
                raise ValueError("split stage options require --counts")
            plan["role"] = "single"
    return plan


def worker_command(plan):
    cmd = [plan["python"], str(Path(plan["repo"])/"agent/mlx_worker.py"),
           "--model", plan["model"], "--cache-dir", plan["cache_dir"]]
    if plan["role"] == "single":
        return cmd + ["--split-role", "none", "--host", plan["host"], "--port", str(plan["port"])]
    cmd += ["--split-counts", ",".join(map(str,plan["counts"])), "--split-role", plan["role"],
            "--no-learn", "--no-split-draft", "--split-pipeline-chats", "1"]
    if plan["role"] == "lead":
        cmd += ["--split-peer", plan["peer"], "--host", plan["host"], "--port", str(plan["port"])]
    else:
        cmd += ["--split-stage-index", str(plan["stage_index"]), "--split-listen", plan["listen"]]
        if plan.get("upstream"):
            cmd += ["--split-upstream", plan["upstream"]]
    return cmd


def paths(plan, *, staged=None):
    home = Path(plan["home"])
    root = home/".caravan/services"
    canonical = root/f"{plan['name']}.json"
    login = root/"login"/f"{plan['name']}.json"
    if staged is None:
        staged = not canonical.exists() and login.exists()
    return {"config": login if staged else canonical,
            "plist": home/"Library/LaunchAgents"/f"{plan['label']}.plist",
            "log": home/".caravan/logs"/f"{plan['name']}.log",
            "runtime": root/"runtime"/f"{plan['name']}.json"}


def render(plan, *, staged=None):
    p = paths(plan, staged=staged)
    if plan["kind"] == "web":
        cmd = [plan["python"], str(Path(plan["repo"])/"proxy/web_server.py"),
               "--host", plan["host"], "--port", str(plan["port"]),
               "--lead-port", str(plan["lead_port"]), "--repo", plan["repo"]]
    else:
        cmd = [plan["python"], str(Path(plan["repo"])/"agent/caravan_agent.py"),
               "--service-config", str(p["config"]), "--apply"]
    return {"Label": plan["label"], "ProgramArguments": cmd,
            "WorkingDirectory": plan["repo"], "RunAtLoad": True, "KeepAlive": True,
            "ThrottleInterval": 15, "ExitTimeOut": 30, "ProcessType": "Interactive",
            "AbandonProcessGroup": plan["kind"] == "web",
            "StandardOutPath": str(p["log"]), "StandardErrorPath": str(p["log"]),
            "EnvironmentVariables": {"HOME": plan["home"], "PYTHONUNBUFFERED": "1",
                                     "CARAVAN_WEB_KEEP_WORKERS": "1",
                                     "PATH": str(Path(plan["python"]).parent)+":/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"}}


def load(path):
    plan = json.loads(Path(path).expanduser().read_text())
    if plan.get("managed_by") != OWNER or plan.get("schema") != 1:
        raise ValueError("not a Caravan-managed service plan")
    # Rebuild rather than trust serialized command lines or labels.
    rebuilt = make_plan(kind=plan["kind"],name=plan["name"],repo=plan["repo"],python=plan["python"],home=plan["home"],
                        host=plan["host"],web_port=plan["port"],lead_port=plan.get("lead_port",plan["port"]),
                        model=plan.get("model"),counts=plan.get("counts"),stage_index=plan.get("stage_index"),
                        listen=plan.get("listen"),upstream=plan.get("upstream"),peer=plan.get("peer"))
    if plan != rebuilt:
        raise ValueError("service plan has unsupported fields or was edited inconsistently; regenerate it")
    return rebuilt


def plan_files(home):
    root = Path(home)/".caravan/services"
    return sorted(root.glob("*.json")) + sorted((root/"login").glob("*.json"))


def login_job_loaded(plan):
    """A staged plan does not own an existing worker until launchd loads it.

    The schema stays compatible; staging lives outside the canonical scan used
    by an older already-running web server. Errors other than job-not-found
    fail closed, rather than releasing an active launchd worker to the UI.
    """
    import subprocess
    try:
        r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{plan['label']}"],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"Cannot check staged auto-start ownership: {e}") from None
    if r.returncode == 0:
        return True
    if r.returncode in (3,113) or "Could not find service" in r.stderr or "No such process" in r.stderr:
        return False
    raise ValueError(f"Cannot check staged auto-start ownership: {r.stderr.strip()}")


def managed_plans(home):
    root = Path(home)/".caravan/services"
    for path in plan_files(home):
        try:
            plan = load(path)
            if path.parent == root/"login" and not login_job_loaded(plan):
                continue
        except (ValueError, OSError, KeyError, TypeError) as e:
            raise ValueError(f"Unreadable auto-start plan {path}; repair it before changing workers: {e}") from None
        yield plan


def managed_lead(home, lead_port):
    """Normal installed plans reserve their port; login-staged plans reserve it
    only after launchd loads the job. No current worker is adopted by staging."""
    for p in managed_plans(home):
        if p["kind"] == "worker" and p["role"] in ("single","lead") and p["port"] == lead_port:
            return p
    return None


def managed_worker_port(home, number):
    for p in managed_plans(home):
        reserved = int(p["listen"].rsplit(":",1)[1]) if p.get("role") == "packer" else p["port"]
        if p["kind"] == "worker" and reserved == int(number):
            return p
    return None
