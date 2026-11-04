#!/bin/bash
# v19 remeasure v0 (main 45ed2c2 + old llama.cpp build, q8_0). MODE write|prefix  TAG llama|qwen3
set -uo pipefail
MODE=$1; TAG=$2
R=$HOME/.caravan/bench-2026-11-04/v19; S=$R/scripts
case $TAG in
  llama) G=$HOME/.caravan/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf; NT=""; UB=2048; NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit ;;
  qwen3) G=$HOME/.caravan/models/Qwen3-30B-A3B-Q4_K_S.gguf; NT=" /no_think"; UB=1024; NAME=mlx-community/Qwen3-30B-A3B-4bit ;;
esac
[[ $(pmset -g | awk '/lowpowermode/{print $2}') == 0 ]] || { echo REFUSE_LPM; exit 2; }
if [[ $MODE == write ]]; then
  sed -e 's#^LP, PP = 8180, 8190#LP, PP = 8194, 8190#' \
      -e 's#".caravan/bench-2026-10-30/improvements"#".caravan/bench-2026-11-04/v19/v0"#' \
      -e 's#sys.path.insert(0, str(Path(__file__).parent)); from common#sys.path.insert(0, str(Path.home() / "dev/caravan-v3/bench/improvements")); from common#' \
      $HOME/dev/caravan-v3/bench/improvements/imp_bench.py > $S/imp_bench_p8194.py
  CARAVAN_DIR=$R/caravan-v0 LLAMA_BIN=$HOME/dev/llama.cpp/build/bin KV=q8_0 NO_THINK="$NT" \
    /opt/homebrew/bin/python3 -u $S/imp_bench_p8194.py v0-$TAG-write $G 200 $UB 2 8192 main,quality > $R/v0-$TAG-write.out 2>&1
  echo rc=$?
else
  d=$R/v0/v0-$TAG-prefix; mkdir -p $d
  nohup $HOME/dev/llama.cpp/build/bin/llama-server -m $G --port 8194 -c 16384 --parallel 1 -ngl 999 -fa on -ctk q8_0 -ctv q8_0 -b 2048 -ub $UB > $d/server.log 2>&1 &
  P=$!
  for i in $(seq 1 300); do curl -sf http://127.0.0.1:8194/health >/dev/null && break; sleep 1; done
  $HOME/.caravan/venvs/mlx/bin/python $HOME/dev/caravan-v3/handoff/lab/day12_prefix_bench.py http://127.0.0.1:8194 $NAME $d/prefix.json 2048 > $d/prefix.out 2>&1
  kill $P; sleep 3; kill -9 $P 2>/dev/null; echo DONE v0 $TAG prefix
fi
