#!/bin/bash
set -euo pipefail
TAG=${1:?tag}; FLAG=${2:?flag}
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
URL=http://127.0.0.1:8194
PEER=169.254.103.191:5560
R=$HOME/.caravan/bench-2026-11-04/day13-gemma-prefix
N=2048
case "$TAG" in
  llama)
    M=$HOME/.caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit
    NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit; K=16 ;;
  qwen3)
    M=$HOME/.exo/models/mlx-community--Qwen3-30B-A3B-4bit
    NAME=mlx-community/Qwen3-30B-A3B-4bit; K=24 ;;
  *) echo bad; exit 1 ;;
esac
dir="$R/${TAG}-n${N}-${FLAG}-fresh"
mkdir -p "$dir"
LPM=$(pmset -g | awk '/lowpowermode/{print $2}')
[[ "$LPM" == "0" ]] || { echo REFUSE_LPM; exit 2; }
true 2>/dev/null || true
sleep 2
args=(--model "$M" --split-role lead --split-peer "$PEER" --host 127.0.0.1 --port 8194
      --split-draft-skip-first-load --no-learn --no-split-draft
      --split-packer-layers "$K" --split-pipeline-chats 1)
if [[ "$FLAG" == on ]]; then args+=(--split-shared-prefix-cache); fi
nohup $PY "$CV/agent/mlx_worker.py" "${args[@]}" > "$dir/lead.log" 2>&1 &
echo $! > "$dir/lead.pid"
for i in $(seq 1 420); do grep -qE 'listening on http' "$dir/lead.log" 2>/dev/null && break; sleep 1; done
curl -sf "$URL/health" >/dev/null
$PY "$CV/handoff/lab/day12_prefix_bench.py" "$URL" "$NAME" "$dir/prefix.json" "$N" | tee "$dir/prefix.out"
export NAME FLAG dir URL
$PY - <<'PY'
import json, time, uuid, urllib.request, os
from pathlib import Path
URL = os.environ["URL"]
MODEL = os.environ["NAME"]
FLAG = os.environ["FLAG"]
dir = os.environ["dir"]
NT = " /no_think" if "qwen3-30b" in MODEL.lower() else ""
OUT = Path(dir) / "write.json"
TG = "Write a short numbered list of five everyday household tools and one sentence about each."

def stream_chat(prompt, max_tokens=128, name="tg"):
    body = {"model": MODEL, "messages":[{"role":"user","content": prompt + NT}],
            "max_tokens": max_tokens, "temperature": 0, "seed": 1, "stream": True}
    sess = uuid.uuid4().hex[:16]
    req = urllib.request.Request(URL+"/v1/chat/completions", json.dumps(body).encode(),
        {"Content-Type":"application/json","X-Caravan-Session":sess})
    t0 = time.time(); ttft=None; content=""; gen_n=0; finish=None; cv={}
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"): continue
            data = line[5:].strip()
            if data == "[DONE]": break
            try: j = json.loads(data)
            except Exception: continue
            if ttft is None: ttft = time.time()-t0
            ch = (j.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            if delta.get("content"): content += delta["content"]
            if ch.get("finish_reason"): finish = ch["finish_reason"]
            u = j.get("usage") or {}
            if u:
                gen_n = u.get("completion_tokens") or gen_n
                cv = u.get("caravan") or cv
    wall = time.time()-t0
    if not gen_n:
        gen_n = max(1, len(content.split()))
    gen_tps = None
    if ttft and gen_n and gen_n > 1 and wall > ttft:
        gen_tps = round((gen_n - 1) / (wall - ttft), 1)
    return {"name": name, "ttft_s": round(ttft,3) if ttft else None, "wall_s": round(wall,3),
            "gen_n": gen_n, "gen_tps": gen_tps, "finish": finish,
            "how": cv.get("how"), "content": content[:160],
            "caravan": {k: cv.get(k) for k in ("ttft_s","prefill_s","total_s","peak_gb","how") if cv}}

runs = [stream_chat(f"[w{i}] "+TG, 128, f"tg128_r{i}") for i in range(2)]
tps = sorted([r["gen_tps"] for r in runs if r.get("gen_tps")])
out = {"model": MODEL, "flag": FLAG, "runs": runs,
       "tg128_median": tps[len(tps)//2] if tps else None}
OUT.write_text(json.dumps(out, indent=2)+"\n")
print(json.dumps(out, indent=2))
PY
kill -9 "$(cat "$dir/lead.pid")" 2>/dev/null || true
true 2>/dev/null || true
sleep 2
echo DONE_FRESH "$TAG" "$FLAG"
