#!/bin/bash
# Idea 2: adaptive PL vs helper-only. TAG MODE
# MODE: helper | adaptive
set -euo pipefail
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
R=$HOME/.caravan/bench-2026-11-03/day12-speedups/idea2
mkdir -p "$R"
PEER=169.254.103.191:5560
URL=http://127.0.0.1:8194
TAG=${1:?tag}; MODE=${2:?mode}

case "$TAG" in
  llama)
    M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit
    NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit; K=16
    D=$HOME/.caravan/mlx-models/drafts/Llama-3.2-1B-Instruct-4bit; SK=3 ;;
  qwen3)
    M=$HOME/.exo/models/mlx-community--Qwen3-30B-A3B-4bit
    NAME=mlx-community/Qwen3-30B-A3B-4bit; K=24
    D=$HOME/.caravan/mlx-models/drafts/Qwen3-0.6B-4bit; SK=3 ;;
  gemma)
    M=$HOME/.exo/models/mlx-community--gemma-4-26b-a4b-it-4bit
    NAME=mlx-community/gemma-4-26b-a4b-it-4bit; K=15
    D=$HOME/.caravan/mlx-models/drafts/gemma-3-270m-it-4bit; SK=2 ;;
  *) echo bad; exit 1 ;;
esac

dir="$R/${TAG}-${MODE}"
mkdir -p "$dir"
LPM=$(pmset -g | awk '/lowpowermode/{print $2}')
[[ "$LPM" == "0" ]] || { echo REFUSE_LPM; exit 2; }

pkill -9 -f 'mlx_worker.py' 2>/dev/null || true
sleep 2
pkill -9 -f 'mlx_worker.py' 2>/dev/null || true
sleep 2

args=(--model "$M" --split-role lead --split-peer "$PEER"
      --host 127.0.0.1 --port 8194
      --split-draft-skip-first-load --no-learn
      --split-packer-layers "$K" --split-pipeline-chats 1
      --split-draft-model "$D" --split-speculate-k "$SK")
if [[ "$MODE" == "adaptive" ]]; then
  args+=(--split-prompt-lookup 3 --split-prompt-lookup-adaptive)
fi

nohup $PY "$CV/agent/mlx_worker.py" "${args[@]}" > "$dir/lead.log" 2>&1 &
echo $! > "$dir/lead.pid"
for i in $(seq 1 360); do grep -qE 'listening on http' "$dir/lead.log" 2>/dev/null && break; sleep 1; done
curl -sf "$URL/health" >/dev/null
$PY "$CV/bench/v3/speculate_bench.py" "$URL" "$NAME" "$dir/suite.json" "$MODE" suite | tee "$dir/suite.out"
kill -9 "$(cat "$dir/lead.pid")" 2>/dev/null || true
pkill -9 -f 'mlx_worker.py' 2>/dev/null || true
sleep 2
echo DONE_IDEA2 "$TAG" "$MODE"
