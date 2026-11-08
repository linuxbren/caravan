"""Experimental direct-source GGUF tensor-cache plans for N RPC Minis.

The stock llama.cpp lead still requires the COMPLETE GGUF. Peers fetch only
large tensors assigned to their device, not a complete GGUF or a sparse fake.
Small tensors still travel via RPC (llama.cpp's hash-cache threshold is 10 MiB).
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

from model_files import repo_name, safe_name, tree_usage
from gguf_rpc_seed import device_layers, tensor_plan, rpc_cache_dir, ensure_bin


def digest_range(path, offset, size):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        f.seek(offset)
        while size:
            b = f.read(min(size, 4 << 20))
            if not b: raise ValueError('GGUF tensor extends beyond the local file')
            h.update(b); size -= len(b)
    return h.hexdigest()


def source_manifest(path, repo, filename, *, cache_root=None):
    """Bind local offsets/checksums to one immutable, SHA256-verified Hub file.

    Cache is metadata only. The first plan hashes the local complete GGUF;
    unchanged subsequent previews reuse its inode/size/mtime-bound result.
    """
    from huggingface_hub import HfApi
    from mlx_split_fetch import _resolve_token
    repo_name(repo); safe_name(filename)
    path = Path(path).expanduser()
    stat = path.stat()
    info = HfApi(token=_resolve_token()).model_info(repo, files_metadata=True)
    src = next((s for s in info.siblings if s.rfilename == filename), None)
    lfs = getattr(src, 'lfs', None)
    sha = lfs.get('sha256') if isinstance(lfs, dict) else getattr(lfs, 'sha256', None)
    if src is None or src.size != stat.st_size or not sha or not info.sha:
        raise ValueError('GGUF source must match the local file size and publish an LFS SHA256')
    identity = [str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, sha]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    root = Path(cache_root) if cache_root else Path.home()/'.caravan/file-plans'
    cached = root/(key+'.json')
    if cached.is_file():
        out = json.loads(cached.read_text())
        out.update(repo_id=repo, filename=filename, revision=info.sha)
        return out
    if digest_range(path, 0, stat.st_size) != sha:
        raise ValueError('installed GGUF differs from this source; no peer files fetched')
    try:
        tuples, n_layer = tensor_plan(str(path), None)
    except ImportError as exc:
        raise ValueError('GGUF metadata reader is missing; install requirements-mac.txt in the Caravan venv') from exc
    if not n_layer: raise ValueError('GGUF block count is unknown')
    tensors = [dict(name=name, offset=off, size=size, sha256=digest_range(path, off, size))
               for name, off, size in tuples]
    if path.stat().st_mtime_ns != stat.st_mtime_ns or path.stat().st_size != stat.st_size:
        raise ValueError('GGUF changed while preparing its plan')
    out = dict(format='gguf', repo_id=repo, filename=filename, revision=info.sha,
               source_bytes=stat.st_size, source_sha256=sha, n_layers=n_layer, tensors=tensors)
    root.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix('.tmp'); tmp.write_text(json.dumps(out)); os.replace(tmp, cached)
    return out


def stage_plan(manifest, shares, index):
    import math
    if (not isinstance(shares, list) or not shares or any(isinstance(s, bool) or not isinstance(s,(int,float)) or
            not math.isfinite(s) or s <= 0 for s in shares) or type(index) is not int or not 0 <= index < len(shares)):
        raise ValueError('GGUF needs one positive finite share per Mini and a valid device index')
    layers = device_layers(manifest['n_layers'], shares, index, pad=0)
    def owns(t):
        name = t['name']
        if name.startswith('blk.'): return int(name.split('.')[1]) in layers
        if name.startswith('output'): return manifest['n_layers'] in layers
        if name.startswith('token_embd'): return index == 0
        return True  # conservative unknown tensors, like the existing seeder
    return dict(manifest, tensors=[t for t in manifest['tensors'] if owns(t)],
                shares=shares, stage_index=index, layer_range=[layers.start,layers.stop])


def record_path(plan, root=None):
    key = plan['source_sha256']
    if not re.fullmatch('[0-9a-f]{64}', key): raise ValueError('invalid source checksum')
    return (Path(root) if root else Path.home()/'.caravan/gguf-plans')/(key+'.json')


def status(plan, *, cache=None, records=None):
    cache = Path(cache) if cache else rpc_cache_dir()
    record = record_path(plan, records)
    seen = json.loads(record.read_text()).get('seen_tensors', {}) if record.exists() else {}
    def valid(t):
        old = seen.get(t['sha256']) or {}
        key = old.get('cache_key', '')
        if not re.fullmatch('[0-9a-f]{16}', key): return False
        p = cache/key
        return not p.is_symlink() and p.is_file() and p.stat().st_size == t['size']
    missing = [t for t in plan['tensors'] if not valid(t)]
    wanted = {t['sha256'] for t in plan['tensors']}
    retained = [v for sha, v in seen.items() if sha not in wanted and
                re.fullmatch('[0-9a-f]{16}', v.get('cache_key','')) and (cache/v['cache_key']).is_file()]
    usage = tree_usage(cache)
    return dict(downloads=[t['name'] for t in missing], download_bytes=sum(t['size'] for t in missing),
                required_bytes=sum(t['size'] for t in plan['tensors']),
                on_disk_bytes=usage['on_disk_bytes'], allocated_bytes=usage['allocated_bytes'],
                not_needed_for_plan=sorted({t['cache_key'] for t in retained}),
                retained_bytes=sum(t['size'] for t in retained), cache_path=str(cache), cache_scope='all RPC models on this Mini')


def fetch_tensor(plan, tensor, part, token=None, opener=None):
    """Strict bounded Range, resumable, checked against the installed lead's SHA256."""
    from range_fetch import file_url
    repo_name(plan['repo_id']); safe_name(plan['filename'])
    if not re.fullmatch('[0-9a-f]{40,64}', plan['revision']): raise ValueError('immutable source revision required')
    size, offset = tensor['size'], tensor['offset']
    if type(size) is not int or type(offset) is not int or size <= 0 or offset < 0 or offset+size > plan['source_bytes']:
        raise ValueError('tensor range outside source file')
    if not re.fullmatch('[0-9a-f]{64}', tensor['sha256']): raise ValueError('invalid tensor checksum')
    part = Path(part)
    part.parent.mkdir(parents=True, exist_ok=True)
    if part.is_symlink(): raise ValueError('linked staging file refused')
    have = part.stat().st_size if part.exists() else 0
    if have > size: raise ValueError('oversized staging file; inspect/move it aside')
    if have < size:
        start, end = offset+have, offset+size-1
        req = urllib.request.Request(file_url(plan['repo_id'], plan['filename'], plan['revision']))
        req.add_header('Range', f'bytes={start}-{end}')
        if token: req.add_header('Authorization', 'Bearer '+token)
        with (opener or urllib.request.urlopen)(req, timeout=60) as r:
            expected = f'bytes {start}-{end}/{plan["source_bytes"]}'
            if r.status != 206 or r.headers.get('Content-Range') != expected:
                raise ValueError('source ignored/changed the requested tensor range; no full-file fallback')
            remaining = size-have
            with part.open('ab') as f:
                while remaining:
                    b = r.read(min(4 << 20, remaining))
                    if not b: raise RuntimeError('tensor download interrupted; Resume to continue')
                    if len(b) > remaining: raise ValueError('oversized range response')
                    f.write(b); remaining -= len(b)
            if r.read(1): raise ValueError('range response has extra bytes')
    if digest_range(part, 0, size) != tensor['sha256']:
        raise ValueError('tensor checksum failed; inspect/move its staging file aside')
    return part


