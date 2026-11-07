#!/bin/bash
# Day 12 ROADMAP #17: one-Mini A/B with/without --fuse-kernels.
# Usage: day12_fuse_driver.sh TAG MODE
#   TAG: llama|qwen3
#   MODE: off|all
set -euo pipefail
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
R=$HOME/.caravan/bench-2026-11-03/day12-fused
mkdir -p "$R"
URL=http://127.0.0.1:8194
TAG=${1:?tag}; MODE=${2:?mode}

case "$TAG" in
  llama)
    M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit
    NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit
    ;;
  qwen3)
    M=$HOME/.exo/models/mlx-community--Qwen3-30B-A3B-4bit
    NAME=mlx-community/Qwen3-30B-A3B-4bit
    ;;
  *) echo "unknown tag $TAG"; exit 1 ;;
esac

dir="$R/${TAG}-${MODE}"
mkdir -p "$dir"
echo "===== ONE-MINI $TAG fuse=$MODE $(date) =====" | tee -a "$R/suite.log"

true 2>/dev/null || true
sleep 2
true 2>/dev/null || true
sleep 2

# Refuse to bench if Low Power Mode is on
LPM=$(pmset -g | awk '/lowpowermode/{print $2}')
if [[ "$LPM" != "0" ]]; then
  echo "REFUSE: Low Power Mode is on (lowpowermode=$LPM)" | tee -a "$R/suite.log"
  exit 2
fi

args=(--model "$M" --split-role none --host 127.0.0.1 --port 8194 --no-learn)
if [[ "$MODE" != "off" ]]; then
  args+=(--fuse-kernels "$MODE")
else
  args+=(--fuse-kernels off)
fi

nohup $PY "$CV/agent/mlx_worker.py" "${args[@]}" > "$dir/lead.log" 2>&1 &
echo $! > "$dir/lead.pid"

for i in $(seq 1 180); do
  grep -qE 'listening on http' "$dir/lead.log" 2>/dev/null && break
  sleep 1
done
grep -E 'fuse kernels:|listening on|loaded ' "$dir/lead.log" | tee "$dir/startup.txt" || true
curl -sf "$URL/health" >/dev/null

$PY "$CV/bench/v3/split_client.py" bench "$URL" "$NAME" "$dir/single.json" | tee "$dir/single.out"

true 2>/dev/null || true
sleep 2
echo DONE_ONE "$TAG" "$MODE" | tee -a "$R/suite.log"
