#!/bin/bash
# Day 12 Idea 1: pipeline N × guess-ahead on/off. Runs on EXO1.
# Usage: day12_speedups_idea1_driver.sh TAG PIPE DRAFT
#   TAG: llama|qwen3|gemma
#   PIPE: 1|2
#   DRAFT: off|on
set -euo pipefail
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
R=$HOME/.caravan/bench-2026-11-03/day12-speedups/idea1
mkdir -p "$R"
PEER=169.254.103.191:5560
URL=http://127.0.0.1:8194
TAG=${1:?tag}; PIPE=${2:?pipe}; DRAFT=${3:?draft}

case "$TAG" in
  llama)
    M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit
    NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit
    K=16
    D=$HOME/.caravan/mlx-models/drafts/Llama-3.2-1B-Instruct-4bit
    SK=3
    ;;
  qwen3)
    M=$HOME/.exo/models/mlx-community--Qwen3-30B-A3B-4bit
    NAME=mlx-community/Qwen3-30B-A3B-4bit
    K=24
    D=$HOME/.caravan/mlx-models/drafts/Qwen3-0.6B-4bit
    SK=3
    ;;
  gemma)
    M=$HOME/.exo/models/mlx-community--gemma-4-26b-a4b-it-4bit
    NAME=mlx-community/gemma-4-26b-a4b-it-4bit
    K=15
    D=$HOME/.caravan/mlx-models/drafts/gemma-3-270m-it-4bit
    SK=2
    ;;
  *) echo "unknown tag $TAG"; exit 1 ;;
esac

dir="$R/${TAG}-n${PIPE}-draft${DRAFT}"
mkdir -p "$dir"
echo "===== IDEA1 $TAG pipe=$PIPE draft=$DRAFT $(date) =====" | tee -a "$R/suite.log"

LPM=$(pmset -g | awk '/lowpowermode/{print $2}')
if [[ "$LPM" != "0" ]]; then
  echo "REFUSE: Low Power Mode on lead (lowpowermode=$LPM)" | tee -a "$R/suite.log"
  exit 2
fi

# Stop any prior lead on test port (pidfile + pattern)
if [[ -f "$dir/lead.pid" ]]; then kill -9 "$(cat "$dir/lead.pid")" 2>/dev/null || true; fi
true 2>/dev/null || true
sleep 2
true 2>/dev/null || true
sleep 2

args=(--model "$M" --split-role lead --split-peer "$PEER"
      --host 127.0.0.1 --port 8194
      --split-draft-skip-first-load --no-learn
      --split-packer-layers "$K"
      --split-pipeline-chats "$PIPE")

if [[ "$DRAFT" == "on" ]]; then
  if [[ ! -d "$D" ]]; then echo "missing draft $D"; exit 1; fi
  args+=(--split-draft-model "$D" --split-speculate-k "$SK")
else
  args+=(--no-split-draft)
fi

nohup $PY "$CV/agent/mlx_worker.py" "${args[@]}" > "$dir/lead.log" 2>&1 &
echo $! > "$dir/lead.pid"

for i in $(seq 1 360); do
  grep -qE 'listening on http' "$dir/lead.log" 2>/dev/null && break
  sleep 1
done
grep -E 'listening on|loaded |split lead:|split pipeline|split speculate' "$dir/lead.log" \
  | tee "$dir/startup.txt" || true
curl -sf "$URL/health" >/dev/null

$PY "$CV/bench/v3/pipeline_bench.py" "$URL" "$NAME" "$dir/pipe-N${PIPE}.json" "$PIPE" \
  | tee "$dir/pipe-N${PIPE}.out"

grep -E 'peak |split lead:|speculate' "$dir/lead.log" | tail -40 > "$dir/lead-peaks.txt" || true

if [[ -f "$dir/lead.pid" ]]; then kill -9 "$(cat "$dir/lead.pid")" 2>/dev/null || true; fi
true 2>/dev/null || true
true 2>/dev/null || true
sleep 2
echo DONE_IDEA1 "$TAG" "n$PIPE" "draft$DRAFT" | tee -a "$R/suite.log"
