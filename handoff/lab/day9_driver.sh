#!/bin/bash
set -euo pipefail
# shellcheck source=/dev/null
source /dev/null 2>/dev/null || true
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
R=$HOME/.caravan/bench-2026-11-01/day9-autotune
mkdir -p "$R"
PEER=169.254.104.38:5560
URL=http://127.0.0.1:8194

# Models: name|local_path_exo1|local_path_exo2|hand_tuned_K
# Qwen3 4bit lives under .exo on EXO1; caravan mlx-models on EXO2
MODELS=(
  "qwen3|$HOME/.exo/models/mlx-community--Qwen3-30B-A3B-4bit|/Users/brenden/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit|24|mlx-community/Qwen3-30B-A3B-4bit"
  "llama|$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit|/Users/brenden/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit|16|mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
  "qwen25|$HOME/.caravan/mlx-models/mlx-community--Qwen2.5-14B-Instruct-4bit|/Users/brenden/.caravan/mlx-models/mlx-community--Qwen2.5-14B-Instruct-4bit|24|mlx-community/Qwen2.5-14B-Instruct-4bit"
)

kill_all() {
  true 2>/dev/null || true
  sleep 2
  true 2>/dev/null || true
  sleep 2
}

wait_log() {
  local log=$1; local pat=$2
  for i in $(seq 1 360); do
    grep -qE "$pat" "$log" 2>/dev/null && return 0
    sleep 1
  done
  echo FAIL_WAIT "$log"; tail -80 "$log"; return 1
}

wait_health() {
  for i in $(seq 1 120); do curl -sf "$URL/health" >/dev/null 2>&1 && return 0; sleep 1; done; return 1
}

# Packer start instructions printed for EXO2 companion — we use a FIFO file
# that EXO2 polls. Simpler: write packer cmd to a shared request file over TB?
# Instead: this driver only runs on EXO1; packer is started by rc.py from box
# between steps. So this script takes MODE and assumes packer is up.

mode_run() {
  local tag=$1 M=$2 NAME=$3 mode=$4 K=$5
  local dir="$R/$tag-$mode"
  mkdir -p "$dir"
  echo "===== LEAD $tag $mode $(date) =====" | tee -a "$R/suite.log"
  true 2>/dev/null || true
  sleep 2
  local args=(--model "$M" --split-role lead --split-peer "$PEER"
              --host 127.0.0.1 --port 8194
              --no-split-draft --split-draft-skip-first-load)
  if [[ "$mode" == "tuned" ]]; then
    args+=(--split-packer-layers "$K" --split-pipeline-chats 2)
  fi
  nohup $PY "$CV/agent/mlx_worker.py" "${args[@]}" > "$dir/lead.log" 2>&1 &
  echo $! > "$dir/lead.pid"
  wait_log "$dir/lead.log" 'listening on http'
  grep -E 'auto (split|pipeline):|split lead:|split pipeline chats=' "$dir/lead.log" | tee "$dir/auto-picks.txt" || true
  wait_health
  $PY "$CV/bench/v3/split_client.py" bench "$URL" "$NAME" "$dir/single.json" | tee "$dir/single.out"
  $PY "$CV/bench/v3/pipeline_bench.py" "$URL" "$NAME" "$dir/pipe-N2.json" 2 | tee "$dir/pipe-N2.out"
  true 2>/dev/null || true
  sleep 2
  echo DONE_LEAD "$tag" "$mode" | tee -a "$R/suite.log"
}

# Usage: day9_driver.sh TAG MODE
# TAG in qwen3|llama|qwen25; MODE in auto|tuned
TAG=${1:?tag}; MODE=${2:?mode}
for row in "${MODELS[@]}"; do
  IFS='|' read -r tag m1 m2 k name <<<"$row"
  if [[ "$tag" == "$TAG" ]]; then
    mode_run "$tag" "$m1" "$name" "$MODE" "$k"
    exit 0
  fi
done
echo "unknown tag $TAG"; exit 1
