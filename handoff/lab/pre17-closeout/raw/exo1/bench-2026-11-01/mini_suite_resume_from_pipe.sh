#!/bin/bash
set -euo pipefail
: "${SUITE_NAME:?}" "${MODEL_DIR:?}" "${MODEL_NAME:?}" "${PAIRING_ID:?}" "${K:?}" "${DRAFT_NAME:?}"
R=$HOME/.caravan/bench-2026-11-01/$SUITE_NAME
M=$MODEL_DIR
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
URL=http://127.0.0.1:8194
PEER=169.254.104.38:5560
mkdir -p "$R"; cd "$CV"
echo "=== RESUME_FROM_PIPE $SUITE_NAME $(date) ==="
kill_lead() {
  pkill -9 -f 'mlx_worker.py --split-role lead' 2>/dev/null || true
  sleep 3
  pkill -9 -f 'mlx_worker.py --split-role lead' 2>/dev/null || true
  sleep 2
}
start_lead() {
  kill_lead
  local log=$1; shift
  : > "$log"
  nohup $PY agent/mlx_worker.py --model "$M" --split-role lead --split-peer "$PEER" \
    --split-packer-layers "$K" --host 127.0.0.1 --port 8194 "$@" > "$log" 2>&1 &
  echo $! > "${log}.pid"
  for i in $(seq 1 240); do
    if grep -q 'listening on http' "$log" 2>/dev/null; then echo "LEAD_UP $log"; return 0; fi
    sleep 1
  done
  echo "LEAD_FAIL $log"; tail -50 "$log"; return 1
}
wait_health() { for i in $(seq 1 90); do curl -sf "$URL/health" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

echo "=== pipeline N=1/2/3 ==="
start_lead "$R/lead-pipe.log" --no-split-draft --split-draft-skip-first-load --split-pipeline-chats 3
wait_health
for N in 1 2 3; do
  echo "--- pipeline N=$N ---"
  $PY bench/v3/pipeline_bench.py "$URL" "$MODEL_NAME" "$R/pipe-N$N.json" "$N" | tee "$R/pipe-N$N.out"
done
kill_lead

echo "=== nodraft suite ==="
start_lead "$R/lead-nodraft.log" --no-split-draft --split-draft-skip-first-load
wait_health
$PY bench/v3/speculate_bench.py "$URL" "$MODEL_NAME" "$R/ga-nodraft-suite.json" nodraft suite | tee "$R/ga-nodraft-suite.out"
kill_lead

echo "=== autopair + first-load gate ==="
PAIRING_ID="$PAIRING_ID" python3 - <<'PY'
import json, os
from pathlib import Path
pid=os.environ["PAIRING_ID"]
p=Path.home()/".caravan/mlx/guess-ahead-state.json"
s=json.loads(p.read_text()) if p.exists() else {}
fl=s.get("first_load") or {}
for k,v in list(fl.items()):
  if (v or {}).get("pairing")==pid or "Qwen2.5" in k or "Distill" in k or "DeepSeek-R1" in k or "DeepSeek" in k:
    fl.pop(k, None)
s["first_load"]=fl
ans=s.setdefault("download_answers", {}); ans[pid]=True
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(s, indent=2)+"\n")
print("cleared first_load for", pid)
PY
start_lead "$R/lead-autopair.log"
wait_health
grep -E 'first-load|speculate|auto-pair|keep|break_even' "$R/lead-autopair.log" | tee "$R/gate-lines.txt" || true
$PY bench/v3/speculate_bench.py "$URL" "$MODEL_NAME" "$R/ga-autopair-suite.json" autopair suite | tee "$R/ga-autopair-suite.out"
cp -f $HOME/.caravan/mlx/guess-ahead-state.json "$R/gate-state.json" || true
grep -E 'first-load|auto-pair|break_even' "$R/lead-autopair.log" | tee "$R/gate-lines2.txt" || true
kill_lead

echo "=== shut-off (be=0.80) ==="
PAIRING_ID="$PAIRING_ID" python3 - <<'PY'
import json, os
from pathlib import Path
pid=os.environ["PAIRING_ID"]
p=Path.home()/".caravan/mlx/guess-ahead-state.json"
s=json.loads(p.read_text())
for k,v in list((s.get("first_load") or {}).items()):
  if (v or {}).get("pairing")==pid or "Qwen2.5" in k or "Distill" in k or "DeepSeek" in k:
    v=dict(v); v["break_even_frac"]=0.80; s["first_load"][k]=v; print("raised be", k)
p.write_text(json.dumps(s, indent=2)+"\n")
PY
start_lead "$R/lead-shutoff.log"
wait_health
MODEL_NAME="$MODEL_NAME" $PY - <<'PY' | tee "$R/shutoff.out"
import json, uuid, urllib.request, os
URL="http://127.0.0.1:8194"; MODEL=os.environ["MODEL_NAME"]
def one(tag):
  prompt=("Continue this random hex stream with more hex digits only, no spaces:\n"
          "a7f3c91e0b4d2e8f1a6c5b9d0e3f7a2c4b8d1e5f9a3c7b0d4e8f2a6c"+tag)
  body={"model":MODEL,"messages":[{"role":"user","content":prompt}],"max_tokens":64,"temperature":0.9,"seed":7,"stream":False}
  req=urllib.request.Request(URL+"/v1/chat/completions", json.dumps(body).encode(),
    {"Content-Type":"application/json","X-Caravan-Session":uuid.uuid4().hex[:16]})
  with urllib.request.urlopen(req, timeout=600) as r: j=json.load(r)
  cv=(j.get("usage") or {}).get("caravan") or {}
  print(json.dumps({"tag":tag,"speculate":cv.get("speculate")}, indent=2))
one("A"); one("B"); one("C")
PY
grep -E 'shut|break_even|accepted|disabled' "$R/lead-shutoff.log" | tee "$R/shutoff-log.txt" || true
kill_lead
PAIRING_ID="$PAIRING_ID" python3 - <<'PY'
import json, os
from pathlib import Path
pid=os.environ["PAIRING_ID"]
p=Path.home()/".caravan/mlx/guess-ahead-state.json"
s=json.loads(p.read_text())
for k,v in list((s.get("first_load") or {}).items()):
  if (v or {}).get("pairing")==pid or "Qwen2.5" in k or "Distill" in k or "DeepSeek" in k:
    v=dict(v)
    if v.get("break_even_frac",0)>=0.79:
      be=v.get("_measured_be") or 0.45; v["break_even_frac"]=be; s["first_load"][k]=v; print("restored be", k, be)
p.write_text(json.dumps(s, indent=2)+"\n")
PY
echo "=== SUITE_RESUME_DONE $(date) ==="
