#!/bin/bash
# Day 12 #17 spanned A/B. Runs on EXO1. Packer must already be listening on 5560
# with the SAME --fuse-kernels MODE.
# Usage: day12_fuse_spanned_driver.sh TAG MODE PIPE
#   TAG: llama|qwen3|gemma
#   MODE: off|all|force-fused|metal-swiglu
#   PIPE: 1|2   (single chat vs two overlapped; sets --split-pipeline-chats)
set -euo pipefail
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
R=$HOME/.caravan/bench-2026-11-03/day12-fused/spanned
mkdir -p "$R"
PEER=169.254.103.191:5560
URL=http://127.0.0.1:8194
TAG=${1:?tag}; MODE=${2:?mode}; PIPE=${3:?pipe}

case "$TAG" in
  llama)
    M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit
    NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit
    K=16
    ;;
  qwen3)
    M=$HOME/.exo/models/mlx-community--Qwen3-30B-A3B-4bit
    NAME=mlx-community/Qwen3-30B-A3B-4bit
    K=24
    ;;
  gemma)
    M=$HOME/.exo/models/mlx-community--gemma-4-26b-a4b-it-4bit
    NAME=mlx-community/gemma-4-26b-a4b-it-4bit
    K=15
    ;;
  *) echo "unknown tag $TAG"; exit 1 ;;
esac

dir="$R/${TAG}-${MODE}-n${PIPE}"
mkdir -p "$dir"
echo "===== SPANNED $TAG fuse=$MODE pipe=$PIPE $(date) =====" | tee -a "$R/suite.log"

LPM=$(pmset -g | awk '/lowpowermode/{print $2}')
if [[ "$LPM" != "0" ]]; then
  echo "REFUSE: Low Power Mode on lead (lowpowermode=$LPM)" | tee -a "$R/suite.log"
  exit 2
fi

# Stop only lead workers; packer is managed by the orch
pkill -9 -f 'mlx_worker.py --split-role lead' 2>/dev/null || true
pkill -9 -f 'mlx_worker.py --split-role none' 2>/dev/null || true
sleep 2

args=(--model "$M" --split-role lead --split-peer "$PEER"
      --host 127.0.0.1 --port 8194
      --no-split-draft --split-draft-skip-first-load --no-learn
      --split-packer-layers "$K"
      --split-pipeline-chats "$PIPE"
      --fuse-kernels "$MODE")

nohup $PY "$CV/agent/mlx_worker.py" "${args[@]}" > "$dir/lead.log" 2>&1 &
echo $! > "$dir/lead.pid"

for i in $(seq 1 300); do
  grep -qE 'listening on http' "$dir/lead.log" 2>/dev/null && break
  sleep 1
done
grep -E 'fuse kernels:|listening on|loaded |split lead:|split pipeline' "$dir/lead.log" \
  | tee "$dir/startup.txt" || true
curl -sf "$URL/health" >/dev/null

if [[ "$PIPE" == "1" ]]; then
  # Single-chat light bench (no pp4096)
  $PY "$CV/handoff/lab/day12_fuse_light_bench.py" "$URL" "$NAME" "$dir/single.json" \
    | tee "$dir/single.out"
else
  $PY "$CV/bench/v3/pipeline_bench.py" "$URL" "$NAME" "$dir/pipe-N2.json" "$PIPE" \
    | tee "$dir/pipe-N2.out"
fi

# Capture peak hints from lead log
grep -E 'peak |fuse kernels:|split lead:' "$dir/lead.log" | tail -40 > "$dir/lead-peaks.txt" || true

pkill -9 -f 'mlx_worker.py --split-role lead' 2>/dev/null || true
sleep 2
echo DONE_SPANNED "$TAG" "$MODE" "n$PIPE" | tee -a "$R/suite.log"
