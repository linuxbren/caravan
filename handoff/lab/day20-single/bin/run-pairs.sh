#!/usr/bin/env bash
set -e
B="$HOME/day20-single/bin"
H=huihui-qwen3-5-27b-claude-4-6-opus-abliterated-4bit
trap 'python "$B/control.py" final-huihui-emergency --model "$H" --counts 24,40' EXIT
# Complete Huihui is already loaded single by the normal guarded API.
python -u "$B/matrix.py" huihui-single --model mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit || echo 'Huihui matrix includes an admission/stream failure; inspect saved raw data'
python -u "$B/control.py" astrea-single --model astrea-r8-chat-9b-optiq-4bit --single
python -u "$B/matrix.py" astrea-single --model mlx-community/Astrea-R8-Chat-9B-OptiQ-4bit
python -u "$B/control.py" astrea-split --model astrea-r8-chat-9b-optiq-4bit --counts 16,16
python -u "$B/matrix.py" astrea-split --model mlx-community/Astrea-R8-Chat-9B-OptiQ-4bit
python -u "$B/control.py" orvena-single --model orvena-4b-mlx-4bit --single
python -u "$B/matrix.py" orvena-single --model Orvena/Orvena-4B-MLX-4bit
python -u "$B/control.py" orvena-split --model orvena-4b-mlx-4bit --counts 16,16
python -u "$B/matrix.py" orvena-split --model Orvena/Orvena-4B-MLX-4bit
python -u "$B/control.py" final-huihui-24-40 --model "$H" --counts 24,40
trap - EXIT
