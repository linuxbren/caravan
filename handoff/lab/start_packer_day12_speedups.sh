#!/bin/bash
# Start packer on EXO2 for Day 12 speedups. Usage: TAG [extra mlx_worker args...]
set -euo pipefail
TAG=${1:?tag}; shift || true
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/cv3
case "$TAG" in
  llama) M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit; K=16 ;;
  qwen3) M=$HOME/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit; K=24 ;;
  gemma) M=$HOME/.caravan/mlx-models/mlx-community--gemma-4-26b-a4b-it-4bit; K=15 ;;
  gptoss) M=$HOME/.caravan/mlx-models/mlx-community--gpt-oss-20b-MXFP4-Q8; K=13 ;;
  *) echo "bad tag $TAG"; exit 1 ;;
esac
if [[ ! -d "$M" ]]; then echo "missing model $M"; exit 1; fi
LPM=$(pmset -g | awk '/lowpowermode/{print $2}')
if [[ "$LPM" != "0" ]]; then
  echo "REFUSE: Low Power Mode on packer (lowpowermode=$LPM)"; exit 2
fi
true 2>/dev/null || true
sleep 2
true 2>/dev/null || true
sleep 2
R=$HOME/.caravan/bench-2026-11-03/day12-speedups
mkdir -p "$R"
LOG=$R/packer-${TAG}.log
# shellcheck disable=SC2086
nohup $PY $CV/agent/mlx_worker.py --model "$M" --split-role packer \
  --split-listen 169.254.103.191:5560 --no-split-draft \
  --split-packer-layers "$K" --no-learn \
  "$@" \
  > "$LOG" 2>&1 &
echo $! > "$R/packer.pid"
echo started packer $TAG K=$K pid $(cat "$R/packer.pid") log $LOG
