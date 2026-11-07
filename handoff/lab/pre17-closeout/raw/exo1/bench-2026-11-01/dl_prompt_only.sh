#!/bin/bash
set -euo pipefail
: "${SUITE_NAME:?}" "${MODEL_DIR:?}" "${PAIRING_ID:?}" "${K:?}" "${DRAFT_NAME:?}"
R=$HOME/.caravan/bench-2026-11-01/$SUITE_NAME
M=$MODEL_DIR
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
PEER=169.254.104.38:5560
DRAFT="$HOME/.caravan/mlx-models/drafts/$DRAFT_NAME"
mkdir -p "$R"; cd "$CV"
echo "=== download prompt only $SUITE_NAME $(date) ===" | tee -a "$R/suite.log"
kill_lead() {
  pkill -9 -f 'mlx_worker.py --split-role lead' 2>/dev/null || true
  sleep 3
  pkill -9 -f 'mlx_worker.py --split-role lead' 2>/dev/null || true
  sleep 2
}
kill_lead
if [[ -d "$DRAFT" && ! -d "${DRAFT}.bak" ]]; then
  mv "$DRAFT" "${DRAFT}.bak"
  echo "moved draft aside -> .bak"
elif [[ -d "${DRAFT}.bak" ]]; then
  echo "bak already present; removing live draft if any"
  rm -rf "$DRAFT" 2>/dev/null || true
fi
PAIRING_ID="$PAIRING_ID" python3 - <<'PY'
import json, os
from pathlib import Path
pid=os.environ["PAIRING_ID"]
p=Path.home()/".caravan/mlx/guess-ahead-state.json"
s=json.loads(p.read_text()) if p.exists() else {"version":1}
ans=s.get("download_answers") or {}
ans.pop(pid, None)
s["download_answers"]=ans
# also clear first_load for this pairing so download path is clean
fl=s.get("first_load") or {}
for k,v in list(fl.items()):
  if (v or {}).get("pairing")==pid:
    fl.pop(k, None)
s["first_load"]=fl
p.write_text(json.dumps(s, indent=2)+"\n")
print("cleared answer+first_load", pid)
PY
python3 - <<PY | tee "$R/dl-prompt.log"
import os, pty, select, time, signal, sys
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
while time.time()-t0 < 600:
  r,_,_=select.select([fd],[],[],1.0)
  if fd in r:
    try: data=os.read(fd,4096)
    except OSError: break
    if not data: break
    sys.stdout.buffer.write(data); sys.stdout.buffer.flush(); buf+=data
    if (not answered) and b"Download" in buf and b"[y/N]" in buf:
      os.write(fd,b"y\n"); answered=True
    if b"listening on http" in buf: break
    if b"Traceback" in buf and b"listening on http" not in buf and time.time()-t0>30:
      break
os.kill(pid, signal.SIGTERM); time.sleep(2)
try: os.kill(pid, signal.SIGKILL)
except Exception: pass
print("\nANSWERED", answered)
text=buf.decode("utf-8","replace")
print("HAS_PROMPT", ("Download" in text and "[y/N]" in text))
print("DOWNLOADED", "downloaded helper" in text)
PY
# restore bak draft; remove freshly downloaded if both exist
if [[ -d "$DRAFT" && -d "${DRAFT}.bak" ]]; then
  rm -rf "$DRAFT"
  mv "${DRAFT}.bak" "$DRAFT"
  echo "restored draft from .bak (removed fresh download)"
elif [[ -d "${DRAFT}.bak" ]]; then
  mv "${DRAFT}.bak" "$DRAFT"
  echo "restored draft from .bak"
fi
kill_lead
echo "=== DOWNLOAD_PROMPT_DONE $(date) ===" | tee -a "$R/suite.log"
