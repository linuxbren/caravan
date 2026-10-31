#!/bin/zsh
cd ~/.caravan/bench-2026-10-30/runtime-compare/localai
PY=/opt/homebrew/bin/python3
NO_THINK=" /no_think" $PY -u localai_bench.py qwen qwen 200 > suite-qwen.out 2>&1
$PY -u localai_bench.py gemma gemma 1000 > suite-gemma.out 2>&1
$PY -u localai_bench.py gptoss gptoss 800 > suite-gptoss.out 2>&1
echo SUITE_DONE > suite.done
