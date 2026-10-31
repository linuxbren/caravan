#!/bin/zsh
cd ~/.caravan/bench-2026-10-30/runtime-compare
PY=/opt/homebrew/bin/python3
echo "ollama suite start $(date +%T)" >> suite.log
NO_THINK="/no_think" $PY -u ollama_bench.py qwen3-30b-a3b-q4ks rc-qwen3-30b-a3b-q4ks 200 > ollama/qwen.out 2>&1; echo "qwen rc=$? $(date +%T)" >> suite.log
$PY -u ollama_bench.py gemma4-26b-q4_0 rc-gemma4-26b-q4_0 1000 > ollama/gemma.out 2>&1; echo "gemma rc=$? $(date +%T)" >> suite.log
$PY -u ollama_bench.py gpt-oss-20b-mxfp4 rc-gpt-oss-20b-mxfp4 800 > ollama/gptoss.out 2>&1; echo "gptoss rc=$? $(date +%T)" >> suite.log
pkill -f 'ollama-bench/ollama' ; echo "ollama suite done $(date +%T)" >> suite.log
