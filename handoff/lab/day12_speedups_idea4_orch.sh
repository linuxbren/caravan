#!/bin/bash
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
    if ssh exo2 "grep -qE 'listening|packer ready|split packer' \$HOME/.caravan/bench-2026-11-03/day12-speedups/packer-${TAG}.log 2>/dev/null"; then break; fi
    sleep 1
  done
  for N in 2048 4096; do
    for FLAG in off on; do
      echo "==== idea4 $TAG n=$N $FLAG $(date) ===="
      ssh exo1 "bash \$HOME/dev/caravan-v3/handoff/lab/day12_speedups_idea4_driver.sh $TAG $N $FLAG"
    done
  done
  ssh exo2 'pkill -9 -f mlx_worker.py 2>/dev/null || true'
  sleep 2
done
echo ALL_DONE_IDEA4 $(date)
