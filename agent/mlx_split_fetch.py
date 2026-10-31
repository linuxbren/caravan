"""Split download for a two-Mini MLX split (Caravan v3 prototype, 2026-10-31).

Each Mini fetches only the safetensors shards that hold *its* layers,
straight from Hugging Face -- nothing is relayed through the head.

    python mlx_split_fetch.py <repo> <local_dir> --role head|front [--front-layers K] [--dry-run]

How: read config.json + model.safetensors.index.json (small files, fetched
first), map every weight name to a role, and pass the needed shard files to
huggingface_hub.snapshot_download(allow_patterns=...) together with the
config/tokenizer files.

Weight -> role rules (plan_split() decides the layer ranges, same as the worker):
  * "...layers.<i>." of the language model -> the stage holding layer i
  * embed_tokens -> front; also head when embeddings are tied (no lm_head)
  * lm_head and the final norm -> head
  * vision / audio towers -> nobody (the split is text-only) unless --with-vision
  * anything else -> both (safe default)
Shards are whole files, so a shard that straddles the boundary goes to both
Minis: the planner reports those "shared" shards and their size.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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


def file_sizes(repo):
    from huggingface_hub import HfApi
    info = HfApi().model_info(repo, files_metadata=True)
    return {s.rfilename: (s.size or 0) for s in info.siblings}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo"); ap.add_argument("local_dir")
    ap.add_argument("--role", choices=("head", "front"), required=True)
    ap.add_argument("--front-layers", type=int)
    ap.add_argument("--with-vision", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from huggingface_hub import snapshot_download
    d = Path(a.local_dir).expanduser()
    snapshot_download(a.repo, local_dir=str(d), allow_patterns=["config.json", "model.safetensors.index.json"])
    cfg = json.loads((d / "config.json").read_text())
    idx = json.loads((d / "model.safetensors.index.json").read_text())
    p = plan_files(cfg, idx, a.front_layers, a.with_vision)
    sizes = file_sizes(a.repo)
    mine = sorted(p[a.role])
    gb = lambda fs: round(sum(sizes.get(f, 0) for f in fs) / 1e9, 2)  # noqa: E731
    shards = sorted(f for f in sizes if f.endswith(".safetensors"))
    report = {"repo": a.repo, "role": a.role, "split": p["split"], "tied": p["tied"], "files": mine,
              "shared": sorted(p["shared"]), "my_gb": gb(mine), "full_gb": gb(shards),
              "other_gb": gb(p["head" if a.role == "front" else "front"])}
    print(json.dumps(report), flush=True)
    if not a.dry_run:
        snapshot_download(a.repo, local_dir=str(d), allow_patterns=SMALL + mine)
        print("FETCHED", a.role, report["my_gb"], "GB of", report["full_gb"], flush=True)
    return report


if __name__ == "__main__":
    main()
