#!/bin/bash
set -uo pipefail
set -a; source /tmp/.mini_env; set +a
RC=/workspace/caravan/handoff/tools/rc.py
LOG=/workspace/caravan/handoff/lab/day10-learn-results/suite.log
STATUS=/workspace/caravan/handoff/lab/day10-learn-results/suite-status.json
echo "[]" > "$STATUS"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG"; }
update_status() {
  python3 - "$STATUS" "$1" "$2" <<'PY'
import json,sys,time
path,tag,phase=sys.argv[1],sys.argv[2],sys.argv[3]
try: data=json.load(open(path))
except Exception: data=[]
data.append({"tag":tag,"phase":phase,"ts":time.strftime("%Y-%m-%dT%H:%M:%S"), "zone":"America/Chicago"})
json.dump(data, open(path,"w"), indent=2)
PY
}

run_model() {
  local TAG="$1"
  local DO_TRAP="$2"
  log "======== START $TAG trap=$DO_TRAP ========"
  update_status "$TAG" "packer_start"
  python3 "$RC" 2 run "bash ~/cv3/handoff/lab/start_packer_day10.sh $TAG; sleep 4; tail -15 ~/.caravan/bench-2026-11-02/day10-learn/packer-$TAG.log; lsof -iTCP:5560 -sTCP:LISTEN | head" >>"$LOG" 2>&1
  local prc=$?
  log "packer_start rc=$prc"
  if [[ $prc -ne 0 ]]; then
    update_status "$TAG" "packer_FAIL"
    log "SKIP rest of $TAG"
    return 1
  fi

  update_status "$TAG" "race_start"
  python3 "$RC" 1 run "pkill -9 -f day10_learn || true; ~/.caravan/venvs/mlx/bin/python ~/dev/caravan-v3/handoff/lab/day10_learn_driver.py race $TAG" >>"$LOG" 2>&1
  local rrc=$?
  log "race rc=$rrc"
  update_status "$TAG" "race_rc_$rrc"
  # pull race result
  python3 "$RC" 1 get "/Users/brenden/.caravan/bench-2026-11-02/day10-learn/${TAG}-race/result.json" \
    "/workspace/caravan/handoff/lab/day10-learn-results/${TAG}-race.json" >>"$LOG" 2>&1 || log "race get fail"

  # ensure packer still up before quality
  python3 "$RC" 2 run "lsof -iTCP:5560 -sTCP:LISTEN | head || bash ~/cv3/handoff/lab/start_packer_day10.sh $TAG; sleep 3; lsof -iTCP:5560 -sTCP:LISTEN | head" >>"$LOG" 2>&1

  update_status "$TAG" "quality_start"
  python3 "$RC" 1 run "~/.caravan/venvs/mlx/bin/python ~/dev/caravan-v3/handoff/lab/day10_learn_driver.py quality $TAG" >>"$LOG" 2>&1
  local qrc=$?
  log "quality rc=$qrc"
  update_status "$TAG" "quality_rc_$qrc"
  python3 "$RC" 1 get "/Users/brenden/.caravan/bench-2026-11-02/day10-learn/${TAG}-quality/result.json" \
    "/workspace/caravan/handoff/lab/day10-learn-results/${TAG}-quality.json" >>"$LOG" 2>&1 || log "quality get fail"

  if [[ "$DO_TRAP" == "1" ]]; then
    python3 "$RC" 2 run "lsof -iTCP:5560 -sTCP:LISTEN | head || bash ~/cv3/handoff/lab/start_packer_day10.sh $TAG; sleep 3; lsof -iTCP:5560 -sTCP:LISTEN | head" >>"$LOG" 2>&1
    update_status "$TAG" "trap_start"
    python3 "$RC" 1 run "~/.caravan/venvs/mlx/bin/python ~/dev/caravan-v3/handoff/lab/day10_learn_driver.py trap $TAG" >>"$LOG" 2>&1
    local trc=$?
    log "trap rc=$trc"
    update_status "$TAG" "trap_rc_$trc"
    python3 "$RC" 1 get "/Users/brenden/.caravan/bench-2026-11-02/day10-learn/${TAG}-trap/result.json" \
      "/workspace/caravan/handoff/lab/day10-learn-results/${TAG}-trap.json" >>"$LOG" 2>&1 || log "trap get fail"
  fi

  # stop workers for this model before next
  python3 "$RC" 1 run "true || true; pkill -9 -f day10_learn || true" >>"$LOG" 2>&1
  python3 "$RC" 2 run "true || true" >>"$LOG" 2>&1
  log "======== DONE $TAG ========"
  update_status "$TAG" "done"
}

# denser 14B first (faster), then gptoss, gemma, qwen3
run_model qwen25 1
run_model distill 1
run_model gptoss 1
run_model gemma 1
run_model qwen3 1

log "ALL_MODELS_DONE"
update_status "ALL" "done"
