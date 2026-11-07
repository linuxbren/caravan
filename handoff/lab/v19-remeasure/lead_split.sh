#!/bin/bash
# v19 remeasure: Day 12 split lead. TAG MODE(bench|prefix) FLAG(off|on)
set -euo pipefail
PY=$HOME/.caravan/venvs/mlx/bin/python; CV=$HOME/dev/caravan-v3
R=$HOME/.caravan/bench-2026-11-04/v19; PEER=169.254.103.191:5560; URL=http://127.0.0.1:8194
TAG=$1; MODE=$2; FLAG=${3:-off}; NT=""
case "$TAG" in
  qwen3) M=$HOME/.exo/models/mlx-community--Qwen3-30B-A3B-4bit; NAME=mlx-community/Qwen3-30B-A3B-4bit; K=24; NT=no_think ;;
  gemma) M=$HOME/.exo/models/mlx-community--gemma-4-26b-a4b-it-4bit; NAME=mlx-community/gemma-4-26b-a4b-it-4bit; K=15 ;;
  gptoss) M=$HOME/.exo/models/mlx-community--gpt-oss-20b-MXFP4-Q8; NAME=mlx-community/gpt-oss-20b-MXFP4-Q8; K=13 ;;
  llama) M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit; NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit; K=16 ;;
esac
d=$R/split-$TAG-$MODE-$FLAG; mkdir -p $d
[[ $(pmset -g | awk '/lowpowermode/{print $2}') == 0 ]] || { echo REFUSE_LPM; exit 2; }
true 2>/dev/null || true; sleep 2
args=(--model "$M" --split-role lead --split-peer "$PEER" --host 127.0.0.1 --port 8194
      --split-draft-skip-first-load --no-learn --no-split-draft --split-packer-layers "$K" --split-pipeline-chats 1)
[[ $FLAG == on ]] && args+=(--split-shared-prefix-cache)
nohup $PY $CV/agent/mlx_worker.py "${args[@]}" > $d/lead.log 2>&1 &
echo $! > $d/lead.pid
for i in $(seq 1 400); do grep -qE 'listening on http' $d/lead.log 2>/dev/null && break; sleep 1; done
if [[ $MODE == bench ]]; then $PY $CV/bench/v3/split_client.py bench $URL $NAME $d/bench.json $NT > $d/bench.out 2>&1
else $PY $CV/handoff/lab/day12_prefix_bench.py $URL $NAME $d/prefix.json 2048 > $d/prefix.out 2>&1; fi
kill -9 $(cat $d/lead.pid) 2>/dev/null || true; true 2>/dev/null || true; sleep 2
echo DONE $TAG $MODE $FLAG
