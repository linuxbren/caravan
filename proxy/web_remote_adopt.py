"""Read-only, identity-verified KEEP_WORKERS adoption for a remote single Mini."""
import json
from pathlib import Path
import shlex
import subprocess
import worker_ownership as O
import web_settings


def tunnel_matches(command,target,port):
    from web_tunnels import tunnel_matches as _match
    return _match(command, target, port)


def adopt(mgr):
    try:
        meta=json.loads((mgr.state_dir/"remote-worker.json").read_text())
        from web_nodes import nodes_from_config,is_local
        node=next(n for n in nodes_from_config() if n.get("id")==meta["node"])
        target=node.get("ssh") or node.get("host")
        if is_local(node) or target!=meta["ssh"] or (node.get("repo") or "~/cv3").rstrip("/")!=meta["repo"].rstrip("/"):return False
        pid,tid=int(meta["pid"]),int(meta["tunnel_pid"])
        if pid<=1 or tid<=1 or not meta.get("model_id"):return False
        if not tunnel_matches(O.command_of(tid),target,mgr.lead_port):return False
        # Ask only the configured Mini/repo to inspect its tracked child identity.
        code=("import sys,json;from pathlib import Path;"
              "repo,pid,port,model=json.loads(sys.argv[1]);"
              "sys.path.insert(0,str(Path(repo).expanduser()/'proxy'));"
              "from worker_ownership import command_of,matches,option;import shlex;"
              "cmd=command_of(pid);"
              "print(json.dumps({'owned':matches(cmd,Path(repo).expanduser()/'agent/mlx_worker.py',port=port) "
              "and option(shlex.split(cmd),'--model')==model}))")
        data=json.dumps([node.get("repo") or "~/cv3",pid,mgr.lead_port,meta["model"]])
        r=mgr._ssh_node(node,"~/.caravan/venvs/mlx/bin/python -c "+shlex.quote(code)+" "+shlex.quote(data),timeout=15)
        if r.returncode or not json.loads(r.stdout.strip()).get("owned") or not mgr.lead_healthy():return False
        mgr._worker_node=dict(node);mgr._lead_path=meta["model"]
        mgr._adopted_tunnel=(tid,target,mgr.lead_port)
        mgr._loaded_entry=dict(id=meta["model_id"],name=meta.get("model_name") or meta["model_id"],source="mlx",lead_path=meta["model"],placement={"mode":"one","node_ids":[node["id"]]},run_mode="single",available_lead=True)
        settings=web_settings.normalize(meta.get("settings") or {})
        mgr._set(status="ready",model_id=meta["model_id"],model_name=mgr._loaded_entry["name"],lead_pid=pid,split=False,settings=settings,page_settings=settings)
        mgr._note("adopted owned remote single-Mini worker and SSH tunnel; no reload")
        return True
    except (OSError,ValueError,TypeError,KeyError,StopIteration,subprocess.SubprocessError):return False
