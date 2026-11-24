"""Web consent and per-helper inventory. No inference dependencies."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import guess_ahead as G
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402


def pairing(key):
    return next((p for p in G.load_table()['pairings'] if p['id'] == key), None)


BALANCE_NO_HELPER = (T("server.web_helpers.a_balance_split_of_an_mlx"))


def balance_split(snapshot) -> bool:
    """True for an MLX model loaded through the Balance planner (N-stage)."""
    b = (snapshot or {}).get('balance') or {}
    return bool((snapshot or {}).get('split') and isinstance(b, dict) and b.get('counts'))


def offer(snapshot):
    model = snapshot.get('model_id') or ''
    if not model or (snapshot.get('settings') or {}).get('guess_ahead') in ('off', 'mtp'):
        return None
    if balance_split(snapshot):
        # Day 28 tuning fix: a Balance split never loads a helper (see
        # BALANCE_NO_HELPER), so do not offer a download it cannot use.
        return None
    p = G.find_pairing(Path(model.replace('/', '--')))
    if not p or p.get('skip') or p['draft'].get('vocab') in ('mismatch', 'incompatible'):
        return None
    d = p['draft']
    if (G.drafts_dir() / d['name'] / 'config.json').is_file():
        return None
    import web_picker
    if any(j.get('repo_id') == d['hf_repo'] and j.get('status') in ('queued', 'running', 'cancelling') for j in web_picker.list_jobs()):
        return None
    st = G.load_state()
    # Older non-interactive False answers have no provenance. Only explicit web
    # answers suppress web prompts; this migrates the old silent-decline bug.
    declined = (st.get('web_download_answers') or {}).get(p['id']) is False
    return dict(id=p['id'], name=d['name'], repo_id=d['hf_repo'], size_mb=d.get('size_mb'),
                model=model, declined=declined,
                message=T("server.web_helpers.a_size_mb_mb_helper_can", size_mb=d['size_mb'], split=model.split('/')[-1]))


def answer(key, download):
    if not pairing(key):
        raise ValueError(T("server.web_helpers.unknown_helper"))
    st = G.load_state()
    st.setdefault('web_download_answers', {})[key] = bool(download)
    # Do not enable worker auto-download: downloads go through normal jobs.
    st.setdefault('download_answers', {}).pop(key, None)
    G.save_state(st)


def inventory():
    out = {}
    root = G.drafts_dir()
    for p in root.iterdir() if root.is_dir() else []:
        if not p.is_dir() or p.is_symlink():
            continue
        pairs = [x for x in G.load_table()['pairings'] if x['draft']['name'] == p.name]
        out['draft:' + p.name] = dict(name=p.name, path=str(p), pairs=sorted({m for x in pairs for m in x['match']}))
    for root in (Path('~/.caravan/mlx-models').expanduser(), Path('~/.exo/models').expanduser()):
        for model in root.iterdir() if root.is_dir() else []:
            p = model / 'caravan-mtp'
            if p.is_dir() and not p.is_symlink():
                out['mtp:' + model.name] = dict(name=model.name + ' · native MTP head', path=str(p), pairs=[model.name.replace('--', '/')])
    return out


def delete_helper(key, current=''):
    import shutil
    item = inventory().get(key)
    if not item:
        return {'ok': False, 'error': T("server.web_helpers.helper_not_found")}
    # Conservative: protect every helper while a model is loaded (also covers
    # active workers retaining a draft after automatic guess-ahead shutoff).
    if current:
        return {'ok': False, 'error': T("server.picker_disk_sizes.stop_the_loaded_model_before_deleting")}
    shutil.rmtree(item['path'])
    return {'ok': True, 'removed': [item['path']]}
