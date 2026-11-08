"""Shared web/future-TUI file plan execution. Configured hosts and server paths only.

Transfers have unique PID/exit/log/plan files. Stop never sweeps processes by repo.
No stage's weights are copied through the lead; only small plans travel by SSH.
"""
from __future__ import annotations
import json
from pathlib import Path
import shlex
import subprocess
import time
import threading
import uuid

import web_nodes
import web_picker
from model_files import repo_name


def rp(path):
    return '"$HOME"/' + shlex.quote(path[2:]) if path.startswith('~/') else shlex.quote(path)


def model_dest(node, repo):
    return (node.get('model_root') or '~/.caravan/mlx-models').rstrip('/') + '/' + repo.replace('/','--')


def command(app, node, args):
    script = str(Path(app.mgr.repo)/'agent'/'model_files.py') if web_nodes.is_local(node) else (node.get('repo') or '~/cv3') + '/agent/model_files.py'
    python = (getattr(app.mgr, 'python', None) if web_nodes.is_local(node) else node.get('python')) or '~/.caravan/venvs/mlx/bin/python'
    return ' '.join([rp(str(python)), rp(script)] + [shlex.quote(str(a)) for a in args])


def shell(app, node, cmd, timeout=60):
    if web_nodes.is_local(node):
        return subprocess.run(['bash', '-lc', cmd], capture_output=True, text=True, timeout=timeout)
    return app._ssh_fn()(node, cmd, timeout=timeout)


