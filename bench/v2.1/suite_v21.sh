#!/bin/bash
# Caravan v2.1 A/B suite (2026-10-31). TEST ports only (8190/8192); exo stays paused.
cd "$(dirname "$0")"
PY=/opt/homebrew/bin/python3
QWEN_ARGS="--prompt-cache-size 1 --prompt-cache-bytes 536870912 --prefill-step-size 512"
export BENCH_ROOT=~/.caravan/bench-2026-10-31/v2.1
run() { echo "=== $(date +%T) $*"; "$@" > /dev/null 2>&1; echo "=== $(date +%T) rc=$?"; }
for what in ${SUITE:-qwen others resume}; do
  if [ "$what" = qwen ]; then
    CARAVAN_MLX_EXTRA_ARGS="$QWEN_ARGS" run $PY ab_bench.py ab-qwen mlx-community/Qwen3-30B-A3B-4bit ${ROUNDS:-3} ${REPS:-2}
  elif [ "$what" = others ]; then
    run $PY ab_bench.py ab-gemma mlx-community/gemma-4-26b-a4b-it-4bit 1 3 v1,v2,v2.1
    run $PY ab_bench.py ab-gptoss mlx-community/gpt-oss-20b-MXFP4-Q8 1 3 v1,v2,v2.1
  elif [ "$what" = resume ]; then
    CARAVAN_DIR=~/dev/caravan-v2.1 RESUME=4000 NO_THINK=" /no_think" CARAVAN_MLX_EXTRA_ARGS="$QWEN_ARGS" \
      run $PY ../v2/mlx_bench_v2.py v21-qwen-resume mlx-community/Qwen3-30B-A3B-4bit 200 resume
  fi
done
echo SUITEDONE
