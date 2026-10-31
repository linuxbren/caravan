#!/bin/zsh
cd ~/.caravan/bench-2026-10-30/runtime-compare/caravan
O=~/.cache/huggingface/hub/models--ggml-org--gpt-oss-20b-GGUF/blobs/27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901
G=~/.caravan/models/gemma-4-26B_q4_0-it.gguf
Q=~/.caravan/models/Qwen3-30B-A3B-Q4_K_S.gguf
PY=(/opt/homebrew/bin/python3 -u)
export PYTHONDONTWRITEBYTECODE=1
echo "suite start $(date +%T)" >> suite.log
${PY[@]} caravan_bench.py gpt-oss-20b-mxfp4 $O 800 2048 2 18432 > gptoss.out 2>&1; echo "gptoss rc=$? $(date +%T)" >> suite.log
${PY[@]} caravan_bench.py gemma4-26b-q4_0 $G 1000 2048 2 18432 > gemma.out 2>&1; echo "gemma rc=$? $(date +%T)" >> suite.log
NO_THINK=" /no_think" ${PY[@]} caravan_bench.py qwen3-30b-a3b-q4ks $Q 200 1024 2 18432 main,quality,d16k,resume,resume_raw > qwen.out 2>&1; echo "qwen rc=$? $(date +%T)" >> suite.log
echo "suite done $(date +%T)" >> suite.log
