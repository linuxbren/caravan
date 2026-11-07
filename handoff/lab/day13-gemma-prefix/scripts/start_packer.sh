#!/bin/bash
set -euo pipefail
TAG=${1:?tag}
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/cv3
case "$TAG" in
  llama) M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit; K=16 ;;
  qwen3) M=$HOME/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit; K=24 ;;
  gemma) M=$HOME/.caravan/mlx-models/mlx-community--gemma-4-26b-a4b-it-4bit; K=15 ;;
  *) echo bad; exit 1 ;;
esac
LPM=$(pmset -g | awk "/lowpowermode/{print \$2}")
[[ "$LPM" == "0" ]] || { echo REFUSE_LPM_PACKER; exit 2; }
true 2>/dev/null || true
sleep 2
R=$HOME/.caravan/bench-2026-11-04/day13-gemma-prefix
mkdir -p "$R"
nohup $PY $CV/agent/mlx_worker.py --model "$M" --split-role packer \
  --split-listen 169.254.103.191:5560 --no-split-draft \
  --split-packer-layers "$K" --no-learn \
  > "$R/packer-${TAG}.log" 2>&1 &
echo $! > "$R/packer.pid"
echo started packer $TAG pid $(cat "$R/packer.pid")
