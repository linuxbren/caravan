"""Split download for a two-Mini MLX split (Caravan v3 prototype, 2026-10-31).

Each Mini fetches only the safetensors shards that hold *its* layers,
straight from Hugging Face -- nothing is relayed through the lead.

    python mlx_split_fetch.py <repo> <local_dir> --role lead|packer|all [--packer-layers K] [--dry-run]

(--role head|front and --front-layers still work as deprecated aliases.
Internally the lead is "head" and Packer 1 is "front", as in mlx_split.py.
--role all downloads every shard — used for single-Mini / copy-to-all placement.)

How: read config.json + model.safetensors.index.json (small files, fetched
first), map every weight name to a role, and pass the needed shard files to
huggingface_hub.snapshot_download(allow_patterns=...) together with the
config/tokenizer files. After a real download it writes
caravan-split-sizes.json (the shard sizes Hugging Face lists) next to the
files; the worker checks each shard's size against it, and against the
shard's own safetensors header, before it starts.

Progress: writes JSON lines to /tmp/caravan-progress-<folder>.jsonl (hook for
the web UI). With hf_xet, `.incomplete` often stays 0 while nettop still shows
bytes_in — the emitter falls back to network counters so progress is truthful.

Weight -> role rules (plan_split() decides the layer ranges, same as the worker):
  * "...layers.<i>." of the language model -> the stage holding layer i
  * embed_tokens -> front (Packer 1); also head (the lead) when embeddings are tied (no lm_head)
  * lm_head and the final norm -> head (the lead)
  * vision / audio towers -> nobody (the split is text-only) unless --with-vision
  * anything else -> both (safe default)
Shards are whole files, so a shard that straddles the boundary goes to both
Minis: the planner reports those "shared" shards and their size.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "proxy"))
from mlx_split import plan_split  # noqa: E402

SMALL = ["*.json", "*.jinja", "*.txt", "*.model", "*.tiktoken", "*.py"]
LAYER = re.compile(r"(?:^|\.)layers\.(\d+)\.")
VISION = ("vision", "audio", "embed_vision", "embed_audio", "multi_modal_projector")


def n_layers_of(config):
    for c in (config, config.get("text_config") or {}):
        if c.get("num_hidden_layers"):
            return int(c["num_hidden_layers"])
    raise ValueError("config has no num_hidden_layers")


def tied_of(config, weight_map):
    """Tied embeddings = no lm_head weights in the checkpoint (the head then needs embed_tokens)."""
    return not any("lm_head" in k for k in weight_map)


def roles_for(name, fr, hr, tied, with_vision=False):
    """Set of roles ("front", "head") that need weight `name`."""
    if any(name.startswith(v) or ("." + v) in name for v in VISION):
        return {"front", "head"} if with_vision else set()
    m = LAYER.search(name)
    if m:
        i = int(m.group(1))
        return {"front"} if fr[0] <= i < fr[1] else {"head"} if hr[0] <= i < hr[1] else set()
    if "embed_tokens" in name:
        return {"front", "head"} if tied else {"front"}
    if "lm_head" in name or re.search(r"(?:^|\.)norm\.", name):
        return {"head"}
    return {"front", "head"}


def plan_files(config, index, front_layers=None, with_vision=False):
    """{"front": set(files), "head": set(files), "shared": set(files), "split": (fr, hr), "tied": bool}."""
    wm = index["weight_map"]
    n = n_layers_of(config)
    fr, hr = plan_split(n, front_layers)
    tied = tied_of(config, wm)
    out = {"front": set(), "head": set()}
    for name, f in wm.items():
        for r in roles_for(name, fr, hr, tied, with_vision):
            out[r].add(f)
    out["shared"] = out["front"] & out["head"]
    out.update(split=(fr, hr), tied=tied, n_layers=n)
    return out


def file_sizes(repo, token=None):
    from huggingface_hub import HfApi
    info = HfApi(token=token).model_info(repo, files_metadata=True)
    return {s.rfilename: (s.size or 0) for s in info.siblings}


def write_sizes(d, repo, sizes):
    """Record the shard sizes Hugging Face lists, so the worker can check
    them at startup (mlx_split.check_local_shards). Merges with an existing
    record for the same repo."""
    from mlx_split import SIZES_FILE
    p = Path(d) / SIZES_FILE
    old = {}
    if p.exists():
        try:
            r = json.loads(p.read_text())
            if r.get("repo") == repo:
                old = dict(r.get("sizes") or {})
        except (OSError, ValueError, AttributeError):
            old = {}
    old.update({f: int(s) for f, s in sizes.items() if s})
    p.write_text(json.dumps({"repo": repo, "sizes": old}, indent=1, sort_keys=True))
    return p


def _resolve_token():
    try:
        from hf_auth import resolve_hf_token
        return resolve_hf_token()
    except Exception:
        return (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or None)


def _progress_path(repo):
    folder = repo.replace("/", "--")
    return Path(os.environ.get("CARAVAN_PROGRESS_DIR", "/tmp")) / f"caravan-progress-{folder}.jsonl"


def _emit_progress_loop(stop_evt, repo, dest, total_bytes, pid):
    """Background: disk → nettop → JSONL hook (truthful under hf_xet)."""
    try:
        from download_progress import combine_progress
    except Exception:
        combine_progress = None
    path = _progress_path(repo)
    try:
        path.write_text("")  # truncate
    except OSError:
        pass
    prev = None
    while not stop_evt.wait(1.0):
        if combine_progress:
            snap = combine_progress(
                dest=str(dest), repo_id=repo, total_bytes=total_bytes,
                pid=pid, prev=prev,
            )
        else:
            snap = {"have_bytes": 0, "source": "starting", "pct": 0, "msg": "starting…",
                    "t": time.time()}
        prev = snap
        try:
            with path.open("a") as f:
                f.write(json.dumps({
                    "t": snap.get("t"),
                    "have_bytes": snap.get("have_bytes"),
                    "total_bytes": snap.get("total_bytes"),
                    "pct": snap.get("pct"),
                    "mb_s": snap.get("mb_s"),
                    "eta_s": snap.get("eta_s"),
                    "source": snap.get("source"),
                    "stalled": snap.get("stalled"),
                    "msg": snap.get("msg"),
                    "pid": pid,
                }) + "\n")
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo"); ap.add_argument("local_dir")
    ap.add_argument("--role", choices=("lead", "packer", "head", "front", "all"), required=True,
                    help="lead: last layers; packer: first layers; all: every shard (1-Mini / copy-all). "
                         "head/front: deprecated aliases")
    ap.add_argument("--packer-layers", "--front-layers", dest="front_layers", type=int, metavar="K",
                    help="layers on Packer 1 (--front-layers: deprecated alias)")
    ap.add_argument("--with-vision", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--gguf-file", default=None,
                    help="GGUF: fetch just this one file (role must be all; only the lead needs it)")
    ap.add_argument("--no-progress", action="store_true",
                    help="skip JSONL progress emitter (tests)")
    a = ap.parse_args(argv)
    role_in = a.role
    a.role = {"lead": "head", "packer": "front"}.get(a.role, a.role)
    shown = {"head": "lead", "front": "packer", "all": "all"}[a.role]
    token = _resolve_token()
    from huggingface_hub import snapshot_download
    d = Path(a.local_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    if a.gguf_file:
        return _fetch_gguf(a, d, token)
    snapshot_download(
        a.repo, local_dir=str(d),
        allow_patterns=["config.json", "model.safetensors.index.json"],
        token=token,
    )
    cfg = json.loads((d / "config.json").read_text())
    idx = json.loads((d / "model.safetensors.index.json").read_text())
    p = plan_files(cfg, idx, a.front_layers, a.with_vision)
    sizes = file_sizes(a.repo, token=token)
    if a.role == "all":
        mine = sorted({f for f in sizes if f.endswith(".safetensors")}
                      or (p["front"] | p["head"]))
    else:
        mine = sorted(p[a.role])
    gb = lambda fs: round(sum(sizes.get(f, 0) for f in fs) / 1e9, 2)  # noqa: E731
    shards = sorted(f for f in sizes if f.endswith(".safetensors"))
    report = {"repo": a.repo, "role": shown, "split": p["split"], "tied": p["tied"], "files": mine,
              "shared": sorted(p["shared"]), "my_gb": gb(mine), "full_gb": gb(shards),
              "other_gb": 0 if a.role == "all" else gb(p["head" if a.role == "front" else "front"])}
    print(json.dumps(report), flush=True)

    stop_evt = threading.Event()
    emitter = None
    if not a.dry_run and not a.no_progress:
        total_b = int(sum(sizes.get(f, 0) for f in mine))
        emitter = threading.Thread(
            target=_emit_progress_loop,
            args=(stop_evt, a.repo, d, total_b, os.getpid()),
            daemon=True, name="caravan-fetch-progress",
        )
        emitter.start()
    try:
        if not a.dry_run:
            snapshot_download(a.repo, local_dir=str(d), allow_patterns=SMALL, token=token)
            _range_fetch_all(a.repo, d, mine, sizes, token)
            write_sizes(d, a.repo, {f: sizes[f] for f in shards})
            print("FETCHED", shown, report["my_gb"], "GB of", report["full_gb"], flush=True)
    finally:
        stop_evt.set()
        if emitter is not None:
            emitter.join(timeout=2)
    return report


def _range_fetch_all(repo, d, names, sizes, token):
    """Big files over HTTP Range so Resume continues a partial file (Day 18)."""
    import range_fetch
    for f in names:
        r = range_fetch.fetch(repo, f, d, int(sizes.get(f) or 0), token=token)
        if r["resumed_from"] and not r["skipped"]:
            print("RESUMED", f, "from", r["resumed_from"], "bytes", flush=True)


def _fetch_gguf(a, d, token):
    """One GGUF file → local_dir. Same progress hook / process name as MLX fetches,
    so the picker's network-byte progress, Stop, Resume and retry all apply.
    Big files go through range_fetch, so a partial .incomplete resumes."""
    from huggingface_hub import snapshot_download
    sizes = file_sizes(a.repo, token=token)
    name = a.gguf_file
    if name not in sizes:
        raise SystemExit(f"{name} not in {a.repo}")
    report = {"repo": a.repo, "role": "all", "files": [name], "gguf": True,
              "my_gb": round(sizes[name] / 1e9, 2), "full_gb": round(sizes[name] / 1e9, 2)}
    print(json.dumps(report), flush=True)
    stop_evt = threading.Event()
    emitter = None
    if not a.dry_run and not a.no_progress:
        emitter = threading.Thread(target=_emit_progress_loop,
                                   args=(stop_evt, a.repo, d, int(sizes[name]), os.getpid()),
                                   daemon=True, name="caravan-fetch-progress")
        emitter.start()
    try:
        if not a.dry_run:
            _range_fetch_all(a.repo, d, [name], sizes, token)
            print("FETCHED gguf", report["my_gb"], "GB", flush=True)
    finally:
        stop_evt.set()
        if emitter is not None:
            emitter.join(timeout=2)
    return report


if __name__ == "__main__":
    main()
