#!/bin/zsh
# 2026-10-30 improvements suite (EXO1). Test ports only: llama 8180, proxy 8190, mlx 8192.
cd ~/.caravan/bench-2026-10-30/improvements
O=${GPT_OSS_GGUF:-$HOME/.caravan/models/gpt-oss-20b.gguf}
G=~/.caravan/models/gemma-4-26B_q4_0-it.gguf
Q=~/.caravan/models/Qwen3-30B-A3B-Q4_K_S.gguf
PY=/opt/homebrew/bin/python3
OLD=~/dev/llama.cpp/build/bin; NEW=~/dev/llama.cpp/build-rebase/bin
V0=~/dev/caravan; IMP=~/dev/caravan-improvements
export PYTHONDONTWRITEBYTECODE=1
L=suite.log
run() { local name=$1; shift; echo "$name start $(date +%T)" >> $L; "$@" > $name.out 2>&1; echo "$name rc=$? $(date +%T)" >> $L; }
STAGE=${1:-all}
if [[ $STAGE == all || $STAGE == resume ]]; then
# --- 1. SWA resume: old build / rebased build / old build + --swa-full (all q8_0 KV, v0-style settings)
run r-gptoss-old    env CARAVAN_DIR=$V0  LLAMA_BIN=$OLD KV=q8_0 TPL=19.295 $PY -u imp_bench.py r-gptoss-old $O 800 2048 2 18432 resume,resume_raw
run r-gptoss-new    env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=q8_0 TPL=19.295 $PY -u imp_bench.py r-gptoss-new $O 800 2048 2 18432 resume,resume_raw
run r-gptoss-swafull env CARAVAN_DIR=$V0 LLAMA_BIN=$OLD KV=q8_0 SWA_FULL=1 TPL=19.295 $PY -u imp_bench.py r-gptoss-swafull $O 800 2048 2 18432 resume,resume_raw
run r-gemma-old     env CARAVAN_DIR=$V0  LLAMA_BIN=$OLD KV=q8_0 TPL=24.19 $PY -u imp_bench.py r-gemma-old $G 1000 2048 1 18432 resume,resume_raw
run r-gemma-new     env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=q8_0 TPL=24.19 $PY -u imp_bench.py r-gemma-new $G 1000 2048 1 18432 resume,resume_raw
run r-gemma-swafull env CARAVAN_DIR=$V0  LLAMA_BIN=$OLD KV=q8_0 SWA_FULL=1 TPL=24.19 $PY -u imp_bench.py r-gemma-swafull $G 1000 2048 1 18432 resume,resume_raw
# non-SWA regression check
run r-qwen-new      env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=q8_0 NO_THINK=" /no_think" TPL=23.48 $PY -u imp_bench.py r-qwen-new $Q 200 1024 1 18432 resume,resume_raw
fi
if [[ $STAGE == all || $STAGE == speed ]]; then
# --- 2. improved Caravan (rebased build + auto KV) standard metrics, same settings as v0
run s-gptoss  env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=auto $PY -u imp_bench.py s-gptoss $O 800 2048 2 18432 main,quality,d16k
run s-gemma   env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=auto $PY -u imp_bench.py s-gemma $G 1000 2048 2 18432 main,quality,d16k
run s-qwen    env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=auto NO_THINK=" /no_think" $PY -u imp_bench.py s-qwen $Q 200 1024 2 8192 main,quality
run s-qwen-16k env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=auto NO_THINK=" /no_think" TPL=23.48 $PY -u imp_bench.py s-qwen-16k $Q 200 1024 1 18432 d16k
fi
if [[ $STAGE == all || $STAGE == mlx ]]; then
# --- 3. MLX through the proxy
run m-gptoss env CARAVAN_DIR=$IMP $PY -u mlx_bench.py m-gptoss mlx-community/gpt-oss-20b-MXFP4-Q8 800
run m-gemma  env CARAVAN_DIR=$IMP $PY -u mlx_bench.py m-gemma mlx-community/gemma-4-26b-a4b-it-4bit 1000
run m-qwen   env CARAVAN_DIR=$IMP NO_THINK=" /no_think" $PY -u mlx_bench.py m-qwen mlx-community/Qwen3-30B-A3B-4bit 200
fi
if [[ $STAGE == extra || $STAGE == next ]]; then
# --- 4. attribution: rebased build with q8_0 (isolates the rebase from f16), and a same-session v0 rerun (drift check)
run x-gptoss-newq8 env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=q8_0 $PY -u imp_bench.py x-gptoss-newq8 $O 800 2048 2 18432 main,d16k
run x-gemma-newq8  env CARAVAN_DIR=$IMP LLAMA_BIN=$NEW KV=q8_0 $PY -u imp_bench.py x-gemma-newq8 $G 1000 2048 2 18432 main,d16k
run x-gptoss-v0    env CARAVAN_DIR=$V0 LLAMA_BIN=$OLD KV=q8_0 $PY -u imp_bench.py x-gptoss-v0 $O 800 2048 2 18432 main,d16k
run x-gemma-v0     env CARAVAN_DIR=$V0 LLAMA_BIN=$OLD KV=q8_0 $PY -u imp_bench.py x-gemma-v0 $G 1000 2048 2 18432 main,d16k
run x-qwen-v0      env CARAVAN_DIR=$V0 LLAMA_BIN=$OLD KV=q8_0 NO_THINK=" /no_think" $PY -u imp_bench.py x-qwen-v0 $Q 200 1024 2 8192 main
run x-qwen-16k-v0  env CARAVAN_DIR=$V0 LLAMA_BIN=$OLD KV=q8_0 NO_THINK=" /no_think" TPL=23.48 $PY -u imp_bench.py x-qwen-16k-v0 $Q 200 1024 1 18432 d16k
fi
if [[ $STAGE == mlxgptoss || $STAGE == next ]]; then
run m-gptoss2 env CARAVAN_DIR=$IMP $PY -u mlx_bench.py m-gptoss2 mlx-community/gpt-oss-20b-MXFP4-Q8 800
# Qwen 4-bit (16 GiB weights) OOMed with mlx_lm's default prompt cache (10 sequences kept on GPU): cap it
run m-qwen2 env CARAVAN_DIR=$IMP NO_THINK=" /no_think" CARAVAN_MLX_EXTRA_ARGS="--prompt-cache-size 2 --prompt-cache-bytes 1073741824" $PY -u mlx_bench.py m-qwen2 mlx-community/Qwen3-30B-A3B-4bit 200
fi
echo "suite $STAGE done $(date +%T)" >> $L
