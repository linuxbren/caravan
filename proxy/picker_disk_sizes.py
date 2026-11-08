"""Model / cleanup disk sizes, and optional cleanup deletes.

  python3 proxy/picker_disk_sizes.py              # print JSON sizes
  python3 proxy/picker_disk_sizes.py --delete hf-cache [--current REPO]
  python3 proxy/picker_disk_sizes.py --delete drafts
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


SKIP_MODEL_DIRS = {"drafts", "caches", ".cache", "cache"}


def _looks_like_model(p: Path) -> bool:
    """True if dir has MLX/GGUF weight signals (not HF hub caches litter)."""
    if not p.is_dir() or p.name in SKIP_MODEL_DIRS or p.name.startswith("."):
        return False
    if (p / "config.json").is_file():
        return True
    if any(p.glob("*.safetensors")) or any(p.glob("*.gguf")):
        return True
    if (p / "model.safetensors.index.json").is_file():
        return True
    return False


def du_gb(path: Path) -> float:
    path = Path(path).expanduser()
    total = 0
    if not path.exists():
        return 0.0
    if path.is_file():
        try:
            return round(path.stat().st_size / 1e9, 2)
        except OSError:
            return 0.0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return round(total / 1e9, 2)


def helper_sizes():
    import web_helpers
    return {k: {**v, "size_gb": du_gb(Path(v["path"]))} for k, v in web_helpers.inventory().items()}


def sizes() -> dict:
    home = Path.home()
    models = {}
    for root in (home / ".caravan" / "mlx-models", home / ".exo" / "models"):
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if not _looks_like_model(p):
                continue
            models[p.name.replace("--", "/")] = du_gb(p)

    hub = du_gb(home / ".cache" / "huggingface" / "hub")
    leftover = 0.0
    root = home / ".caravan" / "mlx-models"
    if root.is_dir():
        for p in root.iterdir():
            if p.is_dir() and p.name not in SKIP_MODEL_DIRS and not p.name.startswith("."):
                c = p / ".cache" / "huggingface"
                if c.is_dir():
                    leftover += du_gb(c)
    drafts = du_gb(home / ".caravan" / "mlx-models" / "drafts")
    return {
        "models": models,
        "helpers": helper_sizes(),
        "cleanup": {
            "hf-cache": round(hub + leftover, 2),
            "drafts": drafts,
            "hf-hub_only": hub,
            "mlx_leftover_cache": round(leftover, 2),
        },
    }


def delete_kind(kind: str, current: str = "") -> dict:
    kind = (kind or "").strip().removeprefix("cleanup:")
    if not kind.startswith(("draft:", "mtp:")):
        kind = kind.lower()
    cur = (current or "").lower()
    removed = []
    home = Path.home()
    if kind in ("hf-cache", "hf_cache", "cache"):
        hub = home / ".cache" / "huggingface" / "hub"
        if hub.is_dir():
            for p in list(hub.iterdir()):
                if cur and cur.replace("/", "--") in p.name.lower():
                    continue
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    removed.append(str(p))
                elif p.is_file() and p.name != "CACHEDIR.TAG":
                    try:
                        p.unlink(); removed.append(str(p))
                    except OSError:
                        pass
        root = home / ".caravan" / "mlx-models"
        if root.is_dir():
            for p in root.iterdir():
                if not p.is_dir() or p.name in SKIP_MODEL_DIRS or p.name.startswith("."):
                    continue
                if cur and (cur.replace("/", "--") in p.name.lower() or cur in p.name.replace("--", "/").lower()):
                    continue
                c = p / ".cache"
                if c.is_dir():
                    shutil.rmtree(c, ignore_errors=True)
                    removed.append(str(c))
    elif kind.startswith(("draft:", "mtp:")):
        import web_helpers
        return web_helpers.delete_helper(kind, current)
    elif kind == "drafts":
        if current:
            return {"ok": False, "error": "Stop the loaded model before deleting helpers."}
        drafts = home / ".caravan" / "mlx-models" / "drafts"
        if drafts.is_dir():
            for p in list(drafts.iterdir()):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    removed.append(str(p))
                elif p.is_file():
                    try:
                        p.unlink(); removed.append(str(p))
                    except OSError:
                        pass
    else:
        return {"ok": False, "error": f"unknown kind {kind}"}
    return {"ok": True, "kind": kind, "removed": removed}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete")
    ap.add_argument("--current", default="")
    ap.add_argument("--inventory", action="store_true",
                    help="MLX tree completeness for Settings dropdown")
    ap.add_argument('--model-root', help='inspect only this MLX model root (no delete behavior change)')
    a = ap.parse_args(argv)
    if a.inventory:
        # Local import so remote Minis with older trees still run --delete/sizes.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import model_inventory as inv
        print(json.dumps(inv.inventory_payload(roots=[a.model_root] if a.model_root else None)))
        return
    if a.delete:
        print(json.dumps(delete_kind(a.delete, a.current)))
    else:
        print(json.dumps(sizes()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
