#!/bin/bash
# Orchestrate Day 12 spanned fuse A/B from the box via rc.py.
set -uo pipefail
set -a; source /tmp/.mini_env; set +a
RC=/workspace/caravan/handoff/tools/rc.py
LOG=/workspace/caravan/handoff/lab/day12-fused/spanned/suite.log
STATUS=/workspace/caravan/handoff/lab/day12-fused/spanned/suite-status.json
mkdir -p /workspace/caravan/handoff/lab/day12-fused/spanned
echo "[]" > "$STATUS"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG"; }
update_status() {
  python3 - "$STATUS" "$1" "$2" <<'PY'
import json,sys,time
path,tag,phase=sys.argv[1],sys.argv[2],sys.argv[3]
try: data=json.load(open(path))
except Exception: data=[]
data.append({"tag":tag,"phase":phase,"ts":time.strftime("%Y-%m-%dT%H:%M:%S"),"zone":"America/Chicago"})
json.dump(data, open(path,"w"), indent=2)
PY
}

sync_scripts() {
  log "sync scripts to Minis"
  for f in day12_fuse_light_bench.py day12_fuse_spanned_driver.sh start_packer_day12_fuse.sh; do
    python3 "$RC" 1 put "/workspace/caravan/handoff/lab/$f" "/Users/brenden/dev/caravan-v3/handoff/lab/$f" || log "put exo1 $f fail"
    python3 "$RC" 2 put "/workspace/caravan/handoff/lab/$f" "/Users/brenden/cv3/handoff/lab/$f" || log "put exo2 $f fail"
  done
  python3 "$RC" 1 run 'chmod +x ~/dev/caravan-v3/handoff/lab/day12_fuse_spanned_driver.sh ~/dev/caravan-v3/handoff/lab/start_packer_day12_fuse.sh' || true
  python3 "$RC" 2 run 'chmod +x ~/cv3/handoff/lab/day12_fuse_spanned_driver.sh ~/cv3/handoff/lab/start_packer_day12_fuse.sh' || true
}

stop_all() {
  python3 "$RC" 1 run "true || true; sleep 1; true || true" >/dev/null 2>&1 || true
  python3 "$RC" 2 run "true || true; sleep 1; true || true" >/dev/null 2>&1 || true
  sleep 2
}

pull_dir() {
  local TAG="$1" MODE="$2" PIPE="$3"
  local rem="/Users/brenden/.caravan/bench-2026-11-03/day12-fused/spanned/${TAG}-${MODE}-n${PIPE}"
  local loc="/workspace/caravan/handoff/lab/day12-fused/spanned/${TAG}-${MODE}-n${PIPE}"
  mkdir -p "$loc"
  for f in single.out single.jsonl startup.txt lead-peaks.txt pipe-N2.out pipe-N2.jsonl lead.log; do
    python3 "$RC" 1 get "$rem/$f" "$loc/$f" >/dev/null 2>&1 || true
  done
  python3 "$RC" 2 get "/Users/brenden/.caravan/bench-2026-11-03/day12-fused/spanned/packer-${TAG}-${MODE}.log" \
    "$loc/packer.log" >/dev/null 2>&1 || true
}

run_one() {
  local TAG="$1" MODE="$2" PIPE="$3"
  local key="${TAG}-${MODE}-n${PIPE}"
  log "======== START $key ========"
  update_status "$key" "packer_start"
  stop_all
  python3 "$RC" 2 run "bash ~/cv3/handoff/lab/start_packer_day12_fuse.sh $TAG $MODE; sleep 5; tail -20 ~/.caravan/bench-2026-11-03/day12-fused/spanned/packer-${TAG}-${MODE}.log; lsof -iTCP:5560 -sTCP:LISTEN | head" >>"$LOG" 2>&1
  local prc=$?
  log "packer_start rc=$prc"
  if [[ $prc -ne 0 ]]; then
    update_status "$key" "packer_FAIL"
    return 1
  fi
  # wait until packer is listening (match LISTEN anywhere; head -1 was the column header)
  for i in $(seq 1 30); do
    python3 "$RC" 2 run 'lsof -iTCP:5560 -sTCP:LISTEN | grep LISTEN | head -2' 2>/dev/null | grep -q LISTEN && break
    sleep 1
  done

  update_status "$key" "lead_bench_start"
  python3 "$RC" 1 run "bash ~/dev/caravan-v3/handoff/lab/day12_fuse_spanned_driver.sh $TAG $MODE $PIPE" >>"$LOG" 2>&1
  local lrc=$?
  log "lead_bench rc=$lrc"
  update_status "$key" "lead_bench_rc_$lrc"
  pull_dir "$TAG" "$MODE" "$PIPE"

  stop_all
  log "======== DONE $key ========"
  update_status "$key" "done"
  return $lrc
}

sync_scripts

# Primary matrix: off vs all, N=1 and N=2, three models (llama quick first)
for MODE in off all; do
  for PIPE in 1 2; do
    run_one llama "$MODE" "$PIPE" || log "FAIL llama $MODE n$PIPE"
  done
done
for MODE in off all; do
  for PIPE in 1 2; do
    run_one gemma "$MODE" "$PIPE" || log "FAIL gemma $MODE n$PIPE"
  done
done
for MODE in off all; do
  for PIPE in 1 2; do
    run_one qwen3 "$MODE" "$PIPE" || log "FAIL qwen3 $MODE n$PIPE"
  done
done

# Pull suite.log from EXO1
python3 "$RC" 1 get "/Users/brenden/.caravan/bench-2026-11-03/day12-fused/spanned/suite.log" \
  "/workspace/caravan/handoff/lab/day12-fused/spanned/exo1-suite.log" >/dev/null 2>&1 || true

log "ALL_SPANNED_DONE"
update_status "ALL" "done"
