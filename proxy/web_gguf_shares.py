"""First-class picker/catalog bridge for strict, independently downloaded GGUF shares."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import uuid

import web_files
import web_nodes
import gguf_share_download as D
import gguf_shards as S

REGISTRY=Path.home()/'.caravan/gguf-models'
from gguf_runtime import current as runtime_bin


def nodes_for(app,body):
    configured=app.configured_nodes();ids=body.get('node_ids')
    if ids is not None:
        if not isinstance(ids,list) or len(ids)!=len(set(ids)) or not set(ids)<={n['id'] for n in configured}:raise ValueError('unknown/duplicate node IDs')
        configured=[next(n for n in configured if n['id']==i) for i in ids]
    nodes=[n for n in configured if n.get('role')=='lead']+[n for n in configured if n.get('role')!='lead']
    if not nodes or sum(n.get('role')=='lead' for n in nodes)!=1 or not web_nodes.is_local(nodes[0]):raise ValueError('a local 1st node is required')
    physical=[n.get('physical_id') or ('local' if web_nodes.is_local(n) else n.get('ssh') or n.get('host')) for n in nodes]
    if len(set(physical))!=len(nodes):raise ValueError('each share needs a distinct physical node')
    return nodes


def invoke(app,node,action,payload):
    """Only metadata travels by SSH; chunked argv stays below platform limits."""
    token='meta-'+uuid.uuid4().hex;path='~/.caravan/transfers/'+token+'.json'
    blob=json.dumps(payload,separators=(',',':'))
    r=web_files.shell(app,node,'mkdir -p ~/.caravan/transfers; : > '+web_files.rp(path))
    if r.returncode:raise RuntimeError('cannot write share metadata')
    for i in range(0,len(blob),24000):
        r=web_files.shell(app,node,'printf %s '+shlex.quote(blob[i:i+24000])+' >> '+web_files.rp(path))
        if r.returncode:raise RuntimeError('cannot write share metadata chunk')
    repo=str(app.mgr.repo) if web_nodes.is_local(node) else node.get('repo') or '~/cv3'
    py=app.mgr.python if web_nodes.is_local(node) else node.get('python') or '~/.caravan/venvs/mlx/bin/python'
    code='''import json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).expanduser()/'agent'))
import gguf_share_download as D,gguf_shards as S
p=json.loads(Path(sys.argv[2]).expanduser().read_text());action=sys.argv[3]
if action=='status':out=D.status(p)
elif action=='receipt':out=json.loads((D._root(p)/'receipt.json').read_text())
elif action=='finalize':out=D.finalize(p,p.pop('receipts'))
elif action in ('existing','save-plan'):
 root=Path(p['root']).expanduser()
 allowed=[Path.home()/'.caravan/day22-shards',Path.home()/'.caravan/gguf-shares']
 if not any(root.resolve().is_relative_to(a.resolve()) for a in allowed) or any(x.is_symlink() for x in [root,*root.parents]):raise ValueError('unmanaged shard root')
 out=S.verify(root)
 if action=='existing':
  m=json.loads((root/'manifest.json').read_text());b=(root/'model.cvgg').read_bytes()[len(S.MAGIC):]
  out.update(manifest=m,data_offset=len(b),header_sha256=hashlib.sha256(b).hexdigest())
 else:D.atomic(root/'source-plan.json',p['plan'])
else:raise ValueError('unknown metadata operation')
print(json.dumps(out),flush=True)
'''
    cmd=web_files.rp(py)+' -c '+shlex.quote(code)+' '+web_files.rp(repo)+' '+web_files.rp(path)+' '+shlex.quote(action)
    r=web_files.shell(app,node,cmd,timeout=300)
    if r.returncode:raise ValueError((r.stderr or r.stdout)[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def model_id(p):return 'gguf-shards/'+p['repo_id']+'/'+p['filename']


def save_deployment(p,roots):
    REGISTRY.mkdir(parents=True,exist_ok=True)
    record=dict(model_id=model_id(p),roots=roots,node_ids=p['node_ids'],shares=p['shares'],plan_id=p['plan_id'],source={k:p[k] for k in ('repo_id','filename','revision','source_sha256','source_bytes')})
    path=REGISTRY/(hashlib.sha256(record['model_id'].encode()).hexdigest()+'.json')
    D.atomic(path,record)
    return record


def entries(nodes,current=None):
    out=[];ids={n['id'] for n in nodes if not n.get('offline') and not n.get('error')}
    for file in sorted(REGISTRY.glob('*.json')):
        if file.is_symlink():continue
        try:
            r=json.loads(file.read_text());p=r['source'];ready=set(r['node_ids'])<=ids and (Path(r['roots'][0]).expanduser()/'manifest.json').is_file()
            opt=dict(id='own-parts',mode='split' if len(r['node_ids'])>1 else 'one',node_ids=r['node_ids'],enabled=ready,label='Split across your Macs: each keeps only its part',reason='' if ready else 'A required node or its share is unavailable')
            out.append(dict(id=r['model_id'],name=Path(p['filename']).stem+' (GGUF)',hf=p['repo_id'],source='gguf',backend='llama',lead_path=str(Path(r['roots'][0]).expanduser()/'model.cvgg'),size_gb=p['source_bytes']/1e9,usable=ready,available_lead=True,disabled_reason=opt['reason'],placement_options=[opt],default_placement=opt['id'],placement=dict(mode=opt['mode'],node_ids=r['node_ids']),current=current==r['model_id'],sharded=True,gguf_deployment=r,gguf_shares=r['shares'],gguf_peer_files_ready=True,note=opt['label'],run_mode='split' if len(r['node_ids'])>1 else 'single'))
        except (OSError,ValueError,KeyError,TypeError):continue
    return out


def preview(app,body,entry=None,fresh=False):
    if entry and entry.get('sharded') and body.get('node_ids') is None:body=dict(body,node_ids=entry['gguf_deployment']['node_ids'])
    nodes=nodes_for(app,body);ids=[n['id'] for n in nodes]
    if entry and entry.get('sharded'):
        dep=entry['gguf_deployment'];p=json.loads((Path(dep['roots'][0]).expanduser()/'source-plan.json').read_text())
        counts=D.shares(body.get('counts') or dep['shares'])
        same=counts==dep['shares'] and ids==dep['node_ids']
        p=dict(p,shares=counts,node_ids=ids)
        own=S.owners(p['n_layers'],counts,[t['name'] for t in p['tensors']]);p['tensors']=[dict(t,owner=own[t['name']]) for t in p['tensors']]
        p['plan_id']=hashlib.sha256(json.dumps([p['source_sha256'],counts,ids],sort_keys=True).encode()).hexdigest()[:24]
        roots=dep['roots'] if same else [D.stage_root(p,i) for i in range(len(nodes))]
    else:
        counts=D.shares(body.get('counts') or [1]*len(nodes));same=False
        if len(counts)!=len(nodes):raise ValueError('one share per node is required')
        p=D.prepare(body['repo_id'],body['gguf_file'],counts,ids,revision=body.get('revision'))
        roots=[D.stage_root(p,i) for i in range(len(nodes))]
    if len(counts)!=len(nodes):raise ValueError('one share per node is required')
    stages=[];requests=[]
    live={n['id']:n for n in (app.nodes() or {}).get('nodes',[])}
    for i,n in enumerate(nodes):
        request=dict(format=D.FORMAT,repo_id=p['repo_id'],filename=p['filename'],revision=p['revision'],manifest=p,counts=counts,stage_index=i,dest=roots[i],runtime_required=True)
        if same:
            checked=invoke(app,n,'existing',dict(root=roots[i]));total=sum(t['size'] for t in p['tensors'] if t['owner']==i)
            st=dict(downloads=[],download_bytes=0,required_bytes=total,on_disk_bytes=checked['logical_bytes'],allocated_bytes=checked['allocated_bytes'],not_needed_for_plan=[],cache_scope='verified own pieces')
        else:st=invoke(app,n,'status',request)
        stats=web_nodes.gather_node_stats(n,ssh_fn=app._ssh_fn()) if fresh else live.get(n['id'],{})
        free=(stats.get('ram') or {}).get('available_gb');active=stats.get('active_gb') or stats.get('weights_gb') or 0
        estimate=st['required_bytes']/1e9+1.3
        headroom=None if free is None else float(free)+float(active)-estimate
        safe=headroom is not None and headroom>=1.75
        stages.append(dict(st,id=n['id'],label=n.get('label') or n['id'],role=n['role'],range=[0,p['n_layers']],layers=counts[i],estimated_use_gb=estimate,headroom_gb=headroom,safe=safe,metadata_ready=True))
        requests.append(request)
    safe=all(s['safe'] for s in stages);ready=safe and all(not s['downloads'] for s in stages) and (same or all((s.get('assembled') is True) for s in stages))
    record=dict(model_id=model_id(p),roots=roots,node_ids=ids,shares=counts,plan_id=p['plan_id'],source={k:p[k] for k in ('repo_id','filename','revision','source_sha256','source_bytes')})
    e=dict(entry or {},id=model_id(p),name=Path(p['filename']).stem+' (GGUF)',source='gguf',sharded=True,lead_path=str(Path(roots[0]).expanduser()/'model.cvgg'),gguf_deployment=record,gguf_shares=counts,gguf_peer_files_ready=ready,placement=dict(mode='split' if len(nodes)>1 else 'one',node_ids=ids))
    return dict(format='gguf',own_shares=True,repo_id=p['repo_id'],model_id=model_id(p),counts=counts,node_ids=ids,safe=safe,ready=ready,margin_gb=1.75,mode='manual' if body.get('counts') else 'auto',stages=stages,file_requests=requests,entry=e,note='Each Mac downloads only its part straight from the source. No full copy and no weight transfer over the cable.',manifest=p,roots=roots)


def finalize(app,plan):
    byid={n['id']:n for n in app.configured_nodes()};requests=plan['file_requests']
    receipts=[invoke(app,byid[n],'receipt',r) for n,r in zip(plan['node_ids'],requests)]
    for n,r in zip(plan['node_ids'],requests):invoke(app,byid[n],'finalize',dict(r,receipts=receipts))
    save_deployment(plan['manifest'],plan['roots'])


def import_existing(app,body):
    import re
    name=body.get('tree','')
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*',name):raise ValueError('select a named legacy shard tree')
    nodes=nodes_for(app,body);root='~/.caravan/day22-shards/'+name
    checks=[invoke(app,n,'existing',dict(root=root)) for n in nodes];m=checks[0]['manifest']
    src=D.source(body['repo_id'],body['gguf_file'],body.get('revision'))
    if src['source_sha256']!=m['source_sha256'] or src['source_bytes']!=m['source_bytes']:raise ValueError('legacy source does not match')
    ids=[n['id'] for n in nodes]
    if len(nodes)!=len(m['shares']):raise ValueError('legacy share count differs from nodes')
    for i,c in enumerate(checks):
        if c['stage_index']!=i or c['source_sha256']!=m['source_sha256'] or c['manifest']['tensors']!=m['tensors'] or c['header_sha256']!=checks[0]['header_sha256']:raise ValueError('legacy stage binding differs')
    p=dict(src,n_layers=m['n_layers'],data_offset=checks[0]['data_offset'],tensors=m['tensors'],shares=m['shares'],node_ids=ids,header_sha256=checks[0]['header_sha256'])
    p['plan_id']=hashlib.sha256(json.dumps([p['source_sha256'],p['shares'],ids],sort_keys=True).encode()).hexdigest()[:24]
    for n in nodes:invoke(app,n,'save-plan',dict(root=root,plan=p))
    return save_deployment(p,[root]*len(nodes))


def peer_start_code(root,port):
    return '''import json,os,subprocess,time
from pathlib import Path
import gguf_shards as S
from gguf_runtime import current
root=Path(ROOT).expanduser();binary=current()/'ggml-rpc-server'
args,env=S.serving_command(root,binary,peer=True,port=PORT)
r=subprocess.run(['lsof','-nP','-iTCP:'+str(PORT),'-sTCP:LISTEN'],capture_output=True,text=True)
if r.returncode==0:raise RuntimeError('RPC port busy; nothing was stopped')
log=Path.home()/'.caravan/web-ui/gguf-shard-peer.log';log.parent.mkdir(parents=True,exist_ok=True)
with log.open('ab') as f:p=subprocess.Popen(args,env=dict(os.environ,**env),stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
try:
 for _ in range(150):
  if p.poll() is not None:raise RuntimeError('own-piece RPC server exited')
  r=subprocess.run(['lsof','-a','-p',str(p.pid),'-nP','-iTCP:'+str(PORT),'-sTCP:LISTEN'],capture_output=True,text=True)
  if r.returncode==0:break
  time.sleep(0.1)
 else:raise RuntimeError('own-piece RPC server did not listen')
except BaseException:
 if p.poll() is None:p.terminate()
 try:p.wait(timeout=5)
 except subprocess.TimeoutExpired:p.kill();p.wait()
 raise
print('PID:'+str(p.pid),flush=True)
print('BIN:'+str(binary),flush=True)
'''.replace('ROOT',repr(root)).replace('PORT',str(port))


def stop_peer(mgr,peer):
    code='''import os,signal,subprocess
p=PID
cmd=subprocess.run(['ps','-ww','-p',str(p),'-o','command='],capture_output=True,text=True).stdout
if BINARY in cmd and '-p PORT' in cmd:
 os.kill(p,signal.SIGTERM)
'''.replace('PID',str(int(peer['pid']))).replace('BINARY',repr(peer['binary'])).replace('PORT',str(peer['port']))
    r=mgr._ssh_node(peer['node'],'python3 -c '+shlex.quote(code),timeout=30)
    if r.returncode:raise RuntimeError('could not stop owned share peer')



def tunnel_args(n,lp):
    import gguf_split as G
    target=n.get('ssh') or n.get('host');args=G.ssh_tunnel_args(target,lp)
    # Existing MLX peer addresses may provide a link-local data route. Keep
    # the configured SSH identity as the host-key anchor, never accept a key.
    import ipaddress
    endpoint=n.get('peer') or '';host=endpoint.rsplit(':',1)[0];verified_tb=False
    if endpoint.startswith('ssh+tb://'):
        from service_endpoints import parse,resolve
        spec=parse(endpoint)
        if spec[0]!=target:raise ValueError('Thunderbolt and SSH identity differ')
        host=resolve(endpoint).rsplit(':',1)[0];verified_tb=True
    try:link=verified_tb or ipaddress.ip_address(host).is_link_local
    except ValueError:link=False
    args[1:1]=['-o','StrictHostKeyChecking=yes']
    if link:args[1:1]=['-o','HostName='+host,'-o','HostKeyAlias='+target.rsplit('@',1)[-1]]
    return args


def load(mgr,entry,settings):
    import gguf_split as G
    dep=entry['gguf_deployment'];nodes=mgr._gguf_nodes(dict(node_ids=dep['node_ids']));roots=dep['roots']
    if [n['id'] for n in nodes]!=dep['node_ids']:raise ValueError('configured stage order differs from saved shard plan')
    # Verify local pieces and runtime before disturbing the previous model.
    S.serving_command(roots[0],runtime_bin()/'llama-server',port=mgr.lead_port,rpc=[f'127.0.0.1:{G.tunnel_port(i)}' for i in range(len(nodes)-1)])
    for i,n in enumerate(nodes[1:]):
        repo=n.get('repo') or '~/cv3';py=n.get('python') or '~/.caravan/venvs/mlx/bin/python'
        code='import sys;from pathlib import Path;sys.path.insert(0,str(Path('+repr(repo)+').expanduser()/"agent"));import gguf_shards as S;from gguf_runtime import current;S.serving_command('+repr(roots[i+1])+',current()/"ggml-rpc-server",peer=True,port='+str(G.RPC_PORT)+');print("verified")'
        result=mgr._ssh_node(n,web_files.rp(py)+' -c '+shlex.quote(code),timeout=180)
        if result.returncode:raise ValueError('Peer pieces/runtime failed preflight; previous model retained: '+(result.stderr or result.stdout)[-800:])
    mgr._check_load_cancel()
    mgr._gguf_cancel=False;mgr._kill_gguf();mgr._kill_lead();mgr._kill_packer()
    gb=dict(nodes=dep['node_ids'],labels=[n.get('label') for n in nodes],mode='split' if len(nodes)>1 else 'single',shares=dep['shares'],storage='own-parts',own_tensor_bytes=[sum(t['size'] for t in json.loads((Path(roots[0]).expanduser()/'manifest.json').read_text())['tensors'] if t['owner']==i) for i in range(len(nodes))],note='Split across your Macs: each keeps only its part')
    mgr._set(status='starting_packer',model_id=entry['id'],model_name=entry['name'],progress=[],error=None,error_detail=None,backend='llama',gguf=gb,balance=None,model_hf=dep['source']['repo_id'],split=len(nodes)>1)
    meta=dict(lead_pid=None,peers=[],tunnels=[],model=entry['lead_path'],id=entry['id'],name=entry['name'],gguf=gb,entry=entry,sharded=True)
    mgr._write_gguf_meta(meta);rpc=[]
    for i,n in enumerate(nodes[1:]):
        mgr._check_cancel();repo=n.get('repo') or '~/cv3';py=n.get('python') or '~/.caravan/venvs/mlx/bin/python'
        code='import sys;from pathlib import Path;sys.path.insert(0,str(Path('+repr(repo)+').expanduser()/"agent"));'+peer_start_code(roots[i+1],G.RPC_PORT)
        result=mgr._ssh_node(n,web_files.rp(py)+' -c '+shlex.quote(code),timeout=180)
        pid=G.parse_pid(result.stdout)
        if result.returncode or not pid:raise RuntimeError('own-piece peer failed: '+(result.stderr or result.stdout)[-1000:])
        meta['peers'].append(dict(id=n['id'],ssh=n.get('ssh') or n.get('host'),pid=pid,node=n,sharded=True,port=G.RPC_PORT,binary=next(x[4:] for x in result.stdout.splitlines() if x.startswith('BIN:'))));mgr._write_gguf_meta(meta);mgr._check_cancel()
        lp=G.tunnel_port(i);target=n.get('ssh') or n.get('host');args=G.ssh_tunnel_args(target,lp)
        args=tunnel_args(n,lp)
        import socket
        with socket.socket() as probe:
            try:probe.bind(("127.0.0.1",lp))
            except OSError:raise ValueError("RPC tunnel port busy; no existing tunnel was touched")
        tun=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
        meta['tunnels'].append(dict(pid=tun.pid,port=lp,ssh=target,id=n['id'],args=args));mgr._write_gguf_meta(meta)
        if not G.wait_port(lp,proc=tun,timeout=15):raise RuntimeError('own-piece SSH tunnel did not start')
        rpc.append(f'127.0.0.1:{lp}')
    args,env=S.serving_command(roots[0],runtime_bin()/'llama-server',port=mgr.lead_port,rpc=rpc)
    mgr._note(gb['note']+'; missing pieces are errors, never cable-transfer fallbacks')
    mgr._set(status='starting_lead');lf=open(mgr._lead_log(),'ab',buffering=0);mgr._worker_node=None
    mgr._lead_proc=subprocess.Popen(args,env=dict(os.environ,**env),stdout=lf,stderr=subprocess.STDOUT,start_new_session=True);lf.close()
    meta['lead_pid']=mgr._lead_proc.pid;mgr._write_gguf_meta(meta);mgr._set(lead_pid=mgr._lead_proc.pid)
    t=time.monotonic();mgr._wait_lead_ready(timeout=300);mgr._check_cancel();mgr._loaded_entry=dict(entry)
    save_deployment(json.loads((Path(roots[0]).expanduser()/'source-plan.json').read_text()),roots)
    mgr._set(status='ready',split=len(nodes)>1);mgr._note(f'own parts ready in {time.monotonic()-t:.3f}s');mgr._start_gguf_watch(meta)
