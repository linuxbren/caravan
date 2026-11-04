#!/bin/bash
# v19 remeasure single Mini on EXO1. VARIANT(v1|v2|v2.1) TAG(llama|qwen3) MODE(write|prefix)
set -uo pipefail
V=$1; TAG=$2; MODE=$3
R=$HOME/.caravan/bench-2026-11-04/v19; S=$R/scripts
case $V in v1) CD=$HOME/dev/caravan-improvements;; v2) CD=$HOME/dev/caravan-v2;; v2.1) CD=$HOME/dev/caravan-v2.1;; esac
QWEN_ARGS="--prompt-cache-size 1 --prompt-cache-bytes 536870912 --prefill-step-size 512"
case $TAG in
  llama) M=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit; EX=""; NT="" ;;
  qwen3) M=mlx-community/Qwen3-30B-A3B-4bit; EX="$QWEN_ARGS"; NT=" /no_think" ;;
esac
[[ $(pmset -g | awk '/lowpowermode/{print $2}') == 0 ]] || { echo REFUSE_LPM; exit 2; }
if [[ $MODE == write ]]; then
  BENCH_ROOT=$R/single CARAVAN_DIR=$CD NO_THINK="$NT" CARAVAN_MLX_EXTRA_ARGS="$EX" \
    /opt/homebrew/bin/python3 -u $S/mlx_bench_v2_p8194.py $V-$TAG-write "$M" 800 main > $R/single-$V-$TAG-write.out 2>&1
  echo rc=$?
else
  d=$R/single/$V-$TAG-prefix; mkdir -p $d
  CMD=$(CARAVAN_MLX_EXTRA_ARGS="$EX" CARAVAN_MLX_CACHE_DIR=$d/mlx-cache /opt/homebrew/bin/python3 - "$CD" "$M" <<'PY'
import sys,shlex; sys.path.insert(0, sys.argv[1]+"/agent"); import mlx_backend as m
print(shlex.join(m.build_mlx_command(sys.argv[2],{},{"port":8194})))
PY
)
  echo "$CMD" > $d/cmd.txt
  CARAVAN_CONFIG=$d/no-config.json CARAVAN_MLX_CACHE_DIR=$d/mlx-cache nohup bash -c "exec $CMD" > $d/server.log 2>&1 &
  P=$!
  for i in $(seq 1 400); do curl -sf http://127.0.0.1:8194/v1/models >/dev/null && break; sleep 1; done
  NAME=$( [[ $TAG == qwen3 ]] && echo mlx-community/Qwen3-30B-A3B-4bit || echo mlx-community/Meta-Llama-3.1-8B-Instruct-4bit )
  if [[ $V == v1 ]]; then NAME=$(awk '{for(i=1;i<NF;i++) if($i=="--model") print $(i+1)}' $d/cmd.txt); fi
  $HOME/.caravan/venvs/mlx/bin/python $HOME/dev/caravan-v3/handoff/lab/day12_prefix_bench.py http://127.0.0.1:8194 $NAME $d/prefix.json 2048 > $d/prefix.out 2>&1
  kill $P; sleep 3; kill -9 $P 2>/dev/null; echo DONE $V $TAG prefix
fi
