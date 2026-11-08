"""Explicit N-stage MLX launcher used by Balance, separate from legacy defaults.

No weight transfers. Commands use per-node repository/model paths. Persistent
ownership records let Stop clean up an N-stage run after a web-only restart.
"""
from __future__ import annotations
import json
import re
import shlex
import subprocess
import time
from pathlib import Path


def _marker(node):
    nid = str(node.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", nid):
        raise ValueError("Mini IDs must contain only letters, numbers, _ and -")
    return f"~/.caravan/web-ui/pipeline-{nid}"


def stage_args(node, counts, index, previous=None):
    """Pure argv builder, shared by tests and real startup."""
    from mlx_split import plan_ranges
    plan_ranges(sum(counts), counts)
    if not node.get("model_path"):
        raise ValueError(f"model folder unknown on {node.get('label') or node['id']}")
    args = ["--model", node["model_path"], "--split-counts", ",".join(map(str, counts)),
            "--no-split-draft", "--no-learn", "--split-pipeline-chats", "1"]
    if index == len(counts) - 1:
        if not previous:
            raise ValueError("lead needs a previous packer")
        args += ["--split-role", "lead", "--split-peer", previous]
    else:
        peer = node.get("peer")
        if not peer or ":" not in peer:
            raise ValueError(f"set a reachable HOST:PORT peer for {node['id']}")
        args += ["--split-role", "packer", "--split-stage-index", str(index),
                 "--split-listen", node.get("listen") or peer]
        if index:
            args += ["--split-upstream", node.get("upstream_peer") or previous]
    # Each stage owns a separate session folder, including same-host simulations.
    args += ["--cache-dir", f"~/.caravan/mlx/pipeline-{node['id']}/sessions"]
    return args


def stop_pipeline(mgr):
    path = mgr.state_dir / "pipeline.json"
    if not path.is_file():
        return False
    records = json.loads(path.read_text())
    for node in reversed(records):
        marker = _marker(node) + ".pid"
        listen = node.get("listen") or node["peer"]
        if mgr._node_is_local(node):
            from worker_ownership import stop
            stop(mgr.worker, pid_file=Path(marker).expanduser(), listen=listen)
        else:
            cmd = mgr._remote_stop_command(node["repo"], marker, listen=listen)
            r = mgr._ssh_node(node, cmd, timeout=30)
            if r.returncode:
                raise RuntimeError(f"could not stop pipeline stage on {node['id']}: {r.stderr}")
    path.unlink()
    (mgr.state_dir / "pipeline-balance.json").unlink(missing_ok=True)
    return True


def load_pipeline(mgr, entry, settings):
    from mlx_split import plan_ranges, check_local_shards, FrontClient
    counts = entry["split_counts"]
    nodes = entry["pipeline_nodes"]
    plan_ranges(sum(counts), counts)
    if len(nodes) != len(counts) or nodes[-1].get("role") != "lead" or not mgr._node_is_local(nodes[-1]):
        raise ValueError("pipeline needs one local lead last and one layer count per Mini")
    commands = []
    previous = None
    for i, node in enumerate(nodes):
        _marker(node)
        args = stage_args(node, counts, i, previous)
        commands.append(args)
        previous = node.get("peer") or previous
        # All shards must pass the worker's exact size checks before stopping a
        # running model. This is rechecked by Stage at load, closing file races.
        if mgr._node_is_local(node):
            check_local_shards(Path(node["model_path"]).expanduser(),
                               "head" if i == len(nodes)-1 else "front", counts=counts, stage_index=i)
        else:
            # Invoke the node's own code, with an argv JSON (no model files copied).
            script = ("import sys,json;from pathlib import Path;"
                      "repo,model,counts,i=json.loads(sys.argv[1]);"
                      "sys.path.insert(0,str(Path(repo).expanduser()/'agent'));"
                      "from mlx_split import check_local_shards;"
                      "check_local_shards(Path(model).expanduser(),'front',counts=counts,stage_index=i)")
            cmd = ("~/.caravan/venvs/mlx/bin/python -c " + shlex.quote(script) + " "
                   + shlex.quote(json.dumps([node.get("repo") or "~/cv3", node["model_path"], counts, i])))
            r = mgr._ssh_node(node, cmd, timeout=60)
            if r.returncode:
                raise ValueError(f"{node['id']} files not ready: {(r.stderr or r.stdout)[-800:]}")
    mgr._set(status="stopping", error=None, model_id=entry["id"], model_name=entry["name"], progress=[], split=True)
    mgr._kill_gguf()
    mgr._kill_lead()
    mgr._kill_packer()
    records = []
    ownership = mgr.state_dir / "pipeline.json"
    try:
        for i, node in enumerate(nodes[:-1]):
            mgr._set(status="starting_packer")
            args = commands[i]
            extras = __import__("web_settings").to_args(dict(settings, pipeline_chats="1", guess_ahead="off"))[1]
            # Balance counts are pinned; use simple serial inference for the
            # unbenchmarked N-stage path (no speculative or reload experiments).
            args += extras
            marker = _marker(node)
            log = marker + ".log"
            if mgr._node_is_local(node):
                args = [str(Path(a).expanduser()) if a.startswith("~/") else a for a in args]
                lp = Path(log).expanduser()
                lp.parent.mkdir(parents=True, exist_ok=True)
                with lp.open("wb") as output:
                    proc = subprocess.Popen([mgr.python, str(mgr.worker)] + args, stdout=output, stderr=subprocess.STDOUT,
                                            start_new_session=True)
                Path(marker + ".pid").expanduser().write_text(str(proc.pid))
            else:
                repo = node.get("repo") or "~/cv3"
                cmd = ("mkdir -p ~/.caravan/web-ui; nohup ~/.caravan/venvs/mlx/bin/python "
                       + mgr._remote_path(repo.rstrip("/") + "/agent/mlx_worker.py") + " "
                       + " ".join(mgr._remote_path(a) if a.startswith("~/") else shlex.quote(a) for a in args)
                       + " > " + mgr._remote_path(log) + " 2>&1 & echo $! > " + mgr._remote_path(marker + ".pid"))
                r = mgr._ssh_node(node, cmd, timeout=30)
                if r.returncode:
                    raise RuntimeError(f"{node['id']} start failed: {r.stderr}")
            records.append(dict(node, repo=node.get("repo") or "~/cv3"))
            ownership.write_text(json.dumps(records))
            # All peer addresses must be reachable from the lead. Middle
            # packers additionally validate their upstream ranges on startup.
            deadline = time.monotonic() + 300
            error = None
            while time.monotonic() < deadline:
                client = FrontClient(node["peer"], timeout=10)
                try:
                    hello = client.call("hello")[0]
                    expected = plan_ranges(sum(counts), counts)[:i+1]
                    actual = [tuple(x["range"]) for x in hello.get("stages", [hello])]
                    if actual != expected:
                        raise ValueError("loaded pipeline ranges do not match Balance")
                    error = None
                    break
                except (OSError, RuntimeError, ConnectionError) as e:
                    error = e
                    time.sleep(1)
                finally:
                    client.close()
            if error:
                raise RuntimeError(f"{node['id']} did not become ready: {error}; see {log}")
            mgr._note(f"{node.get('label') or node['id']}: {counts[i]} layers ready")
        mgr._set(status="starting_lead")
        lead = nodes[-1]
        args = commands[-1] + ["--host", "127.0.0.1", "--port", str(mgr.lead_port)]
        args += __import__("web_settings").to_args(dict(settings, pipeline_chats="1", guess_ahead="off"))[0]
        args = [str(Path(a).expanduser()) if a.startswith("~/") else a for a in args]
        with mgr._lead_log().open("wb") as output:
            mgr._lead_proc = subprocess.Popen([mgr.python, str(mgr.worker)] + args, stdout=output,
                                              stderr=subprocess.STDOUT, start_new_session=True)
        (mgr.state_dir / "lead.pid").write_text(str(mgr._lead_proc.pid))
        mgr._set(lead_pid=mgr._lead_proc.pid, packer_pid=None)
        mgr._wait_lead_ready(timeout=600)
        mgr._loaded_entry = dict(entry)
        mgr._lead_path = lead["model_path"]
        balance = {"counts": counts, "node_ids": [n["id"] for n in nodes], "lead_pid": mgr._lead_proc.pid}
        (mgr.state_dir / "pipeline-balance.json").write_text(json.dumps(balance))
        mgr._set(status="ready", split=True, balance=balance)
        mgr._note("Balance loaded; send a reply to measure real speed")
    except Exception:
        mgr._kill_lead()
        stop_pipeline(mgr)
        raise
