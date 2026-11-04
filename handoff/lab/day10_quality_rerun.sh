#!/bin/bash
set -uo pipefail
set -a; source /tmp/.mini_env; set +a
RC=/workspace/caravan/handoff/tools/rc.py
LOG=/workspace/caravan/handoff/lab/day10-learn-results/quality-rerun.log
log(){ echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG"; }
run_quality(){
  local TAG="$1"
  log "======== QUALITY $TAG ========"
  python3 "$RC" 2 run "bash ~/cv3/handoff/lab/start_packer_day10.sh $TAG; sleep 3; lsof -iTCP:5560 -sTCP:LISTEN | head" >>"$LOG" 2>&1
  # Run driver with output tee'd via remote so we don't lose progress if SOCKS drops mid-stream
  python3 "$RC" 1 run "~/.caravan/venvs/mlx/bin/python ~/dev/caravan-v3/handoff/lab/day10_learn_driver.py quality $TAG > ~/.caravan/bench-2026-11-02/day10-learn/${TAG}-quality-driver.log 2>&1; echo DRIVER_RC=\$?" >>"$LOG" 2>&1
  local rc=$?
  log "quality $TAG orch_rc=$rc"
  python3 "$RC" 1 get "/Users/brenden/.caravan/bench-2026-11-02/day10-learn/${TAG}-quality/result.json" \
    "/workspace/caravan/handoff/lab/day10-learn-results/${TAG}-quality.json" >>"$LOG" 2>&1 || log "get fail $TAG"
  python3 "$RC" 1 run "tail -20 ~/.caravan/bench-2026-11-02/day10-learn/${TAG}-quality-driver.log; python3 -c \"import json;d=json.load(open('/Users/brenden/.caravan/bench-2026-11-02/day10-learn/${TAG}-quality/result.json')); print('SCORE',d.get('passed'),'/',d.get('total'),'mt',d.get('max_tokens'))\"" >>"$LOG" 2>&1
  python3 "$RC" 1 run "pkill -9 -f mlx_worker || true; pkill -9 -f day10_learn || true" >>"$LOG" 2>&1
  python3 "$RC" 2 run "pkill -9 -f mlx_worker || true" >>"$LOG" 2>&1
  log "======== DONE $TAG ========"
}
: > "$LOG"
for TAG in llama qwen25 qwen3 gemma gptoss distill; do
  run_quality "$TAG"
done
log ALL_QUALITY_DONE
