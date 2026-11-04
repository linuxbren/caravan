#!/bin/bash
# Orchestrate Idea 1 across models. Run from Brenden's computer (ssh exo1/exo2).
# Usage: day12_speedups_idea1_orch.sh [llama|qwen3|gemma|all]
set -euo pipefail
SCOPE=${1:-all}
TAGS=()
case "$SCOPE" in
  all) TAGS=(llama gemma qwen3) ;;
  llama|gemma|qwen3) TAGS=("$SCOPE") ;;
  *) echo "bad scope"; exit 1 ;;
esac

for TAG in "${TAGS[@]}"; do
  echo "==== packer $TAG $(date) ===="
  ssh exo2 "bash \$HOME/cv3/handoff/lab/start_packer_day12_speedups.sh $TAG"
  for i in $(seq 1 240); do
    if ssh exo2 "grep -qE 'listening|packer ready|split packer' \$HOME/.caravan/bench-2026-11-03/day12-speedups/packer-${TAG}.log 2>/dev/null"; then
      break
    fi
    sleep 1
  done
  ssh exo2 "tail -30 \$HOME/.caravan/bench-2026-11-03/day12-speedups/packer-${TAG}.log" || true

  for PIPE in 1 2; do
    for DRAFT in off on; do
      echo "==== lead $TAG n=$PIPE draft=$DRAFT $(date) ===="
      ssh exo1 "bash \$HOME/dev/caravan-v3/handoff/lab/day12_speedups_idea1_driver.sh $TAG $PIPE $DRAFT"
    done
  done

  ssh exo2 'pkill -9 -f mlx_worker.py 2>/dev/null || true'
  sleep 2
done
echo ALL_DONE_IDEA1 $(date)
