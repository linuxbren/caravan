#!/bin/bash
# Run on Brenden's Linux box: starts packer on exo2, learn_one on exo1 per tag.
set -euo pipefail
TAGS="${*:-gemma qwen3 llama}"
XFER_SCRIPTS=1
for TAG in $TAGS; do
  echo "==== LEARN $TAG ===="
  # Start packer on exo2
  case "$TAG" in
    llama) MPATH='$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit'; K=16 ;;
    qwen3) MPATH='$HOME/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit'; K=24 ;;
    # exo2 may have gemma under mlx-models (day13 packer script)
    gemma) MPATH='$HOME/.caravan/mlx-models/mlx-community--gemma-4-26b-a4b-it-4bit'; K=15 ;;
  esac
  ssh -o BatchMode=yes exo2 "true 2>/dev/null || true; sleep 2; LPM=\$(pmset -g | awk '/lowpowermode/{print \$2}'); [[ \"\$LPM\" == 0 ]] || { echo REFUSE_LPM_PACKER; exit 2; }; mkdir -p \$HOME/.caravan/bench-2026-11-04/day13-spc-learn; nohup \$HOME/.caravan/venvs/mlx/bin/python \$HOME/cv3/agent/mlx_worker.py --model $MPATH --split-role packer --split-listen 169.254.103.191:5560 --no-split-draft --split-packer-layers $K --no-learn > \$HOME/.caravan/bench-2026-11-04/day13-spc-learn/packer-${TAG}.log 2>&1 & echo \$! > \$HOME/.caravan/bench-2026-11-04/day13-spc-learn/packer.pid; echo packer_pid \$(cat \$HOME/.caravan/bench-2026-11-04/day13-spc-learn/packer.pid)"
  sleep 3
  # Ensure learn_one.sh is on exo1
  ssh -o BatchMode=yes exo1 "bash \$HOME/dev/caravan-v3/handoff/lab/day13-spc-learn/scripts/learn_one.sh $TAG"
  ssh -o BatchMode=yes exo2 "true 2>/dev/null || true"
  ssh -o BatchMode=yes exo1 "true 2>/dev/null || true"
  echo "==== DONE $TAG ===="
done
