#!/usr/bin/env bash
set -e
B="$HOME/day20-single/bin"
H=huihui-qwen3-5-27b-claude-4-6-opus-abliterated-4bit
restore(){ python "$B/stop.py" final-stop; python "$B/control.py" final-huihui-24-40 --model "$H" --counts 24,40; }
trap restore EXIT
python -u "$B/stop.py" before-orvena-split
python -u "$B/control.py" orvena-split --model orvena-4b-mlx-4bit --counts 16,16
python -u "$B/matrix.py" orvena-split --model Orvena/Orvena-4B-MLX-4bit --max-tokens 1024
python -u "$B/stop.py" before-astrea-single-none
python -u "$B/control.py" astrea-single-none --model astrea-r8-chat-9b-optiq-4bit --single
python -u "$B/matrix.py" astrea-single-none --model mlx-community/Astrea-R8-Chat-9B-OptiQ-4bit --routes direct --thinking none
python -u "$B/stop.py" before-astrea-split-none
python -u "$B/control.py" astrea-split-none --model astrea-r8-chat-9b-optiq-4bit --counts 16,16
python -u "$B/matrix.py" astrea-split-none --model mlx-community/Astrea-R8-Chat-9B-OptiQ-4bit --routes direct --thinking none
restore
trap - EXIT
python -u "$B/probe.py" final-full-power --payload "$HOME/day20-single/private/final-full-power.json"
