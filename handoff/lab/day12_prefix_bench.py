#!/usr/bin/env python3
"""Day 12 idea 4: shared-prefix TTFT. Warm a long preamble once, then new sessions
that share it. Reports prefill_s / ttft_s / how / peak_gb.
  day12_prefix_bench.py URL MODEL OUT.json [n_preamble_tokens]
"""
import json, sys, time, uuid, urllib.request
from pathlib import Path

URL, MODEL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
N = int(sys.argv[4]) if len(sys.argv) > 4 else 2048
NT = " /no_think" if "qwen3-30b" in MODEL.lower() else ""
Path(OUT).expanduser().parent.mkdir(parents=True, exist_ok=True)
OUT = str(Path(OUT).expanduser())

# Build a stable long preamble (~N tokens worth of repetitive tool schema text)
unit = (
    "Tool schema: name=search args={query:string, limit:int}. "
    "Tool schema: name=read_file args={path:string}. "
    "Policy: always cite sources. Policy: never invent URLs. "
)
preamble = (unit * ((N // 20) + 8))  # overshoot; model tokenizer decides

def post(msgs, max_tokens, session, name):
    body = {"model": MODEL, "messages": msgs, "max_tokens": max_tokens,
            "temperature": 0, "seed": 1, "stream": False}
    req = urllib.request.Request(
        URL + "/v1/chat/completions", json.dumps(body).encode(),
        {"Content-Type": "application/json", "X-Caravan-Session": session})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            j = json.load(r)
    except Exception as e:
        return {"name": name, "ok": False, "error": repr(e)[:400],
                "wall_s": round(time.time() - t0, 2)}
    wall = time.time() - t0
    u = j.get("usage") or {}
    cv = u.get("caravan") or {}
    return {
        "name": name, "ok": True, "wall_s": round(wall, 3), "session": session,
        "prompt_n": u.get("prompt_tokens"), "gen_n": u.get("completion_tokens"),
        "how": cv.get("how"), "prefill_s": cv.get("prefill_s"),
        "ttft_s": cv.get("ttft_s"), "total_s": cv.get("total_s"),
        "peak_gb": cv.get("peak_gb"),
        "content": ((j["choices"][0]["message"].get("content") or "")[:120]),
    }

results = []
# 1) cold store: session A with preamble + short ask
sa = uuid.uuid4().hex[:16]
results.append(post([
    {"role": "system", "content": preamble},
    {"role": "user", "content": "Reply with OK only." + NT},
], 8, sa, "cold_store"))
# 2) new session B sharing same system preamble
for i in range(2):
    sb = uuid.uuid4().hex[:16]
    results.append(post([
        {"role": "system", "content": preamble},
        {"role": "user", "content": f"Reply with OK{i} only." + NT},
    ], 8, sb, f"new_session_{i}"))
# 3) control: different preamble (should miss)
sc = uuid.uuid4().hex[:16]
other = "Different preamble. " + ("lorem ipsum " * 400)
results.append(post([
    {"role": "system", "content": other},
    {"role": "user", "content": "Reply with OK only." + NT},
], 8, sc, "miss_control"))

out = {"model": MODEL, "url": URL, "target_preamble_chars": len(preamble), "runs": results}
Path(OUT).write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
