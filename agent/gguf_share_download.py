"""Pinned-source, own-range-only GGUF preparation. Never downloads a full GGUF.

First download establishes each tensor's SHA256 from HTTPS immutable-source
bytes; later resume, assembly and loads verify it. HF publishes a whole-file
SHA256, not per-tensor hashes: we record that source identity, not a claim to
have recomputed its whole-file digest on a host holding only some tensors.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import time
from fractions import Fraction
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener
from urllib.parse import urlsplit
from urllib.parse import quote

from model_files import repo_name, safe_name
import gguf_shards as shards

FORMAT = 'gguf-shards'
MAX_HEADER = 64 << 20


class UnsupportedLayout(ValueError):
    """Valid model that needs the standard whole-file engine."""


def atomic(path, value):
    path = Path(path)
    if path.is_symlink(): raise ValueError('linked metadata refused')
    tmp = path.with_name(path.name+'.new')
    if tmp.is_symlink(): raise ValueError('linked temporary metadata refused')
    with tmp.open('w') as f:
        json.dump(value, f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def shares(values):
    if not isinstance(values, list) or not values: raise ValueError('one positive share per node required')
    fs=[]
    for x in values:
        if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0: raise ValueError('invalid share')
        fs.append(Fraction(str(x)).limit_denominator(1000))
    den=math.lcm(*(x.denominator for x in fs)); ns=[int(x*den) for x in fs]
    g=math.gcd(*ns); ns=[n//g for n in ns]
    if max(ns)>10**9: raise ValueError('share ratio too large')
    return ns


def source_url(p):
    repo_name(p['repo_id']); safe_name(p['filename'])
    if not p['filename'].endswith('.gguf') or not re.fullmatch('[0-9a-f]{40}',p['revision']): raise ValueError('pinned GGUF source required')
    if not re.fullmatch('[0-9a-f]{64}',p['source_sha256']) or type(p['source_bytes']) is not int or p['source_bytes']<=0: raise ValueError('invalid source identity')
    return 'https://huggingface.co/'+p['repo_id']+'/resolve/'+p['revision']+'/'+quote(p['filename'],safe='/')


def source(repo, filename, revision=None):
    from huggingface_hub import HfApi
    from mlx_split_fetch import _resolve_token
    repo_name(repo);safe_name(filename)
    info=HfApi(token=_resolve_token()).model_info(repo,revision=revision,files_metadata=True)
    file=next((s for s in info.siblings if s.rfilename==filename),None)
    lfs=getattr(file,'lfs',None);sha=lfs.get('sha256') if isinstance(lfs,dict) else getattr(lfs,'sha256',None)
    if file is None or not sha or not file.size: raise ValueError('source must publish exact file size and SHA256')
    out=dict(repo_id=repo,filename=filename,revision=info.sha,source_sha256=sha,source_bytes=file.size)
    source_url(out)
    return out


class SourceRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if urlsplit(newurl).scheme!='https':raise ValueError('insecure source redirect refused')
        out=super().redirect_request(req,fp,code,msg,headers,newurl)
        if out and urlsplit(newurl).netloc!=urlsplit(req.full_url).netloc:out.remove_header('Authorization')
        return out


def response(p,start,end,opener=None):
    if type(start) is not int or type(end) is not int or not 0<=start<=end<p['source_bytes']: raise ValueError('invalid source range')
    headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'}
    if opener is None:
        from mlx_split_fetch import _resolve_token
        token=_resolve_token()
        if token: headers['Authorization']='Bearer '+token
    r=(opener or build_opener(SourceRedirect()).open)(Request(source_url(p),headers=headers),timeout=90)
    want=f'bytes {start}-{end}/{p["source_bytes"]}'
    if r.status!=206 or r.headers.get('Content-Range')!=want or r.headers.get('Content-Encoding','identity') not in ('identity',''):
        r.close();raise ValueError('source ignored/changed HTTP Range; full-file fallback refused')
    return r


def read_range(p,start,size,opener=None):
    with response(p,start,start+size-1,opener) as r:
        b=r.read(size+1)
    if len(b)!=size: raise ValueError('truncated/oversized source range')
    return b


class HeaderReader:
    """Read-ahead is bounded by a proven lower bound on remaining header bytes.

    No speculative prefix request is allowed to reach tensor payloads. Skipped
    tokenizer arrays need only lengths for planning; the final catalog fetch
    subsequently reads the exact metadata span, never the original's weights.
    """
    def __init__(self,p,opener=None):
        self.p=p;self.opener=opener;self.pos=0;self.minimum=0;self.buf=b'';self.start=0;self.bytes=0;self.requests=[]
    def tell(self):return self.pos
    def seek(self,n,whence=0):
        old=self.pos;self.pos=self.pos+n if whence==1 else n
        self.minimum=max(0,self.minimum-max(0,self.pos-old))
        if not 0<=self.pos<=MAX_HEADER:raise ValueError('GGUF header exceeds supported metadata bound')
        return self.pos
    def read(self,n):
        if n<0 or self.pos+n>MAX_HEADER:raise ValueError('invalid header read')
        if not (self.start<=self.pos and self.pos+n<=self.start+len(self.buf)):
            size=max(n,min(256<<10,self.minimum));size=min(size,self.p['source_bytes']-self.pos)
            self.buf=read_range(self.p,self.pos,size,self.opener);self.start=self.pos;self.bytes+=size
            self.requests.append([self.pos,size])
        b=self.buf[self.pos-self.start:self.pos-self.start+n];self.pos+=len(b);self.minimum=max(0,self.minimum-len(b))
        if len(b)!=n:raise ValueError('truncated header')
        return b


def parse_header(f, quant_sizes):
    scalar={0:('B',1),1:('b',1),2:('H',2),3:('h',2),4:('I',4),5:('i',4),6:('f',4),7:('?',1),10:('Q',8),11:('q',8),12:('d',8)}
    def integer(fmt):return struct.unpack('<'+fmt,f.read(struct.calcsize('<'+fmt)))[0]
    def string():
        n=integer('Q')
        if n>MAX_HEADER:raise ValueError('invalid GGUF string')
        return f.read(n).decode('utf-8',errors='strict')
    def val(t,reserve):
        f.minimum=reserve+1
        if t in scalar:
            fmt,size=scalar[t];return integer(fmt)
        if t==8:
            n=integer('Q')
            if n>MAX_HEADER:raise ValueError('invalid metadata string')
            if n<=4096:return f.read(n).decode('utf-8',errors='strict')
            f.seek(n,1);return None
        if t==9:
            et=integer('I');n=integer('Q')
            if n>10**7 or et not in (*scalar,8):raise ValueError('unsupported metadata array')
            if et in scalar:f.seek(n*scalar[et][1],1)
            else:
                for i in range(n):
                    f.minimum=reserve+(n-i)*8
                    length=integer('Q')
                    if length>MAX_HEADER:raise ValueError('invalid array string')
                    f.seek(length,1)
            return None
        raise ValueError('unsupported GGUF metadata type')
    if f.read(4)!=b'GGUF' or integer('I') not in (2,3):raise ValueError('GGUF v2/v3 required')
    nt,nkv=integer('Q'),integer('Q')
    if not 0<nt<100000 or not 0<nkv<100000:raise ValueError('invalid GGUF directory counts')
    meta={}
    for i in range(nkv):
        f.minimum=nt*24+(nkv-i)*13
        key=string();t=integer('I');meta[key]=val(t,nt*24+(nkv-i-1)*13)
    if meta.get('general.architecture') not in ('llama','qwen2'):raise UnsupportedLayout('This model will download as a complete file.')
    if meta.get('split.count',1)!=1:raise UnsupportedLayout('This model has several files; all will be downloaded.')
    layers=[v for k,v in meta.items() if k.endswith('.block_count')]
    if len(layers)!=1 or type(layers[0]) is not int or not 0<layers[0]<=4096:raise ValueError('invalid block count')
    tensors=[]
    for i in range(nt):
        f.minimum=(nt-i)*24
        name=string();nd=integer('I')
        if not re.fullmatch('[A-Za-z0-9_.-]+',name) or not 1<=nd<=4:raise ValueError('unsupported tensor directory')
        dims=[integer('Q') for _ in range(nd)];typ=integer('I');off=integer('Q')
        if typ not in quant_sizes or any(n<=0 for n in dims):raise UnsupportedLayout('This model will download as a complete file.')
        block,size=quant_sizes[typ];n=math.prod(dims)
        if n%block:raise ValueError('tensor is not quant-block aligned')
        if not name.startswith('blk.') and name not in ('token_embd.weight','output_norm.weight','output_norm.bias','output.weight','output.bias'):raise UnsupportedLayout('This model will download as a complete file.')
        tensors.append(dict(name=name,offset=off,size=n//block*size))
    align=meta.get('general.alignment',32)
    if type(align) is not int or align<1 or align>4096 or align&(align-1):raise ValueError('invalid GGUF alignment')
    data_offset=(f.tell()+align-1)//align*align
    if data_offset>MAX_HEADER:raise ValueError('metadata too large')
    for t in tensors:t['offset']+=data_offset
    if len(set(t['name'] for t in tensors))!=len(tensors):raise ValueError('duplicate tensors')
    intervals=sorted((t['offset'],t['offset']+t['size']) for t in tensors)
    if any(b>c for (_,b),(c,_) in zip(intervals,intervals[1:])) or intervals[-1][1]>f.p['source_bytes']:raise ValueError('overlapping/out-of-source tensors')
    return dict(n_layers=layers[0],data_offset=data_offset,tensors=tensors)


def prepare(repo,filename,counts,node_ids,revision=None,opener=None,src=None):
    p=dict(src or source(repo,filename,revision));reader=HeaderReader(p,opener)
    # The gguf package is already required by the native shard tool.
    import sys
    sys.path.insert(0,str(Path(os.environ.get('CARAVAN_LLAMA_SRC','~/dev/llama.cpp')).expanduser()/'gguf-py'))
    from gguf.constants import GGML_QUANT_SIZES
    p.update(parse_header(reader,GGML_QUANT_SIZES));p['shares']=shares(counts)
    if len(node_ids)!=len(p['shares']) or len(set(node_ids))!=len(node_ids):raise ValueError('one unique node per share required')
    p['node_ids']=node_ids
    own=shards.owners(p['n_layers'],p['shares'],[t['name'] for t in p['tensors']])
    for t in p['tensors']:t['owner']=own[t['name']]
    p['header_sha256']=hashlib.sha256(read_range(p,0,p['data_offset'],opener)).hexdigest()
    p['planner_download_bytes']=reader.bytes+p['data_offset'];p['planner_ranges']=reader.requests+[[0,p['data_offset']]]
    p['plan_id']=hashlib.sha256(json.dumps([p['source_sha256'],p['shares'],node_ids],sort_keys=True).encode()).hexdigest()[:24]
    return p


def stage_root(p,index):
    key=hashlib.sha256((p['repo_id']+'/'+p['filename']).encode()).hexdigest()[:20]
    return '~/.caravan/gguf-shares/'+key+'/'+p['plan_id']+'/stage-'+str(index)


def validate(p,index):
    source_url(p)
    if shares(p['shares'])!=p['shares'] or len(p['node_ids'])!=len(p['shares']) or len(set(p['node_ids']))!=len(p['node_ids']) or type(index) is not int or not 0<=index<len(p['shares']):raise ValueError('invalid stage plan')
    if not 0<p['data_offset']<=MAX_HEADER or p['data_offset']>=p['source_bytes']:raise ValueError('invalid catalog range')
    if not re.fullmatch('[0-9a-f]{64}',p['header_sha256']):raise ValueError('invalid catalog checksum')
    own=shards.owners(p['n_layers'],p['shares'],[t['name'] for t in p['tensors']])
    if len(own)!=len(p['tensors']):raise ValueError('duplicate tensors')
    for t in p['tensors']:
        if not re.fullmatch('[A-Za-z0-9_.-]+',t['name']) or t['owner']!=own[t['name']] or type(t['offset']) is not int or type(t['size']) is not int or t['size']<=0 or t['offset']<p['data_offset'] or t['offset']+t['size']>p['source_bytes']:raise ValueError('invalid tensor range/ownership')
    spans=sorted((t['offset'],t['offset']+t['size']) for t in p['tensors'])
    if any(b>c for (_,b),(c,_) in zip(spans,spans[1:])):raise ValueError('overlapping tensors')


def _root(request):
    p=request['manifest'];i=request['stage_index'];validate(p,i)
    expected=Path(stage_root(p,i)).expanduser()
    if Path(request['dest']).expanduser()!=expected:raise ValueError('stage destination differs from server-derived path')
    for parent in [expected,*expected.parents]:
        if parent.is_symlink():raise ValueError('linked stage path refused')
    return expected


def cache_index(p):
    index={}
    candidates=[*(Path.home()/'.caravan/gguf-shares').glob('*/*/stage-*/receipt.json'),*(Path.home()/'.caravan/day22-shards').glob('*/manifest.json')]
    for previous in candidates:
        if any(x.is_symlink() for x in [previous,*previous.parents]):continue
        try:
            rec=json.loads(previous.read_text())
            if rec.get('source_sha256')!=p['source_sha256']:continue
            for t in rec['tensors']:
                file=previous.parent/'rpc'/t['key']
                if not file.is_symlink() and file.is_file() and file.stat().st_size==t['size']:
                    index[(t['offset'],t['size'],t['name'])]=(file,t)
                    index[('content',t['key'],t['sha256'])]=(file,t)
        except (ValueError,KeyError,OSError):continue
    return index


def status(request):
    root=_root(request);p=request['manifest'];i=request['stage_index'];have=0;missing=[];cached=cache_index(p)
    for t in p['tensors']:
        if t['owner']!=i:continue
        meta=root/'partials'/f'{t["offset"]}-{t["size"]}.json'
        m=json.loads(meta.read_text()) if meta.is_file() else {}
        n=min(t['size'],m.get('bytes',0))
        if (t['offset'],t['size'],t['name']) in cached or ('content',t.get('key'),t.get('sha256')) in cached:n=t['size']
        have+=n
        if n<t['size']:missing.append(t['name'])
    total=sum(t['size'] for t in p['tensors'] if t['owner']==i)
    return dict(assembled=(root/'manifest.json').is_file(),required_bytes=total,download_bytes=total-have,downloads=missing,on_disk_bytes=have,allocated_bytes=None,not_needed_for_plan=[],cache_scope='own verified/resumable ranges only')


def fetch(request,opener=None):
    import fcntl
    root=_root(request);root.mkdir(parents=True,exist_ok=True)
    lock=root/'download.lock'
    if lock.is_symlink():raise ValueError('linked download lock refused')
    with lock.open('a') as lf:
        fcntl.flock(lf,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _fetch_locked(request,root,opener)


def _fetch_locked(request,root,opener):
    p=request['manifest'];i=request['stage_index'];start=time.monotonic();downloaded=0;ranges=[]
    if request.get('runtime_required'):
        from gguf_runtime import ensure
        ensure()
    partials=root/'partials';cache=root/'rpc'
    for d in (partials,cache):
        if d.is_symlink():raise ValueError('linked piece folder refused')
        d.mkdir(exist_ok=True)
    catalog=root/'model.cvgg'
    if catalog.is_symlink():raise ValueError('linked catalog refused')
    if not catalog.exists():
        header=read_range(p,0,p['data_offset'],opener);downloaded+=len(header);ranges.append([0,len(header)])
        if hashlib.sha256(header).hexdigest()!=p['header_sha256']:raise ValueError('metadata checksum differs from pinned plan')
        with catalog.open('xb') as f:f.write(shards.MAGIC+header)
    else:
        with catalog.open('rb') as f:
            if f.read(len(shards.MAGIC))!=shards.MAGIC or hashlib.sha256(f.read()).hexdigest()!=p['header_sha256']:raise ValueError('existing catalog corrupt')
    own=[];exe=shards._hash_bin()
    try:
        for t in p['tensors']:
            if t['owner']!=i:continue
            name=f'{t["offset"]}-{t["size"]}';part=partials/(name+'.part');journal=partials/(name+'.json')
            if part.is_symlink() or journal.is_symlink():raise ValueError('linked partial refused')
            old=json.loads(journal.read_text()) if journal.exists() else dict(bytes=0,sha256=hashlib.sha256(b'').hexdigest())
            n=old['bytes'];h=hashlib.sha256()
            if n==t['size'] and not part.exists() and old.get('key'):
                if t.get('sha256') and old['sha256']!=t['sha256']:raise ValueError('completed piece differs from known-good tensor')
                if t.get('key') and old['key']!=t['key']:raise ValueError('completed native key differs from known-good tensor')
                ready=cache/old['key']
                if ready.is_symlink() or not ready.is_file() or ready.stat().st_size!=n or shards.digest(ready)!=old['sha256']:raise ValueError('completed piece corrupt')
                own.append(dict(t,key=old['key'],sha256=old['sha256']));continue
            if type(n) is not int or not 0<=n<=t['size']:raise ValueError('invalid partial checkpoint')
            if part.exists():
                with part.open('rb') as f:
                    left=n
                    while left:
                        b=f.read(min(left,4<<20))
                        if not b:raise ValueError('partial shorter than checkpoint')
                        h.update(b);left-=len(b)
                if h.hexdigest()!=old['sha256']:raise ValueError('partial checksum failed; existing bytes retained, not trusted')
                if part.stat().st_size<n:raise ValueError('short partial')
                # Discard only an uncommitted tail in this job's private .part.
                with part.open('r+b') as f:f.truncate(n)
            elif n:raise ValueError('checkpoint piece missing')
            # Reuse matching previous-plan tensors by SHA-bound source/offset.
            if n==0:
                cached=cache_index(p);hit=cached.get((t['offset'],t['size'],t['name'])) or cached.get(('content',t.get('key'),t.get('sha256')))
                if hit:
                    file,record=hit
                    if shards.digest(file)!=record['sha256']:raise ValueError('reusable cached piece is corrupt')
                    if part.exists():
                        if part.stat().st_size:raise ValueError('unexpected nonempty partial')
                        part.unlink() # only this job's new empty private partial
                    os.link(file,part);n=t['size'];h=hashlib.sha256()
                    with part.open('rb') as f:
                        for b in iter(lambda:f.read(4<<20),b''):h.update(b)
                    atomic(journal,dict(bytes=n,sha256=h.hexdigest()))
            if n<t['size']:
                begin=t['offset']+n;end=t['offset']+t['size']-1
                with response(p,begin,end,opener) as r,part.open('ab') as f:
                    ranges.append([begin,end-begin+1])
                    while n<t['size']:
                        b=r.read(min(4<<20,t['size']-n))
                        if not b:raise ValueError('interrupted tensor; resume keeps the verified checkpoint')
                        f.write(b);f.flush();os.fsync(f.fileno());h.update(b);n+=len(b);downloaded+=len(b)
                        atomic(journal,dict(bytes=n,sha256=h.hexdigest()))
                        print(json.dumps(dict(stage_index=i,downloaded_bytes=downloaded,offset=t['offset'],piece_bytes=n,piece_size=t['size'])),flush=True)
                    if r.read(1):raise ValueError('oversized tensor response')
            sha=h.hexdigest()
            if t.get('sha256') and sha!=t['sha256']:raise ValueError('tensor checksum differs from known-good plan')
            out=subprocess.run([str(exe),str(part)],input=f'0 {t["size"]}\n',capture_output=True,text=True,check=True)
            key=out.stdout.strip()
            if not re.fullmatch('[0-9a-f]{16}',key):raise ValueError('bad native tensor key')
            dst=cache/key
            if dst.is_symlink():raise ValueError('linked cache piece refused')
            if dst.exists():
                if dst.stat().st_size!=t['size'] or shards.digest(dst)!=sha:raise ValueError('cache-key collision/corruption')
            else:os.link(part,dst)
            atomic(journal,dict(bytes=n,sha256=sha,key=key))
            part.unlink() # our completed private partial; rpc hardlink keeps its data
            own.append(dict(t,key=key,sha256=sha))
    finally:
        exe.unlink();exe.parent.rmdir() # this invocation's disposable compiler output only
    receipt=dict(ok=True,stage_index=i,source_sha256=p['source_sha256'],revision=p['revision'],plan_id=p['plan_id'],tensors=own,downloaded_bytes=downloaded,download_s=round(time.monotonic()-start,6),ranges=ranges,root=str(root))
    atomic(root/'receipt.json',receipt)
    return receipt


def finalize(request,receipts):
    root=_root(request);p=request['manifest'];idx=request['stage_index']
    if len(receipts)!=len(p['shares']) or {r['stage_index'] for r in receipts}!=set(range(len(p['shares']))):raise ValueError('missing/duplicate stage receipt')
    by_name={};keys={}
    for r in receipts:
        if type(r['stage_index']) is not int or not r.get('ok') or r['plan_id']!=p['plan_id'] or r['source_sha256']!=p['source_sha256'] or r['revision']!=p['revision']:raise ValueError('receipt source/plan mismatch')
        for t in r['tensors']:
            expected=next((x for x in p['tensors'] if x['name']==t['name']),None)
            if not expected or any(t[k]!=expected[k] for k in ('offset','size','owner')) or t['owner']!=r['stage_index'] or t['name'] in by_name or not re.fullmatch('[0-9a-f]{64}',t['sha256']) or not re.fullmatch('[0-9a-f]{16}',t['key']):raise ValueError('invalid tensor receipt')
            identity=(t['size'],t['sha256'])
            if t['key'] in keys and keys[t['key']]!=identity:raise ValueError('native key collision')
            keys[t['key']]=identity;by_name[t['name']]=t
    if set(by_name)!={t['name'] for t in p['tensors']}:raise ValueError('incomplete tensor receipt union')
    ts=[by_name[t['name']] for t in p['tensors']]
    table=''.join(f'{t["name"]}\t{t["key"]}\t{t["size"]}\t{t["owner"]}\n' for t in ts)
    wt=root/'weights.tsv'
    if wt.is_symlink():raise ValueError('linked routing table refused')
    wt.write_text(table)
    m=dict(schema=shards.SCHEMA,source_name=p['filename'],source_bytes=p['source_bytes'],source_sha256=p['source_sha256'],catalog_sha256=shards.digest(root/'model.cvgg'),weights_sha256=shards.digest(wt),n_layers=p['n_layers'],shares=p['shares'],stage_index=idx,tensors=ts,origin={k:p[k] for k in ('repo_id','filename','revision')})
    atomic(root/'manifest.json',m)
    verified=shards.verify(root)
    atomic(root/'source-plan.json',dict(p,tensors=ts))
    return verified


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['receipt','finalize']);ap.add_argument('request');ap.add_argument('--receipts')
    a=ap.parse_args();r=json.loads(Path(a.request).expanduser().read_text())
    out=(json.loads((_root(r)/'receipt.json').read_text()) if a.action=='receipt' else finalize(r,json.loads(Path(a.receipts).expanduser().read_text())))
    print(json.dumps(out),flush=True)
