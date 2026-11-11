"""Fail-closed removal of the ONE explicitly approved Day22 full GGUF.

No pruning, globbing, symlink traversal, trash fallback, or automatic picker
cleanup. A fresh all-stage live proof and every Mini's dry-run receipt are
required. All other model files remain outside this command's allowlist.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import time
import urllib.request
from zoneinfo import ZoneInfo

import gguf_shards as shards

NAME = 'qwen2.5-3b-instruct-q4_0.gguf'
PARENT = 'Qwen--Qwen2.5-3B-Instruct-GGUF'
REPO = 'Qwen/Qwen2.5-3B-Instruct-GGUF'
SHA = '670d82d0fbee6289b661eb323612c65bd2e97ec8c65cdbd9131aa44d30e9816a'
SIZE = 1997879712
BASELINE = 'b9c24870c82af3fee514b65739bed72b46c61903fec4a8ba49417534e5c5f2c7'
HUIHUI = 'huihui-qwen3-5-27b-claude-4-6-opus-abliterated-4bit'
PIN = '76a67730ffc7d650dffa4db04d96be84a59e7ef3'
PROOF_AGE_S = 300
BATCH_AGE_S = 120


class GateError(ValueError): pass


class RemovedButAuditFailed(RuntimeError):
    def __init__(self,result,error):
        self.result=result
        super().__init__('original was removed; final audit append failed: '+str(error))


def require(ok, message):
    if not ok: raise GateError(message)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def stamp(st):
    return dict(dev=st.st_dev,ino=st.st_ino,size=st.st_size,mtime_ns=st.st_mtime_ns,
                ctime_ns=st.st_ctime_ns,nlink=st.st_nlink,allocated_bytes=st.st_blocks*512)


def read_json(path):
    p=Path(path)
    require(not p.is_symlink(),'linked evidence refused')
    return json.loads(p.read_text())


def remote_source(record):
    """Read public immutable Hub metadata; never download another full original."""
    url='https://huggingface.co/api/models/'+REPO+'/revision/'+record['revision']+'?blobs=true'
    with urllib.request.urlopen(url,timeout=30) as r:
        data=json.load(r)
    require(data.get('sha')==record['revision'] and data.get('id')==REPO,'source revision unavailable or changed')
    require(not data.get('private') and not data.get('gated'),'recovery source must remain publicly available')
    entry=next((s for s in data.get('siblings',[]) if s.get('rfilename')==NAME),{})
    require(entry.get('size')==SIZE and entry.get('lfs',{}).get('sha256')==SHA,
            'immutable source metadata does not match the original')
    return dict(url=url,revision=data['sha'],sha256=SHA,size=SIZE)


def validate_source(record,manifest,fetch=remote_source):
    require(record.get('repo_id')==REPO and record.get('filename')==NAME,'source outside approved model')
    require(bool(re.fullmatch('[0-9a-f]{40}',record.get('revision',''))),'immutable source revision required')
    require(record.get('sha256')==SHA and record.get('size')==SIZE,'source checksum/size outside approved model')
    require(manifest.get('source_name')==NAME and manifest.get('source_sha256')==SHA and manifest.get('source_bytes')==SIZE,
            'catalog is not for the approved original')
    fetch(record)
    return 'https://huggingface.co/'+REPO+'/resolve/'+record['revision']+'/'+NAME


def production_state(status):
    w=status.get('worker') or {}; restore=status.get('restore') or {}
    # This operation is deliberately narrower than a general cleanup command.
    require(w.get('status')=='ready' and w.get('model_id')==HUIHUI,
            'production model is not the protected ready Huihui MLX selection')
    require(restore.get('last_model')==HUIHUI,'saved restore selection is not protected Huihui MLX')
    require((w.get('balance') or {}).get('counts')==[24,40] and (status.get('active') or {}).get('kv_bits')==16,
            'protected Huihui split/settings changed')
    return dict(model_id=w['model_id'],restore_model=restore['last_model'],pid=w.get('lead_pid'),counts=[24,40],kv_bits=16)


def query_status(url):
    require(url.startswith('http://') and url.endswith('/api/status'),'explicit live Caravan status endpoint required')
    with urllib.request.urlopen(url,timeout=20) as r:return json.load(r)


def process_identity(pid):
    require(type(pid) is int and pid>1,'invalid live process PID')
    p=subprocess.run(['ps','-ww','-p',str(pid),'-o','command='],capture_output=True,text=True,timeout=10)
    require(p.returncode==0 and p.stdout.strip(),'fresh shard process is no longer running')
    start=subprocess.run(['ps','-p',str(pid),'-o','lstart='],capture_output=True,text=True,timeout=10)
    require(start.returncode==0 and start.stdout.strip(),'cannot identify fresh shard process start')
    return dict(command=p.stdout.strip(),started=start.stdout.strip())


def no_open_file(source):
    p=subprocess.run(['lsof','-F','pn','--',str(source)],capture_output=True,text=True,timeout=30)
    require(p.returncode in (0,1) and not p.stderr.strip(),'cannot establish complete open-file check: '+p.stderr.strip())
    require(p.returncode==1 and not p.stdout.strip(),'a running process has the original open: '+p.stdout.strip())
    return True


def stage_binding(root,pid,binary,native_loads):
    """Bind one actual Mini's checked disk pieces/process to native load records."""
    root=Path(root).expanduser().absolute();shards.verify(root)
    m=read_json(root/'manifest.json');idx=m['stage_index']
    mine={t['name']:t['size'] for t in m['tensors'] if t['owner']==idx}
    rows=[t for t in native_loads if t['name'] in mine]
    require(len(rows)==len(mine) and {t['name']:t['size'] for t in rows}==mine,
            "native callbacks do not match this Mini's complete tensor set")
    expected_location='local' if idx==0 else 'remote-local'
    require(all(t['location']==expected_location for t in rows),'tensor was loaded on the wrong side')
    return dict(index=idx,root=str(root),manifest_sha256=shards.digest(root/'manifest.json'),
                catalog_sha256=m['catalog_sha256'],loaded_tensors=len(rows),loaded_bytes=sum(mine.values()),
                loaded_names_sha256=hashlib.sha256('\n'.join(sorted(mine)).encode()).hexdigest(),
                pid=pid,binary=str(Path(binary).expanduser().absolute()),process=process_identity(pid))


