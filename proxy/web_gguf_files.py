"""GGUF Balance file preview: lead-first RPC order, explicit source and shares."""
import json
from pathlib import Path
import shlex

from gguf_files import source_manifest, stage_plan, status
import web_files
import web_nodes
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402


def preview(app, entry, body, *, fresh=False):
    path = Path(entry['lead_path']).expanduser()
    saved = path.parent/'caravan-gguf-source.json'
    origin = json.loads(saved.read_text()) if saved.exists() else {}
    repo, filename = body.get('repo_id') or origin.get('repo_id'), body.get('gguf_file') or origin.get('filename')
    if not repo or not filename:
        raise ValueError(T("server.web_gguf_files.enter_the_original_hugging_face_repository"))
    manifest = source_manifest(path, repo, filename)
    configured = app.configured_nodes()
    ids = body.get('node_ids')
    if ids is not None:
        if not isinstance(ids,list) or len(set(ids)) != len(ids) or not set(ids) <= {n['id'] for n in configured}:
            raise ValueError(T("server.web_gguf_files.unknown_or_duplicate_mini_ids"))
        configured = [n for n in configured if n['id'] in ids]
    nodes = [n for n in configured if n.get('role') == 'lead'] + [n for n in configured if n.get('role') != 'lead']
    if len(nodes) < 2 or sum(n.get('role')=='lead' for n in nodes) != 1 or not web_nodes.is_local(nodes[0]):
        raise ValueError(T("server.web_gguf_files.gguf_peer_file_plans_need_a"))
    physical = [n.get('physical_id') or n.get('ssh') or n.get('host') for n in nodes]
    if len(set(physical)) != len(physical):
        raise ValueError(T("server.web_gguf_files.gguf_rpc_simulation_needs_separate_cache"))
    if fresh:
        live = {n['id']: web_nodes.gather_node_stats(n, ssh_fn=app._ssh_fn()) for n in nodes}
    else:
        live = {n['id']: n for n in app.nodes().get('nodes') or []}
    free = [(live.get(n['id'],{}).get('ram') or {}).get('available_gb') for n in nodes]
    from gguf_split import shares_from_free
    counts = body.get('counts') if body.get('counts') is not None else shares_from_free(free)
    if len(counts) != len(nodes): raise ValueError(T("server.web_gguf_files.one_gguf_share_is_required_per"))
    stages, requests = [], []
    for i,n in enumerate(nodes):
        request = stage_plan(manifest, counts, i)
        # Part manifests are metadata only; the peer fetches tensor bytes directly.
        request.update(dest='~/.caravan/gguf-plans')
        requests.append(request)
        if i == 0:
            usage = path.stat()
            files = dict(downloads=[], download_bytes=0, required_bytes=usage.st_size,
                         on_disk_bytes=usage.st_size, allocated_bytes=usage.st_blocks*512,
                         not_needed_for_plan=[], retained_bytes=0, cache_scope='complete lead GGUF (required by llama.cpp)')
        elif web_nodes.is_local(n):
            files = status(request)
        else:
            # Avoid an argv-size limit by querying only this source's ownership record;
            # tensors are chunked to a private request file by the actual fetch job.
            code = """import json,sys
from pathlib import Path
sys.path[:0]=[str(Path(sys.argv[1]).expanduser()/'agent')]
from gguf_files import status
p=json.loads(sys.argv[2]); print(json.dumps(status(p)))
"""
            data = json.dumps(request)
            if len(data) > 80000:
                raise ValueError(T("server.web_gguf_files.gguf_peer_manifest_exceeds_preview_command"))
            cmd = 'python3 -c '+shlex.quote(code)+' '+web_files.rp(n.get('repo') or '~/.caravan/src/caravan')+' '+shlex.quote(data)
            r = web_files.shell(app,n,cmd)
            if r.returncode: raise ValueError(T("server.web_gguf_files.cannot_inspect_gguf_cache_on_id", id=n['id'], v=(r.stderr or '')[-250:]))
            files = json.loads(r.stdout.strip().splitlines()[-1])
        available = free[i]
        active = live.get(n['id'],{}).get('active_gb') or live.get(n['id'],{}).get('weights_gb') or 0
        estimate = manifest['source_bytes']/1e9 * counts[i]/sum(counts) + 1.3
        headroom = None if available is None else round(float(available)+float(active)-estimate, 2)
        stages.append(dict(files, id=n['id'], label=n.get('label') or n['id'], role=n.get('role'),
                           range=request['layer_range'], layers=counts[i], estimated_use_gb=round(estimate,2),
                           headroom_gb=headroom, safe=headroom is not None and headroom>=1.75,
                           metadata_ready=True))
    safe = all(s['safe'] for s in stages)
    ready = safe and all(s['downloads']==[] for s in stages)
    out = dict(format='gguf', repo_id=repo, model_id=entry['id'], counts=counts,
               node_ids=[n['id'] for n in nodes], mode='auto' if body.get('counts') is None else 'manual',
               margin_gb=1.75, safe=safe, ready=ready, stages=stages, file_requests=requests,
               entry=dict(entry, placement={'mode':'split','node_ids':[n['id'] for n in nodes]}, gguf_shares=counts, gguf_peer_files_ready=ready),
               note=T("server.web_gguf_files.gguf_shares_not_exact_mlx_layer"))
    return out
