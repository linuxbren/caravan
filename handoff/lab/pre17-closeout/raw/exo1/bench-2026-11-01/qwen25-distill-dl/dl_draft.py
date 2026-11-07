from pathlib import Path
from huggingface_hub import snapshot_download
dest = Path.home() / ".caravan/mlx-models/drafts/Qwen2.5-0.5B-Instruct-4bit"
dest.parent.mkdir(parents=True, exist_ok=True)
print("START draft", flush=True)
snapshot_download(repo_id="mlx-community/Qwen2.5-0.5B-Instruct-4bit", local_dir=str(dest), max_workers=1)
print("DONE draft", round(sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())/1e9, 3), "GB", flush=True)
