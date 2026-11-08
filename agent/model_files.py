"""Per-Mini file accounting and revision-pinned stage fetches. Never prunes weights.

The web/TUI send server-generated plans, not user paths or remote shell commands.
Standalone --inspect-json is read-only; --fetch-json requires explicit intent.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'proxy'))


def safe_name(name):
    if (not isinstance(name, str) or not name or '\\' in name or
            PurePosixPath(name).is_absolute() or any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('unsafe model filename')
    return name


def repo_name(repo):
    if not isinstance(repo, str) or not re.fullmatch(r'[\w.-]+/[\w.-]+', repo) or '..' in repo:
        raise ValueError('expected a Hugging Face owner/repository')
    return repo


def contained(root, name):
    root = Path(root).expanduser()
    p = root / safe_name(name)
    if not p.resolve().is_relative_to(root.resolve()):
        raise ValueError('model file points outside its own folder')
    # Never replace a symlink, even one inside the tree.
    if p.is_symlink():
        raise ValueError('refusing to replace a linked model file')
    return p


def tree_usage(path):
    """Logical bytes and allocated bytes (deduped hardlinks), no symlink traversal."""
    d = Path(path).expanduser()
    files, allocated, seen, links = {}, 0, set(), []
    if d.is_symlink():
        return {'files': None, 'on_disk_bytes': None, 'allocated_bytes': None, 'links': [str(d)]}
    for p in d.rglob('*') if d.is_dir() else []:
        if p.is_symlink():
            links.append(str(p.relative_to(d))); continue
        if not p.is_file():
            continue
        st = p.stat()
        files[str(p.relative_to(d))] = st.st_size
        key = (st.st_dev, st.st_ino)
        if key not in seen:
            allocated += getattr(st, 'st_blocks', 0) * 512
            seen.add(key)
    return {'files': files, 'on_disk_bytes': sum(files.values()),
            'allocated_bytes': allocated, 'links': sorted(links)}


def storage_plan(required, inventory, sizes=None):
    """Retained files are NOT deletion recommendations; other plans may need them."""
    required = sorted({safe_name(f) for f in required})
    if inventory is None or inventory.get('files') is None:
        return {'required_files': required, 'downloads': None, 'download_bytes': None,
                'on_disk_bytes': None, 'allocated_bytes': None, 'not_needed_for_plan': None}
    files, sizes = inventory['files'], sizes or {}
    invalid = set(inventory.get('invalid_shards') or [])
    missing = sorted(f for f in required if f not in files or f in invalid or
                     (sizes.get(f) and files[f] != sizes[f]))
    retained = sorted(f for f in files if f.endswith('.safetensors') and f not in required)
    return {'required_files': required, 'downloads': missing,
            'download_bytes': sum(sizes[f] for f in missing) if all(sizes.get(f) for f in missing) else None,
            'on_disk_bytes': inventory.get('on_disk_bytes'), 'allocated_bytes': inventory.get('allocated_bytes'),
            'required_bytes': sum(sizes[f] for f in required) if all(sizes.get(f) for f in required) else None,
            'not_needed_for_plan': retained, 'retained_bytes': sum(files[f] for f in retained),
            'links': inventory.get('links') or []}


def inspect(path):
    from mlx_split import safetensors_expected_size
    out = tree_usage(path)
    d = Path(path).expanduser()
    out['invalid_shards'] = [f for f, size in (out['files'] or {}).items() if f.endswith('.safetensors') and
                             safetensors_expected_size(d/f) != size]
    return out


def plan_digest(config, index):
    return hashlib.sha256(json.dumps([config, index], sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def fetch_mlx(request):
    """Resolve one commit, compare metadata before changing a live model tree.

    Only stage shards + tokenizer/config metadata are fetched. Each Mini uses
    its own HF credentials. No remote Mini or model download is contacted here.
    """
    from huggingface_hub import HfApi, snapshot_download
    from mlx_split_fetch import plan_stage_files, SMALL, _resolve_token, write_sizes
    from mlx_split import check_local_shards
    import range_fetch
    repo = repo_name(request['repo_id'])
    dest = Path(request['dest']).expanduser()
    counts, stage = request['counts'], request['stage_index']
    token = _resolve_token()
    info = HfApi(token=token).model_info(repo, revision=request.get('revision'), files_metadata=True)
    revision = info.sha
    if not revision:
        raise ValueError('source revision is unknown; nothing fetched')
    sizes = {safe_name(s.rfilename): int(s.size or 0) for s in info.siblings}
    with tempfile.TemporaryDirectory(prefix='caravan-plan-') as tmp:
        snapshot_download(repo, revision=revision, local_dir=tmp, token=token,
                          allow_patterns=['config.json', 'model.safetensors.index.json'])
        cfg = json.loads((Path(tmp)/'config.json').read_text())
        idx = json.loads((Path(tmp)/'model.safetensors.index.json').read_text())
        if plan_digest(cfg, idx) != request['metadata_digest']:
            raise ValueError('source metadata changed since preview; nothing in the model folder changed')
        stages = plan_stage_files(cfg, idx, counts)['stages']
        if type(stage) is not int or not 0 <= stage < len(stages):
            raise ValueError('invalid stage index')
        needed = sorted(stages[stage])
        contained(dest, '.cache/huggingface/download/.caravan-path-check')
        for f in needed:
            contained(dest, f)
            contained(dest, '.cache/huggingface/download/'+f+'.incomplete')
            if not sizes.get(f):
                raise ValueError('source size is unknown for ' + f)
        # Validate all metadata paths before snapshot_download follows any links.
        import fnmatch
        for f in sizes:
            if any(fnmatch.fnmatch(f, pat) for pat in SMALL):
                contained(dest, f)
        if dest.is_symlink():
            raise ValueError('model folder must not be a symlink')
        if (dest/'config.json').is_file() and (dest/'model.safetensors.index.json').is_file():
            old_cfg = json.loads((dest/'config.json').read_text())
            old_idx = json.loads((dest/'model.safetensors.index.json').read_text())
            if plan_digest(old_cfg, old_idx) != request['metadata_digest']:
                raise ValueError('this Mini has different model metadata; move its old folder aside before fetching')
        # Correct-size corrupt files must not be silently skipped by Range fetch.
        local = inspect(dest)
        bad = set(needed) & set(local['invalid_shards'])
        if bad:
            raise ValueError('move these corrupt files aside before fetching: ' + ', '.join(sorted(bad)))
        hashes = {}
        for sibling in info.siblings:
            lfs = getattr(sibling, 'lfs', None)
            sha = lfs.get('sha256') if isinstance(lfs, dict) else getattr(lfs, 'sha256', None)
            if sha: hashes[sibling.rfilename] = sha
        def verify_file(f):
            if f not in hashes: return
            h = hashlib.sha256()
            with (dest/f).open('rb') as src:
                for block in iter(lambda: src.read(1 << 20), b''): h.update(block)
            if h.hexdigest() != hashes[f]:
                raise ValueError('source checksum differs: move this file aside before fetching: ' + f)
        for f in needed:
            if (dest/f).is_file() and (dest/f).stat().st_size == sizes[f]: verify_file(f)
        snapshot_download(repo, revision=revision, local_dir=str(dest), token=token, allow_patterns=SMALL)
        for f in needed:
            range_fetch.fetch(repo, f, dest, sizes[f], token=token,
                              url=range_fetch.file_url(repo, f, revision))
        for f in needed: verify_file(f)
        (dest/'caravan-source.json').write_text(json.dumps({'repo': repo, 'revision': revision}))
        write_sizes(dest, repo, {f: sizes[f] for f in set(idx['weight_map'].values())})
        check_local_shards(dest, 'head' if stage == len(counts)-1 else 'front', counts=counts, stage_index=stage)
    if request.get('placement'):
        p = dest/'caravan-placement.json'; tmp=p.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(request['placement'],repo_id=repo))); os.replace(tmp,p)
    return {'ok': True, 'revision': revision, 'files': needed, 'stage_index': stage}


def active_transfers(root=None):
    """Read only owned transfer records; process argv must carry the UUID."""
    import shlex
    import subprocess
    root = Path(root) if root else Path.home()/'.caravan/transfers'
    found=[]
    for p in root.glob('*.pid'):
        token=p.stem
        if not re.fullmatch('[0-9a-f]{32}',token) or p.with_suffix('.exit').exists(): continue
        try:
            pid=int(p.read_text())
            cmd=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True,timeout=5).stdout
            args=shlex.split(cmd)
            if '--job' not in args or args[args.index('--job')+1] != token or not any(a.endswith('/agent/model_files.py') for a in args): continue
            plan=json.loads(p.with_suffix('.json').read_text())
            found.append(dict(token=token,pid=pid,repo_id=plan['repo_id'],node_id=plan.get('node_id'),dest=plan.get('dest'),counts=plan.get('counts') or plan.get('shares')))
        except (OSError,ValueError,IndexError,KeyError): continue
    return found


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--inspect-json'); g.add_argument('--fetch-json'); g.add_argument('--fetch-plan'); g.add_argument('--status-plan'); g.add_argument('--list-transfers', action='store_true')
    p.add_argument('--job', help='unique server-generated transfer marker')
    a = p.parse_args(argv)
    if a.list_transfers:
        out = active_transfers()
    elif a.inspect_json:
        out = inspect(json.loads(a.inspect_json)['path'])
    elif a.status_plan:
        from gguf_files import status
        out = status(json.loads(Path(a.status_plan).expanduser().read_text()))
    else:
        r = json.loads(Path(a.fetch_plan).expanduser().read_text()) if a.fetch_plan else json.loads(a.fetch_json)
        if r.get('format') == 'gguf':
            from gguf_files import fetch_plan
            out = fetch_plan(r)
        else:
            out = fetch_mlx(r)
    print(json.dumps(out), flush=True)
    return out


if __name__ == '__main__':
    main()
