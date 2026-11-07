#!/bin/bash
set -uo pipefail
set -a; source /tmp/.mini_env; set +a
RC=/workspace/caravan/handoff/tools/rc.py
LOG=/workspace/caravan/handoff/lab/day12-fused/spanned/suite.log
STATUS=/workspace/caravan/handoff/lab/day12-fused/spanned/suite-status.json
OUTDIR=/workspace/caravan/handoff/lab/day12-fused/spanned
mkdir -p "$OUTDIR"
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
remote_rc() {
  # parse last [rc=N] from a log snippet file
  python3 - "$1" <<'PY'
import re,sys
t=open(sys.argv[1]).read()
ms=re.findall(r"\[rc=(\d+)\]", t)
print(ms[-1] if ms else "missing")
PY
}
stop_all() {
  python3 "$RC" 1 run "true || true" >/dev/null 2>&1 || true
  python3 "$RC" 2 run "true || true" >/dev/null 2>&1 || true
  sleep 3
}
pull_dir() {
  local TAG="$1" MODE="$2" PIPE="$3"
  local rem="/Users/brenden/.caravan/bench-2026-11-03/day12-fused/spanned/${TAG}-${MODE}-n${PIPE}"
  local loc="$OUTDIR/${TAG}-${MODE}-n${PIPE}"
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
  local tmp="$OUTDIR/_last_run.txt"
  log "======== START $key ========"
  update_status "$key" "packer_start"
  stop_all
  : > "$tmp"
  python3 "$RC" 2 run "bash ~/cv3/handoff/lab/start_packer_day12_fuse.sh $TAG $MODE; sleep 6; tail -30 ~/.caravan/bench-2026-11-03/day12-fused/spanned/packer-${TAG}-${MODE}.log; lsof -iTCP:5560 -sTCP:LISTEN | grep LISTEN | head" | tee -a "$LOG" | tee "$tmp" >/dev/null
  local prc; prc=$(remote_rc "$tmp")
  log "packer_start remote_rc=$prc"
  if [[ "$prc" != "0" ]]; then update_status "$key" "packer_FAIL_$prc"; return 1; fi
  if ! grep -q "listening on 169.254" "$tmp"; then
    log "packer did not log listening"; update_status "$key" "packer_NO_LISTEN"; return 1
  fi
  update_status "$key" "lead_bench_start"
  : > "$tmp"
  python3 "$RC" 1 run "bash ~/dev/caravan-v3/handoff/lab/day12_fuse_spanned_driver.sh $TAG $MODE $PIPE" | tee -a "$LOG" | tee "$tmp" >/dev/null
  local lrc; lrc=$(remote_rc "$tmp")
  log "lead_bench remote_rc=$lrc"
  update_status "$key" "lead_bench_rc_$lrc"
  pull_dir "$TAG" "$MODE" "$PIPE"
  # require jsonl rows for success
  local loc="$OUTDIR/${TAG}-${MODE}-n${PIPE}"
  local rows=0
  if [[ "$PIPE" == "1" ]]; then
    rows=$(wc -l < "$loc/single.jsonl" 2>/dev/null || echo 0)
  else
    rows=$(wc -l < "$loc/pipe-N2.jsonl" 2>/dev/null || echo 0)
  fi
  stop_all
  if [[ "$lrc" != "0" || "$rows" -lt 3 ]]; then
    log "FAIL $key remote_rc=$lrc rows=$rows"
    update_status "$key" "FAIL"
    return 1
  fi
  log "======== DONE $key rows=$rows ========"
  update_status "$key" "done"
  return 0
}

# Ensure packer script with K is on Minis
python3 "$RC" 1 put /workspace/caravan/handoff/lab/start_packer_day12_fuse.sh /Users/brenden/dev/caravan-v3/handoff/lab/start_packer_day12_fuse.sh
python3 "$RC" 2 put /workspace/caravan/handoff/lab/start_packer_day12_fuse.sh /Users/brenden/cv3/handoff/lab/start_packer_day12_fuse.sh
python3 "$RC" 2 run 'chmod +x ~/cv3/handoff/lab/start_packer_day12_fuse.sh'

# Gemma: metal-swiglu only (all/force-fused crashes on head dim 512)
for PIPE in 1 2; do
  run_one gemma metal-swiglu "$PIPE" || log "recorded FAIL gemma metal-swiglu n$PIPE"
done

# Qwen3: off vs all
for MODE in off all; do
  for PIPE in 1 2; do
    run_one qwen3 "$MODE" "$PIPE" || log "recorded FAIL qwen3 $MODE n$PIPE"
  done
done

log "ALL_SPANNED_DONE"
update_status "ALL" "done"
