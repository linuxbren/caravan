#!/bin/bash
# Caravan v1 vs v2, MLX path (2026-10-31). TEST ports only (8190/8192); exo stays paused.
# v2 = this checkout (Caravan MLX worker); v1 16k resume = ~/dev/caravan-improvements (mlx_lm.server).
cd "$(dirname "$0")"
PY=/opt/homebrew/bin/python3
QWEN_ARGS="--prompt-cache-size 1 --prompt-cache-bytes 536870912 --prefill-step-size 512"
V2=$(cd ../.. && pwd)
run() { echo "=== $(date +%T) $*"; "$@" > /dev/null 2>&1; echo "=== $(date +%T) rc=$?"; }
for what in ${SUITE:-v2 v1_16k}; do
  if [ "$what" = v2 ]; then
    CARAVAN_DIR=$V2 run $PY mlx_bench_v2.py v2-gptoss mlx-community/gpt-oss-20b-MXFP4-Q8 800
    CARAVAN_DIR=$V2 run $PY mlx_bench_v2.py v2-gemma mlx-community/gemma-4-26b-a4b-it-4bit 1000
    CARAVAN_DIR=$V2 NO_THINK=" /no_think" CARAVAN_MLX_EXTRA_ARGS="$QWEN_ARGS" run $PY mlx_bench_v2.py v2-qwen mlx-community/Qwen3-30B-A3B-4bit 200
  elif [ "$what" = v2_kv8 ]; then
    # Qwen3 at 16k doesn't fit with a 16-bit cache (Metal OOM); try an 8-bit cache for its full-attention layers.
    CARAVAN_DIR=$V2 NO_THINK=" /no_think" CARAVAN_MLX_EXTRA_ARGS="$QWEN_ARGS --kv-bits 8" run $PY mlx_bench_v2.py v2-qwen-kv8 mlx-community/Qwen3-30B-A3B-4bit 200
  else
    V1=~/dev/caravan-improvements
    CARAVAN_DIR=$V1 RESUME=16000 run $PY mlx_bench_v2.py v1-gptoss-16k mlx-community/gpt-oss-20b-MXFP4-Q8 800 resume
    CARAVAN_DIR=$V1 RESUME=16000 run $PY mlx_bench_v2.py v1-gemma-16k mlx-community/gemma-4-26b-a4b-it-4bit 1000 resume
    CARAVAN_DIR=$V1 RESUME=16000 NO_THINK=" /no_think" CARAVAN_MLX_EXTRA_ARGS="$QWEN_ARGS" run $PY mlx_bench_v2.py v1-qwen-16k mlx-community/Qwen3-30B-A3B-4bit 200 resume
  fi
done
echo SUITEDONE
