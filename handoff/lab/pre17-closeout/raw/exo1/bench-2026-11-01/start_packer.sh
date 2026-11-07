#!/bin/bash
set -euo pipefail
M=$1; K=$2
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/cv3
LOG=$HOME/.caravan/bench-2026-11-01/packer.log
mkdir -p "$(dirname "$LOG")"
pkill -9 -f mlx_worker.py 2>/dev/null || true
sleep 2
nohup $PY $CV/agent/mlx_worker.py \
  --model "$M" \
  --split-role packer --split-listen 169.254.104.38:5560 \
  --split-packer-layers "$K" \
  --host 127.0.0.1 --port 8195 \
  > "$LOG" 2>&1 &
echo PID=$!
for i in $(seq 1 240); do
  grep -qE 'packer listening|listening on|ready' "$LOG" 2>/dev/null && { echo PACKER_UP; tail -5 "$LOG"; exit 0; }
  sleep 1
done
echo PACKER_FAIL; tail -40 "$LOG"; exit 1