def fetch_plan(plan, *, cache=None, records=None, staging=None, opener=None):
    from mlx_split_fetch import _resolve_token
    cache = Path(cache) if cache else rpc_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    record = record_path(plan, records)
    record.parent.mkdir(parents=True, exist_ok=True)
    seen = json.loads(record.read_text()).get('seen_tensors', {}) if record.exists() else {}
    stage = Path(staging) if staging else Path.home()/'.caravan/gguf-staging'
    missing = set(status(plan, cache=cache, records=records)['downloads'])
    for tensor in plan['tensors']:
        if tensor['name'] not in missing:
            key = seen[tensor['sha256']]['cache_key']
            if digest_range(cache/key, 0, tensor['size']) != tensor['sha256']:
                raise ValueError('cached tensor checksum differs; move cache file aside: '+key)
            continue
        part = fetch_tensor(plan, tensor, stage/(tensor['sha256']+'.incomplete'), _resolve_token(), opener)
        p = subprocess.run([str(ensure_bin()), str(part), str(cache)], input=f"0 {tensor['size']}\n",
                           capture_output=True, text=True)
        fields = p.stdout.strip().split()
        if p.returncode or len(fields) != 3 or not re.fullmatch('[0-9a-f]{16}', fields[0]):
            raise RuntimeError(p.stderr or 'tensor-cache seeding failed')
        cached = cache/fields[0]
        if cached.is_symlink() or not cached.is_file() or cached.stat().st_size != tensor['size'] or digest_range(cached, 0, tensor['size']) != tensor['sha256']:
            raise ValueError('tensor cache differs from verified source; move cache file aside: '+fields[0])
        seen[tensor['sha256']] = dict(cache_key=fields[0], size=tensor['size'], name=tensor['name'])
        tmp = record.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(source_sha256=plan['source_sha256'], seen_tensors=seen)))
        os.replace(tmp, record)
        part.unlink()  # completed transfer staging only, NEVER obsolete model/cache files
    result = status(plan, cache=cache, records=records)
    if result['downloads']: raise RuntimeError('tensor cache verification is incomplete')
    return dict(ok=True, **result)
