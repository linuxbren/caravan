#!/usr/bin/env python3
from pathlib import Path
from huggingface_hub import snapshot_download
import os
print("HF_TOKEN_SET", bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")), flush=True)
dest_root = Path.home() / ".caravan/mlx-models"
drafts = dest_root / "drafts"
drafts.mkdir(parents=True, exist_ok=True)
jobs = [
  ("mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit", dest_root / "mlx-community--DeepSeek-R1-Distill-Qwen-14B-4bit"),
  ("mlx-community/Qwen2.5-0.5B-Instruct-4bit", drafts / "Qwen2.5-0.5B-Instruct-4bit"),
]
for repo, dest in jobs:
  print("START", repo, flush=True)
  snapshot_download(repo_id=repo, local_dir=str(dest), max_workers=1)
  size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) / 1e9
  print("DONE", repo, "size", round(size, 3), "GB", flush=True)
print("ALL_DONE", flush=True)
