#!/bin/bash
# Day 13: from empty tuned-settings, chat with a shared system prompt until
# learn decides shared_prefix on or off. No --split-shared-prefix-cache flag.
set -euo pipefail
TAG=${1:?tag}
PY=$HOME/.caravan/venvs/mlx/bin/python
CV=$HOME/dev/caravan-v3
URL=http://127.0.0.1:8194
PEER=169.254.103.191:5560
R=$HOME/.caravan/bench-2026-11-04/day13-spc-learn
MAX_CHATS=${MAX_CHATS:-18}
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
dir="$R/${TAG}"
mkdir -p "$dir"
TUNED="$dir/tuned-settings.json"
rm -f "$TUNED"
LPM=$(pmset -g | awk '/lowpowermode/{print $2}')
[[ "$LPM" == "0" ]] || { echo REFUSE_LPM; exit 2; }
pkill -9 -f 'mlx_worker.py' 2>/dev/null || true
sleep 2
# Packer must already be up on exo2 (orch starts it).
args=(--model "$M" --split-role lead --split-peer "$PEER" --host 127.0.0.1 --port 8194
      --split-draft-skip-first-load --no-split-draft
      --split-packer-layers "$K" --split-pipeline-chats 1
      --tuned-settings "$TUNED")
# NOTE: no --split-shared-prefix-cache — learn must decide.
# NOTE: no --no-learn.
nohup $PY "$CV/agent/mlx_worker.py" "${args[@]}" > "$dir/lead.log" 2>&1 &
echo $! > "$dir/lead.pid"
for i in $(seq 1 420); do grep -qE 'listening on http' "$dir/lead.log" 2>/dev/null && break; sleep 1; done
curl -sf "$URL/health" >/dev/null
export URL NAME TUNED dir MAX_CHATS TAG
$PY - <<'PY'
import json, os, time, uuid, urllib.request
from pathlib import Path

URL = os.environ["URL"]
MODEL = os.environ["NAME"]
TUNED = Path(os.environ["TUNED"])
OUT_DIR = Path(os.environ["dir"])
MAX_CHATS = int(os.environ["MAX_CHATS"])
TAG = os.environ["TAG"]
NT = " /no_think" if "qwen3-30b" in MODEL.lower() else ""
unit = (
    "Tool schema: name=search args={query:string, limit:int}. "
    "Tool schema: name=read_file args={path:string}. "
    "Policy: always cite sources. Policy: never invent URLs. "
)
preamble = unit * 120  # ~2k+ tokens

def chat(i):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": preamble},
            {"role": "user", "content": f"Reply with OK{i} only." + NT},
        ],
        "max_tokens": 8, "temperature": 0, "seed": 1, "stream": False,
    }
    sess = uuid.uuid4().hex[:16]
    req = urllib.request.Request(
        URL + "/v1/chat/completions", json.dumps(body).encode(),
        {"Content-Type": "application/json", "X-Caravan-Session": sess})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        j = json.load(r)
    wall = time.time() - t0
    u = j.get("usage") or {}
    cv = u.get("caravan") or {}
    learn = cv.get("learn") or {}
    return {
        "i": i, "session": sess, "wall_s": round(wall, 3),
        "how": cv.get("how"), "ttft_s": cv.get("ttft_s"),
        "prefill_s": cv.get("prefill_s"), "prompt_n": u.get("prompt_tokens"),
        "learn_winner": (learn.get("winner") or {}),
        "learn_explore": learn.get("explore"),
        "learn_sp_probe": learn.get("shared_prefix_probe"),
        "learn_trial": learn.get("trial"),
    }

def read_tuned():
    if not TUNED.exists():
        return None
    try:
        return json.loads(TUNED.read_text())
    except Exception:
        return None

def sp_state(store):
    if not store:
        return None, {}, {}
    models = store.get("models") or {}
    # find spanned entry for this model stem
    for k, e in models.items():
        if k.endswith(":spanned"):
            w = e.get("winner") or {}
            stats = e.get("stats") or {}
            return w.get("shared_prefix"), w, {
                "off_n": (stats.get("shared_prefix:off") or {}).get("n", 0),
                "on_n": (stats.get("shared_prefix:on") or {}).get("n", 0),
                "store_n": (stats.get("shared_prefix:on_store") or {}).get("n", 0),
                "reply_n": e.get("reply_n", 0),
            }
    return None, {}, {}

runs = []
decision_chat = None
decision = None
for i in range(MAX_CHATS):
    r = chat(i)
    store = read_tuned()
    sp, winner, counts = sp_state(store)
    r["tuned_shared_prefix"] = sp
    r["tuned_counts"] = counts
    runs.append(r)
    print(json.dumps({"chat": i, "how": r["how"], "ttft_s": r["ttft_s"],
                      "sp": sp, "counts": counts,
                      "explore": r["learn_explore"], "trial": r["learn_trial"],
                      "probe": r["learn_sp_probe"]}), flush=True)
    # Decision: promoted on, OR both sides have >=3 samples and still off
    # (keep), after we've had a chance to try on (store_n>=1 or on_n>=1 or explore done).
    off_n = int(counts.get("off_n") or 0)
    on_n = int(counts.get("on_n") or 0)
    store_n = int(counts.get("store_n") or 0)
    if sp is True and on_n >= 3 and off_n >= 3:
        decision = True
        decision_chat = i + 1
        break
    if sp is False and off_n >= 3 and (on_n >= 3 or (store_n >= 1 and on_n == 0 and i >= 8)):
        # Tried on (paid store) but no helpful hits, or hits don't beat — keep off.
        # Require we've actually explored on: store_n>=1 or on_n>0.
        if store_n >= 1 or on_n >= 3:
            decision = False
            decision_chat = i + 1
            break

out = {
    "tag": TAG, "model": MODEL, "max_chats": MAX_CHATS,
    "decision_shared_prefix": decision,
    "chats_until_decision": decision_chat,
    "final_tuned": read_tuned(),
    "runs": runs,
}
(OUT_DIR / "learn.json").write_text(json.dumps(out, indent=2) + "\n")
print("RESULT", json.dumps({
    "tag": TAG, "decision": decision, "chats": decision_chat,
    "last_counts": runs[-1]["tuned_counts"] if runs else None,
}))
PY
kill -9 "$(cat "$dir/lead.pid")" 2>/dev/null || true
pkill -9 -f 'mlx_worker.py' 2>/dev/null || true
sleep 2
echo DONE_LEARN "$TAG"
