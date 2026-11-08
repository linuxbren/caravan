"""Local MLX worker lifecycle for caravan_agent --service-config.

Each node runs its own plan; no SSH, file relay, downloads or remote process
control. Missing upstream stages cause a bounded retry, so login order does not
matter. Only the Popen child this agent created is ever terminated.
"""
from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
import service_config as SC


def upstream_ready(plan, client_factory=None):
    if not plan.get("peer") and not plan.get("upstream"):
        return
    from mlx_split import FrontClient, plan_ranges
    client = (client_factory or FrontClient)(plan.get("peer") or plan["upstream"], timeout=10)
    try:
        hello = client.call("hello")[0]
        expected = plan_ranges(sum(plan["counts"]),plan["counts"])[:plan["stage_index"]]
        actual = [tuple(s["range"]) for s in hello.get("stages",[hello])]
        if actual != expected or hello.get("n_layers") != sum(plan["counts"]):
            raise ValueError("Upstream layers do not match this Mini's saved split. Check all stage plans.")
    finally:
        client.close()


def write_runtime(plan, child_pid):
    p = SC.paths(plan)
    p["runtime"].parent.mkdir(parents=True,exist_ok=True)
    record = {"managed_by":SC.OWNER,"label":plan["label"],"agent_pid":os.getpid(),"pid":child_pid,
              "worker":str(Path(plan["repo"])/"agent/mlx_worker.py"),
              "port":plan["port"],"listen":plan.get("listen"),"role":plan["role"]}
    temporary = p["runtime"].with_suffix(".tmp")
    temporary.write_text(json.dumps(record)); temporary.replace(p["runtime"])


def clear_runtime(plan,child_pid):
    p = SC.paths(plan)["runtime"]
    try:
        if json.loads(p.read_text()).get("pid") == child_pid:
            p.unlink()
    except (OSError,ValueError):
        pass


def run(path, *, apply=False, stop=None, popen=subprocess.Popen, retry_seconds=15):
    plan = SC.load(path)
    if plan["kind"] != "worker":
        raise ValueError("agent service config must describe a local worker")
    cmd = SC.worker_command(plan)
    print("[Caravan] Local worker plan: "+__import__("shlex").join(cmd),flush=True)
    if not apply:
        print("[Caravan] Preview only; --apply starts this Mini's own worker.",flush=True)
        return 0
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
    from caravan_service import validate_files,ensure_port_free
    stop = stop or threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT,signal.SIGTERM):
            previous[sig] = signal.signal(sig,lambda *_:stop.set())
    try:
        while not stop.is_set():
            child = None
            try:
                validate_files(plan)
                upstream_ready(plan)
                if stop.is_set():
                    break
                ensure_port_free(plan)
                child = popen(cmd)
                write_runtime(plan,child.pid)
                print(f"[Caravan] Started local {plan['role']} worker pid {child.pid}.",flush=True)
                while child.poll() is None and not stop.wait(0.5):
                    pass
                if stop.is_set() and child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait()
                else:
                    print(f"[Caravan] Worker exited ({child.returncode}); retrying in {retry_seconds}s.",flush=True)
            except (OSError,RuntimeError,ValueError,KeyError) as e:
                print(f"[Caravan] Not ready: {e}. Waiting {retry_seconds}s; no model downloads or other processes touched.",flush=True)
            finally:
                if child is not None:
                    # Also reap our child if bookkeeping or readiness raised.
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            child.kill(); child.wait()
                    clear_runtime(plan,child.pid)
            stop.wait(retry_seconds)
    finally:
        for sig,handler in previous.items():
            signal.signal(sig,handler)
    print("[Caravan] Local worker service stopped; files and caches kept.",flush=True)
    return 0