def validate_live(proof,manifest,root,now_ns,process=process_identity):
    require(proof.get('schema')=='caravan-gguf-removal-live-v1','fresh live proof required')
    require(proof.get('source_sha256')==SHA,'live proof belongs to another model')
    require(bool(re.fullmatch('[0-9a-f]{32}',proof.get('transaction',''))),'invalid live transaction')
    created=proof.get('created_ns',0); load=proof.get('load') or {}; chat=proof.get('chat') or {}
    require(type(created) is int and 0<=now_ns-created<=PROOF_AGE_S*10**9,'live proof is stale or future-dated')
    require(load.get('ok') is True and load.get('fresh_process') is True and load.get('runtime_pin')==PIN and
            type(load.get('started_ns')) is int and type(load.get('ready_ns')) is int and
            0<=now_ns-load['started_ns']<=PROOF_AGE_S*10**9 and load['started_ns']<=load['ready_ns']<=created,
            'proof is not a fresh successful catalog-only load')
    require(chat.get('ok') is True and chat.get('text_sha256')==BASELINE and chat.get('completion_tokens')==128 and
            chat.get('prompt_tokens')==55 and chat.get('cache_n')==0 and chat.get('temperature')==0,
            'fresh chat does not match the pinned known-good baseline/settings')
    require(chat.get('started_ns',0)>=load['ready_ns'] and chat.get('finished_ns',0)<=created and
            chat.get('finished_ns',0)>=chat.get('started_ns',0),'chat timing does not follow the fresh load')
    stages=proof.get('stages') or []; n=len(manifest['shares']);idx=manifest['stage_index']
    require(len(stages)==n and {x.get('index') for x in stages}==set(range(n)),'proof must cover every Mini')
    stage=next(x for x in stages if x['index']==idx)
    require(stage.get('root')==str(root) and stage.get('manifest_sha256')==shards.digest(root/'manifest.json') and
            stage.get('catalog_sha256')==manifest['catalog_sha256'],'live proof does not bind this Mini/catalog')
    own=[t for t in manifest['tensors'] if t['owner']==idx]
    names=hashlib.sha256('\n'.join(sorted(t['name'] for t in own)).encode()).hexdigest()
    require(stage.get('loaded_tensors')==len(own) and stage.get('loaded_bytes')==sum(t['size'] for t in own) and
            stage.get('loaded_names_sha256')==names,'native load did not cover exactly this Mini\'s pieces')
    observed=process(stage.get('pid'))
    require(observed==stage.get('process'),'shard process changed or PID was reused')
    args=shlex.split(observed['command']); expected=stage.get('binary','')
    require(args and args[0]==expected and Path(expected).name==('llama-server' if idx==0 else 'ggml-rpc-server'),
            'wrong live shard executable')
    marker=Path(expected).parents[2]/'caravan-shards-version'
    require(marker.is_file() and marker.read_text().strip()=='catalog-v1/'+PIN,'wrong shard runtime marker')
    require(not any(x.endswith('.gguf') for x in args),'live process was given an original GGUF')
    if idx==0:
        require('-m' in args and args[args.index('-m')+1]==str(root/'model.cvgg'),'lead was not loaded from this catalog')
    return dict(transaction=proof['transaction'],proof_sha256=canonical_hash(proof),stage=stage,
                baseline_sha256=BASELINE,created_ns=created)


