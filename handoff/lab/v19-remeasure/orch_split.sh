#!/bin/bash
set -uo pipefail
for TAG in qwen3 gemma gptoss; do
  echo "== packer $TAG $(date +%T)"
  ssh exo2 "bash \$HOME/cv3/handoff/lab/start_packer_day12_speedups.sh $TAG"
  for i in $(seq 1 240); do ssh exo2 "grep -qE 'listening|packer ready|split packer' \$HOME/.caravan/bench-2026-11-03/day12-speedups/packer-${TAG}.log" && break; sleep 1; done
  ssh exo1 "bash ~/.caravan/bench-2026-11-04/v19/scripts/lead_split.sh $TAG bench off"
  if [[ $TAG == qwen3 ]]; then
    for F in off on; do
      ssh exo2 "bash \$HOME/cv3/handoff/lab/start_packer_day12_speedups.sh $TAG" >/dev/null
      for i in $(seq 1 240); do ssh exo2 "grep -qE 'listening|packer ready|split packer' \$HOME/.caravan/bench-2026-11-03/day12-speedups/packer-${TAG}.log" && break; sleep 1; done
      ssh exo1 "bash ~/.caravan/bench-2026-11-04/v19/scripts/lead_split.sh $TAG prefix $F"
    done
  fi
  ssh exo2 'true 2>/dev/null || true'; sleep 2
done
echo ALL_SPLIT_DONE $(date +%T)
