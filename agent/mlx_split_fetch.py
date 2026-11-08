"""Split download for an N-Mini MLX split (Caravan v3 prototype, 2026-10-31).

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
MTP = re.compile(r"(?:^|\.)mtp\.")
VISION = ("vision", "audio", "embed_vision", "embed_audio", "multi_modal_projector")


def n_layers_of(config):
    for c in (config, config.get("text_config") or {}):
        if c.get("num_hidden_layers"):
            return int(c["num_hidden_layers"])
    raise ValueError("config has no num_hidden_layers")


def tied_of(config, weight_map):
    """Tied embeddings: the head stage computes logits with embed_tokens.

    True when the checkpoint has no lm_head weights, OR when config.json says
    tie_word_embeddings=true (top level or text_config). mlx_lm follows the
    config flag: it builds no lm_head module and drops lm_head.* in sanitize,
    even if the file ships one. Day 18 bug: Dark Champion 21B (mixtral) ships
    lm_head AND tie_word_embeddings=true, so the lead skipped the embed shard
    and strict=False left embed_tokens at random init -> pure gibberish."""
    cfg = config or {}
    flags = [cfg.get("tie_word_embeddings")]
    for sub in ("text_config", "llm_config"):
        if isinstance(cfg.get(sub), dict):
            flags.append(cfg[sub].get("tie_word_embeddings"))
    if any(f is True for f in flags):
        return True
    return not any("lm_head" in k for k in weight_map)


def roles_for(name, fr, hr, tied, with_vision=False):
    """Set of roles ("front", "head") that need weight `name`."""
    if any(name.startswith(v) or ("." + v) in name for v in VISION):
        return {"front", "head"} if with_vision else set()
    if MTP.search(name):
        # Native multi-token-prediction head (mtp.*): runs on final hidden
        # states, so only the lead (head stage) ever needs it.
        return {"head"}
    m = LAYER.search(name)
    if m:
        i = int(m.group(1))
        return {"front"} if fr[0] <= i < fr[1] else {"head"} if hr[0] <= i < hr[1] else set()
    if "embed_tokens" in name:
        return {"front", "head"} if tied else {"front"}
    if "lm_head" in name or re.search(r"(?:^|\.)norm\.", name):
        return {"head"}
    return {"front", "head"}


def head_only_reason(config, weight_map):
    """Non-empty when the repo is a standalone helper head (e.g.
    mlx-community/Qwen3.6-35B-A3B-MTP-4bit: model_type qwen3_5_mtp, 46 keys,
    one `layers.0`, no embed_tokens) rather than a chat model. Its config
    still says num_hidden_layers=40, so splitting it would plan 40 layers
    that do not exist."""
    cfg = config or {}
    mt = str(cfg.get("model_type") or "")
    if mt.endswith("_mtp") or mt.endswith("_nextn"):
        return f"{mt} is a guess-ahead helper head, not a chat model"
    if weight_map and not any("embed_tokens" in k or "wte" in k or "tok_embeddings" in k
                              for k in weight_map):
        idx = {int(m.group(1)) for k in weight_map for m in [LAYER.search(k)] if m}
        try:
            n = n_layers_of(cfg)
        except Exception:
            n = None
        if n and len(idx) < n:
            return f"checkpoint has {len(idx)} of {n} layers and no embeddings (helper head?)"
    return ""


def plan_files(config, index, front_layers=None, with_vision=False):
    """{"front": set(files), "head": set(files), "shared": set(files), "split": (fr, hr), "tied": bool}.

    Layers numbered >= num_hidden_layers (DeepSeek/GLM nextn MTP layers) go
    to neither stage: mlx_lm drops them at load. `mtp.*` keys go to the head."""
    wm = index["weight_map"]
    why = head_only_reason(config, wm)
    if why:
        raise ValueError(f"cannot split: {why}")
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


def plan_stage_files(config, index, counts, with_vision=False):
    """N-stage shard plan. Whole boundary shards can be needed by many stages."""
    from mlx_split import plan_ranges
    wm = index["weight_map"]
    why = head_only_reason(config, wm)
    if why:
        raise ValueError(f"cannot split: {why}")
    ranges = plan_ranges(n_layers_of(config), counts)
    tied = tied_of(config, wm)
    stages = [set() for _ in ranges]
    last = len(stages) - 1
    for name, filename in wm.items():
        if any(name.startswith(v) or ("." + v) in name for v in VISION):
            owners = range(len(stages)) if with_vision else []
        elif MTP.search(name):
            owners = [last]
        elif LAYER.search(name):
            layer = int(LAYER.search(name).group(1))
            owners = [i for i, (a, b) in enumerate(ranges) if a <= layer < b]
        elif "embed_tokens" in name:
            owners = {0, last} if tied else [0]
        elif "lm_head" in name or re.search(r"(?:^|\.)norm\.", name):
            owners = [last]
        else:
            owners = range(len(stages))
        for i in owners:
            stages[i].add(filename)
    shared = {f for files in stages for f in files if sum(f in fs for fs in stages) > 1}
    return {"stages": stages, "split": ranges, "tied": tied, "shared": shared}


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
    ap.add_argument("--split-counts", help="N-stage counts in forward order, e.g. 10,10,12")
    ap.add_argument("--stage-index", type=int, help="zero-based stage in --split-counts")
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
    if a.split_counts:
        from mlx_split import parse_counts
        p = plan_stage_files(cfg, idx, parse_counts(a.split_counts), a.with_vision)
        if a.stage_index is None or not 0 <= a.stage_index < len(p["stages"]):
            ap.error("--split-counts requires a valid --stage-index")
        if a.role != "all" and (a.role == "head") != (a.stage_index == len(p["stages"])-1):
            ap.error("--role lead must use the last stage; packer must use an earlier stage")
        p["front"], p["head"] = p["stages"][0], p["stages"][-1]
    else:
        if a.stage_index is not None:
            ap.error("--stage-index requires --split-counts")
        p = plan_files(cfg, idx, a.front_layers, a.with_vision)
    sizes = file_sizes(a.repo, token=token)
    if a.role == "all":
        mine = sorted({f for f in sizes if f.endswith(".safetensors")}
                      or (set().union(*p["stages"]) if a.split_counts else (p["front"] | p["head"])))
    else:
        mine = sorted(p["stages"][a.stage_index] if a.split_counts else p[a.role])
    gb = lambda fs: round(sum(sizes.get(f, 0) for f in fs) / 1e9, 2)  # noqa: E731
    shards = sorted(f for f in sizes if f.endswith(".safetensors"))
    other = (set().union(*(files for i, files in enumerate(p["stages"]) if i != a.stage_index))
             if a.split_counts else p["head" if a.role == "front" else "front"])
    report = {"repo": a.repo, "role": shown, "split": p["split"], "tied": p["tied"], "files": mine,
              "shared": sorted(p["shared"]), "my_gb": gb(mine), "full_gb": gb(shards),
              "other_gb": 0 if a.role == "all" else gb(other)}
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