def preflight(source,root,record,proof,status,*,now_ns=None,fetch=remote_source,process=process_identity,opened=no_open_file):
    now_ns=time.time_ns() if now_ns is None else now_ns
    source=Path(source).expanduser().absolute();root=Path(root).expanduser().absolute()
    require(source.name==NAME and source.parent.name==PARENT,'path is outside the ONE approved original')
    require(source==source.resolve(strict=True),'linked original/path refused')
    before=source.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink==1,'original must be a regular, singly linked file')
    require(before.st_size==SIZE,'original has the wrong size')
    checked=shards.verify(root);m=read_json(root/'manifest.json')
    recovery=validate_source(record,m,fetch)
    prod=production_state(status)
    live=validate_live(proof,m,root,now_ns,process)
    require(shards.digest(source)==SHA,'original SHA256 does not match the approved model')
    after=source.lstat();require(stamp(before)==stamp(after),'original changed during verification')
    opened(source)
    return dict(schema='caravan-gguf-removal-gate-v1',gate_passed=True,checked_ns=now_ns,
                transaction=live['transaction'],proof_sha256=live['proof_sha256'],
                stage_index=m['stage_index'],n_minis=len(m['shares']),root=str(root),
                manifest_sha256=shards.digest(root/'manifest.json'),source_record_sha256=canonical_hash(record),
                production=prod,pieces=checked,recovery_url=recovery,
                will_remove=[dict(path=str(source),sha256=SHA,**stamp(after))])


def validate_batch(batch,gate,now_ns):
    require(batch.get('schema')=='caravan-gguf-removal-batch-v1','all-Mini dry-run batch required')
    receipts=batch.get('gates') or []
    require(len(receipts)==gate['n_minis'] and {r.get('stage_index') for r in receipts}==set(range(gate['n_minis'])),
            'batch must contain one passing dry run per Mini')
    for r in receipts:
        require(r.get('gate_passed') is True and r.get('transaction')==gate['transaction'] and
                r.get('proof_sha256')==gate['proof_sha256'] and r.get('source_record_sha256')==gate['source_record_sha256'] and
                r.get('n_minis')==gate['n_minis'],'not every Mini passed the same source/live transaction')
        require(type(r.get('checked_ns')) is int and 0<=now_ns-r['checked_ns']<=BATCH_AGE_S*10**9,
                'a Mini dry run is stale or future-dated')
        files=r.get('will_remove') or []
        require(len(files)==1 and files[0].get('sha256')==SHA and files[0].get('size')==SIZE and
                Path(files[0].get('path','')).name==NAME and Path(files[0]['path']).parent.name==PARENT,
                'batch contains an unapproved removal')
    old=next(r for r in receipts if r['stage_index']==gate['stage_index'])
    require(old['will_remove']==gate['will_remove'] and old['manifest_sha256']==gate['manifest_sha256'],
            'original or shard manifest changed since the all-Mini dry run')
    return True


