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
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402


def _marker(node):
    nid = str(node.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", nid):
        raise ValueError(T("server.web_pipeline.mini_ids_must_contain_only_letters"))
    return f"~/.caravan/web-ui/pipeline-{nid}"


def stage_args(node, counts, index, previous=None):
    """Pure argv builder, shared by tests and real startup."""
    from mlx_split import plan_ranges
    plan_ranges(sum(counts), counts)
    if not node.get("model_path"):
        raise ValueError(T("server.web_pipeline.model_folder_unknown_on_v", v=node.get('label') or node['id']))
    args = ["--model", node["model_path"], "--split-counts", ",".join(map(str, counts)),
            "--no-split-draft", "--no-learn", "--split-pipeline-chats", "1"]
    if index == len(counts) - 1:
        if not previous:
            raise ValueError(T("server.web_pipeline.lead_needs_a_previous_packer"))
        args += ["--split-role", "lead", "--split-peer", previous]
    else:
        peer = node.get("peer")
        if not peer or ":" not in peer:
            raise ValueError(T("server.web_pipeline.set_a_reachable_host_port_peer", id=node['id']))
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
                raise RuntimeError(T("server.web_pipeline.could_not_stop_pipeline_stage_on", id=node['id'], stderr=r.stderr))
    path.unlink()
    (mgr.state_dir / "pipeline-balance.json").unlink(missing_ok=True)
    return True


def adopted_entry(mgr, cmd, pid):
    """Recover a command-verified owned pipeline outside the default catalog roots.

    No discovery, downloads, process changes, or client-supplied paths. A stale
    state file cannot turn a different command/range into an adopted pipeline.
    """
    from mlx_split import plan_ranges
    from mlx_split_fetch import n_layers_of
    import model_inventory as inventory
    import web_catalog as catalog
    import web_nodes
    try:
        balance = json.loads((mgr.state_dir / "pipeline-balance.json").read_text())
        records = json.loads((mgr.state_dir / "pipeline.json").read_text())
        counts, ids = balance["counts"], balance["node_ids"]
        args = shlex.split(cmd)
        def flag(key):
            if key in args: return args[args.index(key)+1]
            return next((v.split("=",1)[1] for v in args if v.startswith(key+"=")), None)
        path = Path(flag("--model")).expanduser()
        if balance["lead_pid"] != pid or flag("--split-role") != "lead": return None
        if [int(v) for v in flag("--split-counts").split(",")] != counts: return None
        if balance.get("model_path") and Path(balance["model_path"]).expanduser() != path: return None
        plan_ranges(n_layers_of(json.loads((path/"config.json").read_text())), counts)
        if len(ids) != len(counts) or len(set(ids)) != len(ids): return None
        if [r["id"] for r in records] != ids[:-1]: return None
        nodes = {n["id"]: n for n in web_nodes.nodes_from_config()}
        lead = nodes[ids[-1]]
        if lead.get("role") != "lead" or not web_nodes.is_local(lead): return None
        if any(nodes[nid].get("role") == "lead" for nid in ids[:-1]): return None
        if flag("--split-peer") != records[-1]["peer"]: return None
        repo = inventory.folder_to_repo(path.name)
        entry = dict(id=balance.get("model_id") or catalog.slug_id(repo),
                     name=balance.get("model_name") or inventory.pretty_name(repo),
                     hf=repo, lead_path=str(path), split_counts=counts,
                     pipeline_nodes=records+[dict(lead, model_path=str(path))],
                     placement={"mode":"split","node_ids":ids},
                     run_mode="split", need_split=True, usable=True, available_lead=True)
        return entry
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def resolve_nodes(mgr, nodes):
    """Resolve explicit per-node TB interfaces; retain concrete ownership records."""
    import service_endpoints as SE
    import peer_route as PR
    out=[]
    for node in nodes:
        n=dict(node)
        # Link-order fix: the lead<->Mac data link is the first working link in
        # the fixed order Thunderbolt > wired Ethernet > Wi-Fi > other, re-checked
        # on every load. Not a Mac / nothing checkable: the strict tb:// rules below.
        route=None
        target=(n.get("ssh") or n.get("host") or "").strip()
        if target and not mgr._node_is_local(n) and any(n.get(k) for k in ("peer","listen")):
            route=PR.route_for(target,fresh=True,label=n.get("label") or n.get("id"))
            if route and route.get("warning"):
                note=getattr(mgr,"_note",None)
                if note:note(route["warning"])
        for key in ("peer","listen","upstream_peer"):
            value=n.get(key)
            if not value:continue
            if key in ("peer","listen") and route and route.get("address"):
                port=str(value).rsplit(":",1)[-1]
                if port.isdigit():
                    n[key]=f"{route['address']}:{port}";n["link"]=route["kind"];continue
            spec=SE.parse(value)
            if spec and spec[0] is None and not mgr._node_is_local(n):
                target=n.get("ssh") or n.get("host")
                if not target:raise ValueError(T("server.web_pipeline.remote_thunderbolt_interface_needs_a_trusted"))
                value=f"ssh+tb://{target}/{spec[1]}:{spec[2]}"
            n[key]=SE.resolve(value)
        out.append(n)
    return out


def load_pipeline(mgr, entry, settings):
    from mlx_split import plan_ranges, check_local_shards, FrontClient
    counts = entry["split_counts"]
    nodes = resolve_nodes(mgr, entry["pipeline_nodes"])
    entry = dict(entry,pipeline_nodes=nodes)
    check_cancel = getattr(mgr,"_check_load_cancel",lambda:None)
    check_cancel()
    plan_ranges(sum(counts), counts)
    if len(nodes) != len(counts) or nodes[-1].get("role") != "lead" or not mgr._node_is_local(nodes[-1]):
        raise ValueError(T("server.web_pipeline.pipeline_needs_one_local_lead_last"))
    commands = []
    previous = None
    for i, node in enumerate(nodes):
        check_cancel()
        _marker(node)
        args = stage_args(node, counts, i, previous)
        commands.append(args)
        previous = node.get("peer") or previous
        # All shards must pass the worker's exact size checks before stopping a
        # running model. This is rechecked by Stage at load, closing file races.
        if mgr._node_is_local(node):
            import service_config as SC
            number = int((node.get("listen") or node.get("peer")).rsplit(":",1)[1]) if i < len(nodes)-1 else mgr.lead_port
            reserved = SC.managed_worker_port(Path.home(), number)
            if reserved:
                raise ValueError(T("server.web_pipeline.auto_start_service_name_owns_this", name=reserved['name']))
            check_local_shards(Path(node["model_path"]).expanduser(),
                               "head" if i == len(nodes)-1 else "front", counts=counts, stage_index=i)
        else:
            # Invoke the node's own code, with an argv JSON (no model files copied).
            script = ("import sys,json;from pathlib import Path;"
                      "repo,model,counts,i,port=json.loads(sys.argv[1]);"
                      "sys.path.insert(0,str(Path(repo).expanduser()/'agent'));"
                      "from service_config import managed_worker_port;"
                      "reserved=managed_worker_port(Path.home(),port);"
                      "assert reserved is None, 'An auto-start service owns this packer; uninstall its job before using web-managed loads';"
                      "from mlx_split import check_local_shards;"
                      "check_local_shards(Path(model).expanduser(),'front',counts=counts,stage_index=i)")
            cmd = ("~/.caravan/venvs/mlx/bin/python -c " + shlex.quote(script) + " "
                   + shlex.quote(json.dumps([node.get("repo") or "~/.caravan/src/caravan", node["model_path"], counts, i,
                                                  int((node.get("listen") or node["peer"]).rsplit(":",1)[1]) ])))
            r = mgr._ssh_node(node, cmd, timeout=60)
            if r.returncode:
                raise ValueError(T("server.web_pipeline.id_files_not_ready_v", id=node['id'], v=(r.stderr or r.stdout)[-800:]))
    mgr._set(status="stopping", error=None, model_id=entry["id"], model_name=entry["name"], progress=[], split=True)
    mgr._kill_gguf()
    mgr._kill_lead()
    mgr._kill_packer()
    records = []
    ownership = mgr.state_dir / "pipeline.json"
    try:
        for i, node in enumerate(nodes[:-1]):
            check_cancel()
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
                repo = node.get("repo") or "~/.caravan/src/caravan"
                cmd = ("mkdir -p ~/.caravan/web-ui; nohup ~/.caravan/venvs/mlx/bin/python "
                       + mgr._remote_path(repo.rstrip("/") + "/agent/mlx_worker.py") + " "
                       + " ".join(mgr._remote_path(a) if a.startswith("~/") else shlex.quote(a) for a in args)
                       + " > " + mgr._remote_path(log) + " 2>&1 & echo $! > " + mgr._remote_path(marker + ".pid"))
                r = mgr._ssh_node(node, cmd, timeout=30)
                if r.returncode:
                    raise RuntimeError(T("server.web_pipeline.id_start_failed_stderr", id=node['id'], stderr=r.stderr))
            records.append(dict(node, repo=node.get("repo") or "~/.caravan/src/caravan"))
            ownership.write_text(json.dumps(records))
            # All peer addresses must be reachable from the lead. Middle
            # packers additionally validate their upstream ranges on startup.
            deadline = time.monotonic() + 300
            error = None
            while time.monotonic() < deadline:
                check_cancel()
                client = FrontClient(node["peer"], timeout=10)
                try:
                    hello = client.call("hello")[0]
                    expected = plan_ranges(sum(counts), counts)[:i+1]
                    actual = [tuple(x["range"]) for x in hello.get("stages", [hello])]
                    if actual != expected:
                        raise ValueError(T("server.web_pipeline.loaded_pipeline_ranges_do_not_match"))
                    error = None
                    break
                except (OSError, RuntimeError, ConnectionError) as e:
                    error = e
                    time.sleep(1)
                finally:
                    client.close()
            if error:
                raise RuntimeError(T("server.web_pipeline.id_did_not_become_ready", id=node['id'], error=error, log=log))
            label = node.get('label') or node['id']
            msg = T("server.web_pipeline.label_count_layers_ready", label=label, count=counts[i])
            try:  # Day 32: the Balance view checks the code, not the words
                mgr._note(msg, code="stage_ready", label=label, count=counts[i])
            except TypeError:  # a manager without coded notes
                mgr._note(msg)
        mgr._set(status="starting_lead")
        lead = nodes[-1]
        args = commands[-1] + ["--host", "127.0.0.1", "--port", str(mgr.lead_port)]
        import web_settings as _ws
        args += _ws.to_args(dict(settings, pipeline_chats="1", guess_ahead="off"))[0]
        # Shared stage defaults include --no-learn (packers should not record).
        # Drop it on the lead when Self-tuning is on, so learning matches On.
        args = _ws.drop_no_learn_for_lead(args, settings)
        args = [str(Path(a).expanduser()) if a.startswith("~/") else a for a in args]
        with mgr._lead_log().open("wb") as output:
            mgr._lead_proc = subprocess.Popen([mgr.python, str(mgr.worker)] + args, stdout=output,
                                              stderr=subprocess.STDOUT, start_new_session=True)
        (mgr.state_dir / "lead.pid").write_text(str(mgr._lead_proc.pid))
        mgr._set(lead_pid=mgr._lead_proc.pid, packer_pid=None)
        mgr._wait_lead_ready(timeout=600)
        mgr._loaded_entry = dict(entry)
        mgr._lead_path = lead["model_path"]
        balance = {"counts": counts, "node_ids": [n["id"] for n in nodes], "lead_pid": mgr._lead_proc.pid,
                   "model_id": entry["id"], "model_name": entry["name"], "model_path": mgr._lead_path}
        (mgr.state_dir / "pipeline-balance.json").write_text(json.dumps(balance))
        mgr._set(status="ready", split=True, balance=balance)
        mgr._note(T("server.web_pipeline.balance_loaded_send_a_reply_to"))
    except Exception:
        mgr._kill_lead()
        stop_pipeline(mgr)
        raise
