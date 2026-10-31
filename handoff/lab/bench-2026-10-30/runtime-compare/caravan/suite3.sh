#!/bin/zsh
cd ~/.caravan/bench-2026-10-30/runtime-compare/caravan
while pgrep -f suite2.sh >/dev/null; do sleep 3; done
export PYTHONDONTWRITEBYTECODE=1
Q=~/.caravan/models/Qwen3-30B-A3B-Q4_K_S.gguf
NO_THINK=" /no_think" /opt/homebrew/bin/python3 -u caravan_bench.py qwen3-30b-a3b-q4ks-2x8k $Q 200 1024 2 8192 main,quality > qwen-c.out 2>&1; echo "qwen-2x8k rc=$? $(date +%T)" >> suite.log
