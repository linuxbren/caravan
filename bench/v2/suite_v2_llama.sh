#!/bin/zsh
# Caravan v2 llama.cpp regression check (2026-10-31): same commands as bench/improvements/suite_imp.sh
# (v1 = s-* speed, r-*-new resume) with CARAVAN_DIR = this v2 checkout. TEST ports 8180/8190 only.
V2=${0:A:h:h:h}   # before the cd: $0 may be relative
cd ~/.caravan/bench-2026-10-30/improvements
# Same GGUF file as v1's s-gptoss / r-gptoss-new (the ~/.caravan/models/gpt-oss-20b.gguf symlink points at an Ollama blob that's gone).
O=${GPT_OSS_GGUF:-$HOME/.cache/huggingface/hub/models--ggml-org--gpt-oss-20b-GGUF/blobs/27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901}
G=~/.caravan/models/gemma-4-26B_q4_0-it.gguf
Q=~/.caravan/models/Qwen3-30B-A3B-Q4_K_S.gguf
PY=/opt/homebrew/bin/python3
NEW=~/dev/llama.cpp/build-rebase/bin
export PYTHONDONTWRITEBYTECODE=1
L=suite-v2l.log
run() { local name=$1; shift; [[ -n $ONLY && $name != *${ONLY}* ]] && return; echo "$name start $(date +%T)" >> $L; "$@" > $name.out 2>&1; echo "$name rc=$? $(date +%T)" >> $L; }
run v2l-s-gptoss env CARAVAN_DIR=$V2 LLAMA_BIN=$NEW KV=auto $PY -u imp_bench.py v2l-s-gptoss $O 800 2048 2 18432 main
run v2l-s-gemma  env CARAVAN_DIR=$V2 LLAMA_BIN=$NEW KV=auto $PY -u imp_bench.py v2l-s-gemma $G 1000 2048 2 18432 main
run v2l-s-qwen   env CARAVAN_DIR=$V2 LLAMA_BIN=$NEW KV=auto NO_THINK=" /no_think" $PY -u imp_bench.py v2l-s-qwen $Q 200 1024 2 8192 main
run v2l-r-gptoss env CARAVAN_DIR=$V2 LLAMA_BIN=$NEW KV=q8_0 TPL=19.295 $PY -u imp_bench.py v2l-r-gptoss $O 800 2048 2 18432 resume
run v2l-r-gemma  env CARAVAN_DIR=$V2 LLAMA_BIN=$NEW KV=q8_0 TPL=24.19 $PY -u imp_bench.py v2l-r-gemma $G 1000 2048 1 18432 resume
run v2l-r-qwen   env CARAVAN_DIR=$V2 LLAMA_BIN=$NEW KV=q8_0 NO_THINK=" /no_think" TPL=23.48 $PY -u imp_bench.py v2l-r-qwen $Q 200 1024 1 18432 resume
echo "suite v2l done $(date +%T)" >> $L
