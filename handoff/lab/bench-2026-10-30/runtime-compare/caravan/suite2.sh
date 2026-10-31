#!/bin/zsh
cd ~/.caravan/bench-2026-10-30/runtime-compare/caravan
O=~/.cache/huggingface/hub/models--ggml-org--gpt-oss-20b-GGUF/blobs/27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901
G=~/.caravan/models/gemma-4-26B_q4_0-it.gguf
Q=~/.caravan/models/Qwen3-30B-A3B-Q4_K_S.gguf
PY=/opt/homebrew/bin/python3
export PYTHONDONTWRITEBYTECODE=1
echo "suite2 start $(date +%T)" >> suite.log
NO_THINK=" /no_think" $PY -u caravan_bench.py qwen3-30b-a3b-q4ks-2x12k $Q 200 1024 2 12288 main,quality > qwen-a.out 2>&1; echo "qwen-2x12k rc=$? $(date +%T)" >> suite.log
NO_THINK=" /no_think" TPL=23.48 $PY -u caravan_bench.py qwen3-30b-a3b-q4ks-1x18k $Q 200 1024 1 18432 d16k,resume,resume_raw > qwen-b.out 2>&1; echo "qwen-1x18k rc=$? $(date +%T)" >> suite.log
TPL=19.295 $PY -u caravan_bench.py gpt-oss-20b-mxfp4-raw $O 800 2048 2 18432 resume_raw > gptoss-raw.out 2>&1; echo "gptoss-raw rc=$? $(date +%T)" >> suite.log
TPL=24.19 $PY -u caravan_bench.py gemma4-26b-q4_0-raw $G 1000 2048 2 18432 resume_raw > gemma-raw.out 2>&1; echo "gemma-raw rc=$? $(date +%T)" >> suite.log
echo "suite2 done $(date +%T)" >> suite.log
