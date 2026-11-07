#!/bin/bash
# Start packer on EXO2. Usage: start_packer.sh MODEL_DIR TAG KA_FLAG OUT_DIR
set -euo pipefail
MODEL_DIR="$1"
TAG="$2"
KA_FLAG="$3"
OUT_DIR="$4"
VENV="$HOME/.caravan/venvs/mlx/bin/python"
REPO="$HOME/cv3"
CACHE="$OUT_DIR/cache-packer-$TAG"
mkdir -p "$CACHE" "$OUT_DIR"
pkill -f "mlx_worker.py" 2>/dev/null || true
sleep 2
LOG="$OUT_DIR/packer-$TAG.log"
nohup "$VENV" "$REPO/agent/mlx_worker.py" --split-role packer \
  --split-listen 169.254.104.38:5560 --model "$MODEL_DIR" --cache-dir "$CACHE" \
  --wired-limit startup --no-persist $KA_FLAG > "$LOG" 2>&1 &
echo "packer_pid=$!"
for i in $(seq 1 40); do
  if grep -q "listening on" "$LOG" 2>/dev/null; then echo READY; tail -6 "$LOG"; break; fi
  if grep -qi Traceback "$LOG" 2>/dev/null; then echo FAIL; cat "$LOG"; exit 1; fi
  sleep 2
done
