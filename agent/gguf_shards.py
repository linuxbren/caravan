"""Experimental strict GGUF shards: all tensor sizes, N Minis, no full lead file.

The .cvgg catalog is explicitly NOT a standalone GGUF. It wraps GGUF metadata
for llama_model_init_from_user; weights are separate, verified tensor pieces.
Stock llama.cpp cannot load it. See docs/DAY22.md before running the experiment.
Existing sources and output directories are never modified or replaced.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from gguf_rpc_seed import device_layers

MAGIC = b'CVGGUF1\n'
SCHEMA = 'caravan-gguf-shards-v1'


def shares_arg(text):
    shares = [float(x) for x in text.split(',')]
    if not shares or any(not math.isfinite(s) or s <= 0 for s in shares):
        raise ValueError('one positive finite share is required per Mini')
    return shares


def owners(n_layers, shares, names):
    """Exact llama.cpp layer split; input/unknown globals on lead, output last slot."""
    shares = shares_arg(','.join(map(str, shares)))
    if type(n_layers) is not int or n_layers <= 0:
        raise ValueError('positive block count required')
    slots = {}
    for i in range(len(shares)):
        for layer in device_layers(n_layers, shares, i, pad=0):
            slots[layer] = i
    out = {}
    for name in names:
        m = re.fullmatch(r'blk\.(\d+)\..+', name)
        if m:
            layer = int(m[1])
            if layer >= n_layers: raise ValueError('tensor layer outside model')
            out[name] = slots[layer]
        elif name.startswith('output'):
            out[name] = slots[n_layers]
        else:
            out[name] = 0
    return out


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def _reader(path):
    src = Path(os.environ.get('CARAVAN_LLAMA_SRC', '~/dev/llama.cpp')).expanduser()/'gguf-py'
    if src.is_dir(): sys.path.insert(0, str(src))
    from gguf import GGUFReader
    return GGUFReader(path)


def _hash_bin():
    # Build outside model storage; never overwrite an existing helper binary.
    import tempfile
    d = Path(tempfile.mkdtemp(prefix='caravan-shard-hash-'))
    exe = d/'hash'
    subprocess.run(['cc', '-O2', '-o', str(exe), str(Path(__file__).with_name('gguf_shard_hash.c'))], check=True)
    return exe


def create(source, root, shares, index):
    """Create a NEW Mini-specific tree; retain incomplete trees on any failure."""
    t0 = time.monotonic()
    source = Path(source).expanduser().resolve(strict=True)
    root = Path(root).expanduser()
    shares = shares_arg(','.join(map(str, shares)))
    if type(index) is not int or not 0 <= index < len(shares):
        raise ValueError('invalid Mini index')
    before = source.stat()
    reader = _reader(source)
    if 'split.count' in reader.fields:
        f = reader.fields['split.count']
        if int(f.parts[f.data[0]][0]) > 1:
            raise ValueError('multi-file source GGUF is not supported yet')
    counts = [int(f.parts[f.data[0]][0]) for k,f in reader.fields.items() if k.endswith('.block_count')]
    if len(counts) != 1: raise ValueError('unambiguous GGUF block count required')
    n_layers = counts[0]
    names = [t.name for t in reader.tensors]
    if len(set(names)) != len(names): raise ValueError('duplicate tensor names')
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', n) for n in names):
        raise ValueError('unsupported tensor name')
    own = owners(n_layers, shares, names)
    tensors = []
    for t in reader.tensors:
        off, size = int(t.data_offset), int(t.n_bytes)
        if off < reader.data_offset or size <= 0 or off+size > before.st_size:
            raise ValueError('tensor range outside source')
        tensors.append(dict(name=t.name, offset=off, size=size, owner=own[t.name]))
    intervals = sorted((t['offset'],t['offset']+t['size']) for t in tensors)
    if any(b > c for (_,b),(c,_) in zip(intervals,intervals[1:])):
        raise ValueError('overlapping tensor ranges')
    # Do all structural validation BEFORE reserving the fresh output directory.
    root.mkdir(parents=True, exist_ok=False)
    cache = root/'rpc'; cache.mkdir()
    exe = _hash_bin()
    try:
        p = subprocess.run([str(exe), str(source)], input=''.join(f"{t['offset']} {t['size']}\n" for t in tensors),
                           capture_output=True, text=True, check=True)
    finally:
        exe.unlink(); exe.parent.rmdir()  # only this invocation's disposable compiler output
    keys = p.stdout.splitlines()
    if len(keys) != len(tensors): raise ValueError('incomplete tensor hash result')
    seen = {}
    with source.open('rb') as f:
        for t, key in zip(tensors, keys):
            if not re.fullmatch('[0-9a-f]{16}', key): raise ValueError('invalid native hash')
            t['key'] = key
            f.seek(t['offset']); left = t['size']; sha = hashlib.sha256()
            # Exclusive create even inside the fresh tree; never replace a piece.
            dst = cache/key
            output = dst.open('xb') if t['owner'] == index and not dst.exists() else None
            try:
                while left:
                    b = f.read(min(left,4<<20))
                    if not b: raise ValueError('source truncated while sharding')
                    sha.update(b)
                    if output: output.write(b)
                    left -= len(b)
            finally:
                if output: output.close()
            t['sha256'] = sha.hexdigest()
            if key in seen and seen[key] != (t['size'],t['sha256']):
                raise ValueError('FNV collision: refusing ambiguous native RPC cache keys')
            seen[key] = (t['size'],t['sha256'])
        f.seek(0)
        with (root/'model.cvgg').open('xb') as out:
            out.write(MAGIC)
            out.write(f.read(int(reader.data_offset)))
    source_sha = digest(source)
    after = source.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('source changed during sharding; output is not ready')
    manifest = dict(schema=SCHEMA, source_name=source.name, source_bytes=before.st_size,
                    source_sha256=source_sha, catalog_sha256=digest(root/'model.cvgg'),
                    n_layers=n_layers, shares=shares, stage_index=index, tensors=tensors)
    with (root/'weights.tsv').open('x') as f:
        for t in tensors: f.write(f"{t['name']}\t{t['key']}\t{t['size']}\t{t['owner']}\n")
    manifest['weights_sha256'] = digest(root/'weights.tsv')
    with (root/'manifest.json').open('x') as f: json.dump(manifest,f,indent=2)
    result = verify(root)
    result['create_s'] = round(time.monotonic()-t0,3)
    return result


def verify(root):
    """Check SHA256 of every local piece, catalog, routing table; reject links/extras."""
    root = Path(root).expanduser()
    for name in ('manifest.json','weights.tsv','model.cvgg','rpc'):
        if (root/name).is_symlink(): raise ValueError('linked shard artifact refused')
    m = json.loads((root/'manifest.json').read_text())
    if m.get('schema') != SCHEMA: raise ValueError('unsupported shard schema')
    shares = shares_arg(','.join(map(str,m['shares'])))
    idx = m['stage_index']
    if type(idx) is not int or not 0 <= idx < len(shares): raise ValueError('invalid stage index')
    for name, key in [('model.cvgg','catalog_sha256'),('weights.tsv','weights_sha256')]:
        if digest(root/name) != m[key]: raise ValueError(name+' checksum mismatch')
    with (root/'model.cvgg').open('rb') as f:
        if f.read(len(MAGIC)) != MAGIC or f.read(4) != b'GGUF': raise ValueError('invalid catalog')
    ts = m['tensors']; names = [t['name'] for t in ts]
    if len(set(names)) != len(names): raise ValueError('duplicate tensor names')
    own = owners(m['n_layers'],shares,names)
    expected_table = ''.join(f"{t['name']}\t{t['key']}\t{t['size']}\t{t['owner']}\n" for t in ts)
    if (root/'weights.tsv').read_text() != expected_table: raise ValueError('routing table differs from manifest')
    wanted = {}; total = 0
    for t in ts:
        if (not re.fullmatch('[0-9a-f]{16}', t['key']) or not re.fullmatch('[0-9a-f]{64}', t['sha256']) or
            type(t['size']) is not int or t['size'] <= 0 or t['owner'] != own[t['name']]):
            raise ValueError('invalid tensor manifest')
        if t['owner'] != idx: continue
        key = t['key']; p = root/'rpc'/key
        if key in wanted and wanted[key] != (t['size'],t['sha256']): raise ValueError('ambiguous tensor key')
        wanted[key] = (t['size'],t['sha256'])
        if p.is_symlink() or not p.is_file() or p.stat().st_size != t['size'] or digest(p) != t['sha256']:
            raise ValueError('tensor piece missing or corrupt: '+t['name'])
        total += t['size']
    if {p.name for p in (root/'rpc').iterdir()} != set(wanted):
        raise ValueError('unexpected tensor files in stage cache')
    paths = [p for p in root.rglob('*') if p.is_file()]
    return dict(ok=True, stage_index=idx, n_minis=len(shares), tensors=sum(t['owner']==idx for t in ts),
                tensor_bytes=total, unique_piece_bytes=sum(s for s,_ in wanted.values()),
                logical_bytes=sum(p.stat().st_size for p in paths),
                allocated_bytes=sum(p.stat().st_blocks*512 for p in paths), source_bytes=m['source_bytes'],
                source_sha256=m['source_sha256'], root=str(root))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='action',required=True)
    p = sub.add_parser('create'); p.add_argument('source'); p.add_argument('root')
    p.add_argument('--shares',required=True); p.add_argument('--index',required=True,type=int)
    p = sub.add_parser('verify'); p.add_argument('root')
    a = ap.parse_args()
    result = create(a.source,a.root,shares_arg(a.shares),a.index) if a.action=='create' else verify(a.root)
    print(json.dumps(result,sort_keys=True),flush=True)

if __name__=='__main__': main()