def append_journal(path,row):
    path=Path(path).expanduser().absolute()
    require(path.suffix=='.jsonl' and path.parent.is_dir() and path==path.resolve(),'unsafe/missing audit journal path')
    flags=os.O_WRONLY|os.O_CREAT|os.O_APPEND|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags,0o600)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode) and os.fstat(fd).st_nlink==1,'linked/non-regular journal refused')
        data=(json.dumps(row,sort_keys=True)+'\n').encode();view=memoryview(data)
        while view:
            n=os.write(fd,view);require(n>0,'audit write failed');view=view[n:]
        os.fsync(fd)
    finally:os.close(fd)


def available(path):
    st=os.statvfs(path);return st.f_bavail*st.f_frsize


def remove_original(source,root,record,proof,status, batch,journal,**deps):
    gate=preflight(source,root,record,proof,status,**deps)
    validate_batch(batch,gate,time.time_ns())
    src=Path(gate['will_remove'][0]['path']);ident=gate['will_remove'][0]
    # No mutation before ALL gates and the audit intent are durable.
    free_before=available(src.parent)
    row=dict(event='removal-intent',gate=gate,batch_sha256=canonical_hash(batch),available_before=free_before,
             ct=datetime.now(ZoneInfo('America/Chicago')).isoformat())
    append_journal(journal,row)
    directory=os.open(src.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
    try:
        current=os.stat(src.name,dir_fd=directory,follow_symlinks=False)
        require(stamp(current)=={k:ident[k] for k in stamp(current)},'original identity changed immediately before removal')
        # Exactly one basename in the pinned open parent directory; no glob/delete-tree.
        os.unlink(src.name,dir_fd=directory)
        directory_sync_error=None
        try: os.fsync(directory)
        except OSError as e: directory_sync_error=str(e)
    finally:os.close(directory)
    result=dict(event='removed',path=str(src),sha256=SHA,logical_bytes_removed=ident['size'],
                allocated_file_bytes_removed=ident['allocated_bytes'],available_before=free_before,
                available_after=None,transaction=gate['transaction'],stage_index=gate['stage_index'],
                proof_sha256=gate['proof_sha256'],ct=datetime.now(ZoneInfo('America/Chicago')).isoformat())
    try:result['available_after']=available(src.parent)
    except OSError as e:result['available_after_error']=str(e)
    result['observed_available_delta']=result['available_after']-free_before if result['available_after'] is not None else None
    if directory_sync_error:result['directory_sync_error']=directory_sync_error
    try: append_journal(journal,result)
    except Exception as e: raise RemovedButAuditFailed(result,e) from e
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source');ap.add_argument('--root',required=True);ap.add_argument('--source-record',required=True)
    ap.add_argument('--live-proof',required=True);ap.add_argument('--status-url',required=True)
    ap.add_argument('--commit',action='store_true');ap.add_argument('--batch');ap.add_argument('--journal')
    a=ap.parse_args();record=read_json(a.source_record);proof=read_json(a.live_proof)
    try:
        status=query_status(a.status_url)
        if a.commit:
            require(a.batch and a.journal,'commit requires all-Mini dry-run batch and durable journal')
            result=remove_original(a.source,a.root,record,proof,status,read_json(a.batch),a.journal)
        else:result=preflight(a.source,a.root,record,proof,status)
        print(json.dumps(result,sort_keys=True),flush=True)
    except RemovedButAuditFailed as e:
        print(json.dumps(dict(removed=True,result=e.result,error=str(e))),flush=True)
        raise SystemExit(2)
    except Exception as e:
        print(json.dumps(dict(gate_passed=False,removed=False,error=str(e))),flush=True)
        raise SystemExit(1)

if __name__=='__main__':main()
