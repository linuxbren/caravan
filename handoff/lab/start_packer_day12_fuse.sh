#!/bin/bash
set -euo pipefail
TAG=${1:?tag}
MODE=${2:?mode}   # off|all|force-fused|metal-swiglu
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/cv3
case "$TAG" in
  llama) M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit; K=16 ;;
  qwen3) M=$HOME/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit; K=24 ;;
  gemma) M=$HOME/.caravan/mlx-models/mlx-community--gemma-4-26b-a4b-it-4bit; K=15 ;;
  *) echo "bad tag $TAG"; exit 1 ;;
esac
if [[ ! -d "$M" ]]; then echo "missing model $M"; exit 1; fi
LPM=$(pmset -g | awk '/lowpowermode/{print $2}')
if [[ "$LPM" != "0" ]]; then
  echo "REFUSE: Low Power Mode on packer (lowpowermode=$LPM)"; exit 2
fi
pkill -9 -f 'mlx_worker.py' 2>/dev/null || true
sleep 2
pkill -9 -f 'mlx_worker.py' 2>/dev/null || true
sleep 2
R=$HOME/.caravan/bench-2026-11-03/day12-fused/spanned
mkdir -p "$R"
LOG=$R/packer-${TAG}-${MODE}.log
nohup $PY $CV/agent/mlx_worker.py --model "$M" --split-role packer \
  --split-listen 169.254.103.191:5560 --no-split-draft \
  --split-packer-layers "$K" \
  --fuse-kernels "$MODE" \
  > "$LOG" 2>&1 &
echo $! > "$R/packer.pid"
echo started packer $TAG fuse=$MODE K=$K pid $(cat "$R/packer.pid") log $LOG