def inspect_node(app, node, path):
    from model_files import inspect
    if web_nodes.is_local(node):
        return inspect(path)
    r = shell(app, node, command(app, node, ['--inspect-json', json.dumps({'path': path})]))
    if r.returncode:
        raise ValueError(f"Cannot inspect files on {node['id']}: {(r.stderr or r.stdout or '')[-300:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def cancel(app, job):
    results = []
    configured = {n['id']: n for n in app.configured_nodes()}
    for transfer in job.get('file_transfers') or []:
        node = configured.get(transfer['id'])
        token = transfer['token']
        if not node or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
            continue
        # Verify argv, including the unique job marker, on the target before TERM.
        code = """import os,signal,subprocess,shlex,sys
from pathlib import Path
p=Path.home()/'.caravan/transfers'/('%s.pid'%sys.argv[1])
if p.is_file():
 pid=int(p.read_text()); cmd=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
 a=shlex.split(cmd)
 if '--job' in a and a[a.index('--job')+1]==sys.argv[1] and any(x.endswith('/agent/model_files.py') for x in a):
  os.kill(pid,signal.SIGTERM)
"""
        r = shell(app, node, 'python3 -c ' + shlex.quote(code) + ' ' + shlex.quote(token))
        results.append({'id': node['id'], 'ok': r.returncode == 0})
    return {'ok': all(r['ok'] for r in results), 'nodes': results}


def active(app,node):
    r=shell(app,node,command(app,node,['--list-transfers']))
    if r.returncode: raise ValueError('Cannot check active transfers on '+node['id']+'; update/check this Mini before fetching')
    return [t for t in json.loads(r.stdout.strip().splitlines()[-1]) if t.get('node_id') in (None,node['id'])]


def orphans(app, known):
    found={}
    for node in app.configured_nodes():
        try: items=active(app,node)
        except Exception: continue  # display is best-effort; start() fails closed
        for t in items:
            if t['repo_id'] in known: continue
            group=found.setdefault(t['repo_id'],{'progress':{},'transfers':[]})
            group['progress'][node['id']]={'label':node.get('label') or node['id'],'role':node.get('role'), 'pct':0,'msg':'owned transfer still running after web restart; see transfer log','source':'unknown'}
            group['transfers'].append({'id':node['id'],'token':t['token']})
    return [dict(id='files-live-'+repo.replace('/','--'),repo_id=repo,status='running',orphan=True,file_mode=True,
                 progress=g['progress'],file_transfers=g['transfers'],note='Active file transfer rediscovered; no automatic reload') for repo,g in found.items()]


_start_lock = threading.Lock()


def start(app, plan):
    """Serialize duplicate checks + registration; parallel HTTP clicks cannot race."""
    with _start_lock:
        return _start_locked(app,plan)


def _start_locked(app, plan):
    """Explicit Fetch button. Revalidated preview supplied by the server, not client."""
    repo = repo_name(plan['repo_id'])
    if any(j.get('repo_id') == repo and j.get('status') in ('queued', 'running', 'cancelling') for j in web_picker.list_jobs()):
        raise ValueError('a download for this repository is already running; wait or stop it first')
    discover = getattr(app,'list_orphan_fetch_jobs',None)
    if discover and any(j.get('repo_id')==repo for j in discover()):
        raise ValueError('an untracked download for this repository is still running; stop/wait before fetching')
    requests = [dict(r) for r in plan['file_requests']]
    # One immutable revision for the WHOLE job, not independently resolved main
    # on each Mini (the source can publish new weights during a long download).
    if requests and requests[0].get('format') != 'gguf':
        revisions = {r.get('revision') for r in requests}
        if len(revisions) != 1 or not next(iter(revisions)):
            from huggingface_hub import HfApi
            from mlx_split_fetch import _resolve_token
            revision = HfApi(token=_resolve_token()).model_info(repo).sha
            if not revision: raise ValueError('source revision is unknown')
            for r in requests: r['revision'] = revision
    by_id = {n['id']: n for n in app.configured_nodes()}
    destinations = set()
    for stage, r in zip(plan['stages'], requests):
        n = by_id[stage['id']]
        physical = n.get('physical_id') or n.get('ssh') or n.get('host') or 'local'
        if physical in ('local','localhost','127.0.0.1'): physical='local'
        key=(physical,r.get('dest'))
        if key in destinations:
            raise ValueError('simulated Minis on one host need separate model_root folders; nothing started')
        destinations.add(key)
    for stage in plan['stages']:
        if any(t['repo_id']==repo for t in active(app,by_id[stage['id']])):
            raise ValueError('an owned transfer is still running on '+stage['id']+'; stop/wait before starting another')
    placement = {'mode': 'split', 'node_ids': plan['node_ids'], 'layer_plan': plan['counts'],
                 'split_counts': plan['counts'], 'n_stages': len(plan['counts']),
                 'node_labels': [s['label'] for s in plan['stages']]}
    if len(plan['counts']) == 2 and requests[0].get('format') != 'gguf':
        placement['packer_layers'] = plan['counts'][0]
    transfers, runners = [], []
    # Include all stages so a completed job saves the exact same placement everywhere.
    for stage, request in zip(plan['stages'], requests):
        node = by_id[stage['id']]
        request.update(node_id=stage['id'],placement=placement)
        if stage.get('downloads') is None:
            raise ValueError(f"Files unknown on {stage['id']}; refresh before fetching")
        if request.get('format') == 'gguf' and node.get('role') == 'lead':
            continue  # llama.cpp still needs the existing complete lead file
        token = uuid.uuid4().hex
        transfers.append({'id': stage['id'], 'token': token})
        def run(repo_id, dest, pk, prog, node=node, request=request, token=token):
            base = '~/.caravan/transfers/' + token
            blob = json.dumps(request, separators=(',', ':'))
            r = shell(app, node, 'mkdir -p ~/.caravan/transfers; : > ' + rp(base+'.json'))
            if r.returncode: raise RuntimeError('cannot prepare transfer plan')
            # Bound each SSH command even for large MoE tensor manifests.
            for i in range(0, len(blob), 24000):
                r = shell(app, node, 'printf %s ' + shlex.quote(blob[i:i+24000]) + ' >> ' + rp(base+'.json'))
                if r.returncode: raise RuntimeError('cannot write transfer plan')
            cmd = command(app, node, ['--fetch-plan', str(base+'.json'), '--job', token])
            # The subshell records the real exit code; a vanished PID is NOT success.
            inner = cmd + ' & child=$!; printf %s "$child" > ' + rp(base+'.pid') + '; wait "$child"; rc=$?; printf %s "$rc" > ' + rp(base+'.exit')
            launch = 'nohup bash -c ' + shlex.quote(inner) + ' > ' + rp(base+'.log') + ' 2>&1 < /dev/null &'

            r = shell(app, node, launch)
            if r.returncode: raise RuntimeError('could not start file transfer')
            lost = 0
            while True:
                prog(1, 'fetching this Mini’s own files from source')  # checks cancellation
                code = """from pathlib import Path
import json,os,sys
b=Path.home()/'.caravan/transfers'/sys.argv[1]
e=b.with_suffix('.exit'); p=b.with_suffix('.pid')
pid=int(p.read_text()) if p.exists() else None
alive=None
if pid:
 try: os.kill(pid,0); alive=True
 except ProcessLookupError: alive=False
print(json.dumps({'exit':e.read_text() if e.exists() else None,'alive':alive,'pid':pid,'log':b.with_suffix('.log').read_text()[-1200:] if b.with_suffix('.log').exists() else ''}))
"""
                r = shell(app, node, 'python3 -c '+shlex.quote(code)+' '+token)
                if r.returncode: raise RuntimeError('lost transfer status; inspect ~/.caravan/transfers/'+token+'.log')
                status = json.loads(r.stdout.strip().splitlines()[-1])
                if status['exit'] is not None:
                    if status['exit'].strip() != '0': raise RuntimeError(status['log'] or 'stage fetch failed')
                    break
                lost = lost+1 if not status.get('alive') else 0
                if lost >= 5:
                    raise RuntimeError('transfer disappeared without an exit result; inspect its log, not marked complete')
                time.sleep(1)
            prog(100, 'verified complete')
        def save(blob, node=node, request=request):
            # GGUF caches have their own manifest and do not change MLX placement.
            if request.get('format') == 'gguf': return
            code = "from pathlib import Path; import json,sys; p=Path(sys.argv[1]).expanduser()/'caravan-placement.json'; p.write_text(sys.argv[2])"
            r = shell(app, node, 'python3 -c '+shlex.quote(code)+' '+rp(request['dest'])+' '+shlex.quote(json.dumps(blob)))
            if r.returncode: raise RuntimeError('could not save stage placement')
        def measure(node=node, request=request, token=token):
            # This counts bytes on this Mini, not network traffic or another node's files.
            if request.get('format') == 'gguf':
                r = shell(app, node, command(app,node,['--status-plan','~/.caravan/transfers/'+token+'.json']))
                if r.returncode: return {'have_bytes':0,'source':'starting'}
                current=json.loads(r.stdout.strip().splitlines()[-1])
                have=current['required_bytes']-current['download_bytes']
                return {'have_bytes':have,'disk_have':have,'source':'tensor-cache'}
            inv = inspect_node(app, node, request['dest'])
            have = sum(max(inv['files'].get(f, 0), inv['files'].get('.cache/huggingface/download/'+f+'.incomplete', 0)) for f in request['required_files'])
            return {'have_bytes': have, 'disk_have': have, 'source': 'disk'}
        runners.append({'id': stage['id'], 'label': stage['label'], 'role': node.get('role'),
                        'dest': request.get('dest') or '~/.caravan/transfers', 'run': run,
                        'measure': measure, 'total_bytes': stage.get('required_bytes'), 'save_placement': save})
    if not runners: raise ValueError('no peer files to fetch')
    job = web_picker.start_download(repo, runners=runners, placement=placement, note='Own files only; retained files are never deleted')
    web_picker._job_set(job['id'], file_mode=True, file_transfers=transfers,
                        request={'file_fetch': True, 'model_id': plan['model_id'], 'counts': plan['counts'], 'node_ids': plan['node_ids'], 'repo_id': repo, 'gguf_file': requests[0].get('filename')})
    return web_picker.get_job(job['id'])


def prepare_new_mlx(app, repo, nodes, counts=None):
    """N-stage legacy picker bridge, using the exact Balance/file contract."""
    from huggingface_hub import HfApi, snapshot_download
    from mlx_split_fetch import _resolve_token, n_layers_of
    from model_files import plan_digest
    import split_balance as SB
    import tempfile
    repo_name(repo)
    token = _resolve_token()
    info = HfApi(token=token).model_info(repo, files_metadata=True)
    if not info.sha: raise ValueError('source revision is unknown')
    sizes = {s.rfilename: int(s.size or 0) for s in info.siblings}
    with tempfile.TemporaryDirectory(prefix='caravan-preview-') as tmp:
        snapshot_download(repo, revision=info.sha, local_dir=tmp, token=token,
                          allow_patterns=['config.json', 'model.safetensors.index.json'])
        cfg = json.loads((Path(tmp)/'config.json').read_text())
        idx = json.loads((Path(tmp)/'model.safetensors.index.json').read_text())
    nodes = SB.pipeline_order(nodes)
    if len(nodes) != len({n['id'] for n in nodes}): raise ValueError('duplicate Mini IDs')
    inventories, requests = {}, []
    for n in nodes:
        dest = model_dest(n, repo)
        usage = inspect_node(app, n, dest)
        inventories[n['id']] = {'storage': usage, 'has_config': 'config.json' in (usage['files'] or {}),
                                'has_index': 'model.safetensors.index.json' in (usage['files'] or {}),
                                'has_tokenizer': any(f in (usage['files'] or {}) for f in ('tokenizer.json','tokenizer.model','tokenizer.tiktoken','vocab.json','spiece.model'))}
        requests.append({'format': 'mlx', 'repo_id': repo, 'dest': dest, 'metadata_digest': plan_digest(cfg, idx), 'revision': info.sha})
    weights = sum(sizes[f] for f in set(idx['weight_map'].values())) / 1e9
    out = SB.preview(n_layers_of(cfg), weights, nodes, counts, config=cfg, index=idx, sizes=sizes, inventories=inventories)
    if not out['safe']: raise ValueError('this split leaves too little memory; choose fewer layers/a smaller model')
    for i, r in enumerate(requests):
        r.update(counts=out['counts'], stage_index=i, required_files=out['stages'][i]['required_files'])
    out.update(repo_id=repo, model_id=repo, node_ids=[n['id'] for n in nodes], file_requests=requests)
    return out
