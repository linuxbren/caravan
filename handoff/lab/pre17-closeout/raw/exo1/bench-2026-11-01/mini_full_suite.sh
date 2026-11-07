#!/bin/bash
# Full Mini suite (Llama-class). Env:
#   SUITE_NAME  e.g. qwen25-suite
#   MODEL_DIR   local path
#   MODEL_NAME  API/HF style name
#   PAIRING_ID  guessers.json id (qwen25 / deepseek-r1-distill-qwen)
#   K           packer layers (even cut)
#   DRAFT_NAME  short draft dir name under drafts/
# Optional: SKIP_DOWNLOAD_PROMPT=1 SKIP_SHUTOFF=1
set -euo pipefail
: "${SUITE_NAME:?}" "${MODEL_DIR:?}" "${MODEL_NAME:?}" "${PAIRING_ID:?}" "${K:?}" "${DRAFT_NAME:?}"
R=$HOME/.caravan/bench-2026-11-01/$SUITE_NAME
M=$MODEL_DIR
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
URL=http://127.0.0.1:8194
PEER=169.254.104.38:5560
mkdir -p "$R"
cd "$CV"
echo "=== SUITE $SUITE_NAME model=$MODEL_NAME pairing=$PAIRING_ID K=$K $(date) ==="
pmset -g | grep -i lowpower || true

kill_lead() {
  pkill -f 'mlx_worker.py --split-role lead' 2>/dev/null || true
  sleep 2
  pkill -9 -f 'mlx_worker.py --split-role lead' 2>/dev/null || true
  sleep 1
}
start_lead() {
  kill_lead
  local log=$1; shift
  nohup $PY agent/mlx_worker.py \
    --model "$M" \
    --split-role lead --split-peer "$PEER" \
    --split-packer-layers "$K" \
    --host 127.0.0.1 --port 8194 \
    "$@" > "$log" 2>&1 &
  echo $! > "${log}.pid"
  for i in $(seq 1 240); do
    if grep -q 'listening on http' "$log" 2>/dev/null; then
      echo "LEAD_UP $log"; return 0
    fi
    sleep 1
  done
  echo "LEAD_FAIL $log"; tail -50 "$log"; return 1
}
wait_health() {
  for i in $(seq 1 90); do
    curl -sf "$URL/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

echo "=== keepalive OFF ==="
start_lead "$R/lead-ka-off.log" --no-split-keepalive --no-split-draft --split-draft-skip-first-load
wait_health
$PY bench/v3/split_client.py bench "$URL" "$MODEL_NAME" "$R/ka-off.json" | tee "$R/ka-off.out"
# also copy jsonl if client wrote .jsonl
kill_lead

echo "=== keepalive ON ==="
start_lead "$R/lead-ka-on.log" --no-split-draft --split-draft-skip-first-load
wait_health
$PY bench/v3/split_client.py bench "$URL" "$MODEL_NAME" "$R/ka-on.json" | tee "$R/ka-on.out"
kill_lead

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
PAIRING_ID="$PAIRING_ID" DRAFT_NAME="$DRAFT_NAME" python3 - <<'PY'
import json, os
from pathlib import Path
pid=os.environ["PAIRING_ID"]
p=Path.home()/".caravan/mlx/guess-ahead-state.json"
s=json.loads(p.read_text()) if p.exists() else {}
fl=s.get("first_load") or {}
# clear first_load entries that mention this pairing's draft or family keywords
keys=[]
for k in list(fl):
  kl=k.lower()
  if pid.replace("-","") in kl.replace("-","") or "qwen2.5" in kl or "distill" in kl or "deepseek-r1" in kl:
    # only clear keys for THIS run's models — be conservative: clear all qwen2.5/distill first_load
    keys.append(k)
# clearer: clear any first_load whose pairing field matches
for k,v in list(fl.items()):
  if (v or {}).get("pairing")==pid or pid.split("-")[0] in k.lower() or "Qwen2.5" in k or "Distill" in k or "DeepSeek-R1" in k:
    fl.pop(k, None)
s["first_load"]=fl
ans=s.setdefault("download_answers", {})
ans[pid]=True
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(s, indent=2)+"\n")
print("cleared first_load for", pid, "answers", ans)
PY
start_lead "$R/lead-autopair.log"
wait_health
grep -E 'first-load|speculate|auto-pair|keep|break_even' "$R/lead-autopair.log" | tee "$R/gate-lines.txt" || true
$PY bench/v3/speculate_bench.py "$URL" "$MODEL_NAME" "$R/ga-autopair-suite.json" autopair suite | tee "$R/ga-autopair-suite.out"
# snapshot gate state
cp -f $HOME/.caravan/mlx/guess-ahead-state.json "$R/gate-state.json" || true
grep -E 'first-load|auto-pair|break_even' "$R/lead-autopair.log" | tee "$R/gate-lines2.txt" || true
kill_lead

echo "=== shut-off (be=0.80, no skip-first-load) ==="
PAIRING_ID="$PAIRING_ID" python3 - <<'PY'
import json, os
from pathlib import Path
pid=os.environ["PAIRING_ID"]
p=Path.home()/".caravan/mlx/guess-ahead-state.json"
s=json.loads(p.read_text())
for k,v in list((s.get("first_load") or {}).items()):
  if (v or {}).get("pairing")==pid or "Qwen2.5" in k or "Distill" in k or "DeepSeek" in k or pid in k.lower():
    v=dict(v); v["break_even_frac"]=0.80; s["first_load"][k]=v
    print("raised be", k)
