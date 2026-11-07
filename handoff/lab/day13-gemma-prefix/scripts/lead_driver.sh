#!/bin/bash
set -euo pipefail
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
R=$HOME/.caravan/bench-2026-11-04/day13-gemma-prefix
PEER=169.254.103.191:5560
URL=http://127.0.0.1:8194
TAG=${1:?tag}; N=${2:-2048}; FLAG=${3:-on}
case "$TAG" in
  llama)
    M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit
    NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit; K=16 ;;
  qwen3)
    M=$HOME/.exo/models/mlx-community--Qwen3-30B-A3B-4bit
    NAME=mlx-community/Qwen3-30B-A3B-4bit; K=24 ;;
  gemma)
    M=$HOME/.exo/models/mlx-community--gemma-4-26b-a4b-it-4bit
    NAME=mlx-community/gemma-4-26b-a4b-it-4bit; K=15 ;;
  *) echo bad; exit 1 ;;
esac
dir="$R/${TAG}-n${N}-${FLAG}"
mkdir -p "$dir"
LPM=$(pmset -g | awk "/lowpowermode/{print \$2}")
[[ "$LPM" == "0" ]] || { echo REFUSE_LPM; exit 2; }
true 2>/dev/null || true
sleep 2
args=(--model "$M" --split-role lead --split-peer "$PEER"
      --host 127.0.0.1 --port 8194
      --split-draft-skip-first-load --no-learn --no-split-draft
      --split-packer-layers "$K" --split-pipeline-chats 1)
if [[ "$FLAG" == "on" ]]; then
  args+=(--split-shared-prefix-cache)
fi
nohup $PY "$CV/agent/mlx_worker.py" "${args[@]}" > "$dir/lead.log" 2>&1 &
echo $! > "$dir/lead.pid"
for i in $(seq 1 420); do grep -qE "listening on http" "$dir/lead.log" 2>/dev/null && break; sleep 1; done
curl -sf "$URL/health" >/dev/null
$PY "$CV/handoff/lab/day12_prefix_bench.py" "$URL" "$NAME" "$dir/prefix.json" "$N" | tee "$dir/prefix.out"
# quality: same seed, off/on content compared by orch later — also dump a fixed ask
$PY - <<PY
import json, urllib.request, uuid
URL="$URL"; MODEL="$NAME"
preamble = ("Tool schema: name=search args={query:string, limit:int}. " * 80)
body={"model":MODEL,"messages":[{"role":"system","content":preamble},{"role":"user","content":"Say the word banana once."}],"max_tokens":16,"temperature":0,"seed":7,"stream":False}
req=urllib.request.Request(URL+"/v1/chat/completions", json.dumps(body).encode(), {"Content-Type":"application/json","X-Caravan-Session":uuid.uuid4().hex[:16]})
with urllib.request.urlopen(req, timeout=600) as r:
    j=json.load(r)
open("$dir/quality.json","w").write(json.dumps({"content":j["choices"][0]["message"].get("content"),"how":(j.get("usage") or {}).get("caravan",{}).get("how"),"ttft_s":(j.get("usage") or {}).get("caravan",{}).get("ttft_s")}, indent=2)+"\n")
print("QUALITY", j["choices"][0]["message"].get("content"))
PY
kill -9 "$(cat "$dir/lead.pid")" 2>/dev/null || true
true 2>/dev/null || true
sleep 2
echo DONE_DAY13 "$TAG" "$N" "$FLAG"
