#!/usr/bin/env bash
set -e
B="$HOME/day20-speedups/bin"; P="$HOME/day20-speedups/private"
H=huihui-qwen3-5-27b-claude-4-6-opus-abliterated-4bit
Q=qwen3-30b-a3b-4bit
trap 'python "$B/control.py" huihui-followup-emergency --model "$H" --counts 24,40' EXIT
python -u "$B/control.py" qwen-pl-paired16 --model "$Q" --counts 24,24
# Prime exact short prompt; exclude this cold/restore control from paired data.
python -u "$B/probe.py" qwen-repeat-prime --payload "$P/repeat.json" --lookup off --session d20-pl-paired
for i in 1 2 3; do
 python -u "$B/probe.py" qwen-repeat-paired-off-$i --payload "$P/repeat.json" --lookup off --session d20-pl-paired
 python -u "$B/probe.py" qwen-repeat-paired-on-$i --payload "$P/repeat.json" --lookup adaptive --session d20-pl-paired
done
python -u "$B/control.py" huihui-unseen-on-demand --model "$H" --counts 24,40
python -u "$B/probe.py" prewarm-unseen-baseline --payload "$P/prewarm-unseen-A.json" --max-tokens 1
python -u "$B/control.py" huihui-unseen-for-prewarm --model "$H" --counts 24,40
python -u "$B/probe.py" prewarm-dummy-control --payload "$P/prewarm.json" --max-tokens 1
python -u "$B/probe.py" prewarm-unseen-after --payload "$P/prewarm-unseen-B.json" --max-tokens 1
trap - EXIT