p.write_text(json.dumps(s, indent=2)+"\n")
PY
start_lead "$R/lead-shutoff.log"
wait_health
MODEL_NAME="$MODEL_NAME" $PY - <<'PY' | tee "$R/shutoff.out"
import json, uuid, urllib.request, time, os
URL="http://127.0.0.1:8194"
MODEL=os.environ["MODEL_NAME"]
def one(tag):
  prompt=("Continue this random hex stream with more hex digits only, no spaces:\n"
          "a7f3c91e0b4d2e8f1a6c5b9d0e3f7a2c4b8d1e5f9a3c7b0d4e8f2a6c"+tag)
  body={"model":MODEL,"messages":[{"role":"user","content":prompt}],
        "max_tokens":64,"temperature":0.9,"seed":7,"stream":False}
  req=urllib.request.Request(URL+"/v1/chat/completions", json.dumps(body).encode(),
    {"Content-Type":"application/json","X-Caravan-Session":uuid.uuid4().hex[:16]})
  with urllib.request.urlopen(req, timeout=600) as r: j=json.load(r)
  cv=(j.get("usage") or {}).get("caravan") or {}
  print(json.dumps({"tag":tag,"speculate":cv.get("speculate")}, indent=2))
one("A"); one("B"); one("C")
PY
grep -E 'shut|break_even|accepted|disabled' "$R/lead-shutoff.log" | tee "$R/shutoff-log.txt" || true
kill_lead

# restore break_even toward measured if present
PAIRING_ID="$PAIRING_ID" python3 - <<'PY'
import json, os
from pathlib import Path
pid=os.environ["PAIRING_ID"]
p=Path.home()/".caravan/mlx/guess-ahead-state.json"
s=json.loads(p.read_text())
for k,v in list((s.get("first_load") or {}).items()):
  if (v or {}).get("pairing")==pid or "Qwen2.5" in k or "Distill" in k or "DeepSeek" in k:
    v=dict(v)
    # leave keep; set be from derived if we stored ~0.45 style — keep 0.45 as safe default after demo
    if v.get("break_even_frac",0)>=0.79:
      be=v.get("_measured_be") or 0.45
      v["break_even_frac"]=be
      s["first_load"][k]=v
      print("restored be", k, be)
p.write_text(json.dumps(s, indent=2)+"\n")
PY

if [[ "${SKIP_DOWNLOAD_PROMPT:-0}" != "1" ]]; then
  echo "=== download prompt ==="
  DRAFT="$HOME/.caravan/mlx-models/drafts/$DRAFT_NAME"
  if [[ -d "$DRAFT" ]]; then
    mv "$DRAFT" "${DRAFT}.bak"
  fi
  PAIRING_ID="$PAIRING_ID" python3 - <<'PY'
import json, os
from pathlib import Path
pid=os.environ["PAIRING_ID"]
p=Path.home()/".caravan/mlx/guess-ahead-state.json"
s=json.loads(p.read_text())
ans=s.get("download_answers") or {}
ans.pop(pid, None)
s["download_answers"]=ans
p.write_text(json.dumps(s, indent=2)+"\n")
print("cleared answer", pid)
PY
  python3 - <<PY | tee "$R/dl-prompt.log"
import os, pty, select, time, signal, sys
log_path=os.path.expanduser("$R/dl-prompt.log")
# also write via tee externally; here print
cmd=[os.path.expanduser("~/.caravan/venvs/mlx/bin/python"),
     os.path.expanduser("~/dev/caravan-v3/agent/mlx_worker.py"),
     "--model", os.path.expanduser("$M"),
     "--split-role","lead","--split-peer","$PEER","--split-packer-layers","$K",
     "--host","127.0.0.1","--port","8194","--split-draft-skip-first-load"]
pid,fd=pty.fork()
if pid==0:
  os.chdir(os.path.expanduser("~/dev/caravan-v3"))
  os.execv(cmd[0], cmd)
answered=False; buf=b""; t0=time.time()
while time.time()-t0 < 300:
  r,_,_=select.select([fd],[],[],1.0)
  if fd in r:
    try: data=os.read(fd,4096)
    except OSError: break
    if not data: break
    sys.stdout.buffer.write(data); sys.stdout.buffer.flush(); buf+=data
    if (not answered) and b"Download" in buf and b"[y/N]" in buf:
      os.write(fd,b"y\n"); answered=True
    if b"listening on http" in buf: break
os.kill(pid, signal.SIGTERM); time.sleep(2)
try: os.kill(pid, signal.SIGKILL)
except Exception: pass
print("\\nANSWERED", answered)
PY
  # restore bak draft; remove freshly downloaded if both exist
  if [[ -d "$DRAFT" && -d "${DRAFT}.bak" ]]; then
    rm -rf "$DRAFT"
    mv "${DRAFT}.bak" "$DRAFT"
  elif [[ -d "${DRAFT}.bak" ]]; then
    mv "${DRAFT}.bak" "$DRAFT"
  fi
  kill_lead
fi

echo "=== SUITE_DONE $SUITE_NAME $(date) ==="
