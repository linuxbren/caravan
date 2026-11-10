#!/usr/bin/env bash
set -e
B="$HOME/day20-speedups/bin"
P="$HOME/day20-speedups/private"
H=huihui-qwen3-5-27b-claude-4-6-opus-abliterated-4bit
Q=qwen3-30b-a3b-4bit
# Never leave a temporary comparison model selected if a later step fails.
trap 'python "$B/control.py" huihui-emergency-restore --model "$H" --counts 24,40' EXIT
# If a single placement was unexpectedly allowed, this next guarded load still
# explicitly chooses the intended split before any split-labelled measurements.
python -u "$B/control.py" qwen-split16 --model "$Q" --counts 24,24
python -u "$B/matrix.py" qwen-split-kv16 --model mlx-community/Qwen3-30B-A3B-4bit
python -u "$B/probe.py" qwen-repeat-lookup-off --payload "$P/repeat.json" --lookup off --session d20-pl-off
python -u "$B/probe.py" qwen-repeat-lookup-adaptive --payload "$P/repeat.json" --lookup adaptive --session d20-pl-on
python -u "$B/probe.py" qwen-agent-lookup-off --payload "$P/qwen-full.json" --lookup off
python -u "$B/probe.py" qwen-agent-lookup-adaptive --payload "$P/qwen-full.json" --lookup adaptive
python -u "$B/control.py" qwen-split8 --model "$Q" --counts 24,24 --kv 8
python -u "$B/matrix.py" qwen-split-kv8 --model mlx-community/Qwen3-30B-A3B-4bit
python -u "$B/control.py" huihui-restore16 --model "$H" --counts 24,40
python -u "$B/probe.py" huihui-reload-on-demand --payload "$P/huihui-split-kv16-hermes-cold.json" --max-tokens 512
python -u "$B/control.py" huihui-reload-for-prewarm --model "$H" --counts 24,40
python -u "$B/probe.py" huihui-prefix-prewarm --payload "$P/prewarm.json" --max-tokens 1
python -u "$B/probe.py" huihui-after-prewarm --payload "$P/huihui-split-kv16-hermes-cold.json" --max-tokens 512
trap - EXIT
