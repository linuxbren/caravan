#!/bin/bash
set -euo pipefail
TAG=${1:?tag}
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/cv3
case "$TAG" in
  llama) M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit ;;
  qwen3) M=$HOME/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit ;;
  gemma) M=$HOME/.caravan/mlx-models/mlx-community--gemma-4-26b-a4b-it-4bit ;;
  gptoss) M=$HOME/.caravan/mlx-models/mlx-community--gpt-oss-20b-MXFP4-Q8 ;;
  qwen25) M=$HOME/.caravan/mlx-models/mlx-community--Qwen2.5-14B-Instruct-4bit ;;
  distill) M=$HOME/.caravan/mlx-models/mlx-community--DeepSeek-R1-Distill-Qwen-14B-4bit ;;
  *) echo "bad tag $TAG"; exit 1 ;;
esac
if [[ ! -d "$M" ]]; then echo "missing model $M"; exit 1; fi
true 2>/dev/null || true
sleep 2
mkdir -p $HOME/.caravan/bench-2026-11-02/day10-learn
LOG=$HOME/.caravan/bench-2026-11-02/day10-learn/packer-$TAG.log
nohup $PY $CV/agent/mlx_worker.py --model "$M" --split-role packer \
  --split-listen 169.254.104.38:5560 --no-split-draft \
  > "$LOG" 2>&1 &
echo $! > $HOME/.caravan/bench-2026-11-02/day10-learn/packer.pid
echo started packer $TAG pid $(cat $HOME/.caravan/bench-2026-11-02/day10-learn/packer.pid)
