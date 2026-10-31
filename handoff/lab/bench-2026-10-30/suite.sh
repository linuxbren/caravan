#!/bin/zsh
cd ~/.caravan/bench-2026-10-30
G=~/.caravan/models/gemma-4-26B_q4_0-it.gguf
O=~/.cache/huggingface/hub/models--ggml-org--gpt-oss-20b-GGUF/blobs/27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901
echo "suite start $(date +%T)" > suite.log
./bench.sh gemma4-26b-q4_0 $G > gemma-bench.out 2>&1; echo "gemma bench rc=$? $(date +%T)" >> suite.log
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3 -u smoke.py gemma4-26b-q4_0 $G 300 > gemma-smoke.out 2>&1; echo "gemma smoke rc=$? $(date +%T)" >> suite.log
./bench.sh gpt-oss-20b-mxfp4 $O > gptoss-bench.out 2>&1; echo "gptoss bench rc=$? $(date +%T)" >> suite.log
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3 -u smoke.py gpt-oss-20b-mxfp4 $O 800 > gptoss-smoke.out 2>&1; echo "gptoss smoke rc=$? $(date +%T)" >> suite.log
echo "suite done $(date +%T)" >> suite.log
