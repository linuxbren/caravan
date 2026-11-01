"""Idea 3 guess-ahead bench (2026-11-01). Talks to the split lead.

  speculate_bench.py URL MODEL OUT.json [tag]

Warm once, then two tg128 runs (medians later). One quality check.
Lead should be started with --split-draft-model and --split-speculate-k.
Does not start or stop workers. Low Power Mode must be off.
"""
import json, sys, time, uuid, urllib.request
from pathlib import Path

URL, MODEL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
TAG = sys.argv[4] if len(sys.argv) > 4 else "spec"
NT = " /no_think" if "qwen3-30b" in MODEL.lower() else ""
Path(OUT).expanduser().parent.mkdir(parents=True, exist_ok=True)
OUT = str(Path(OUT).expanduser())


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
                "wall_s": round(time.time() - t0, 2), "session": session}
    wall = time.time() - t0
    u = j.get("usage") or {}
    cv = u.get("caravan") or {}
    msg = j["choices"][0]["message"]
    rec = {"name": name, "ok": True, "wall_s": round(wall, 3), "session": session,
           "prompt_n": u.get("prompt_tokens"), "gen_n": u.get("completion_tokens"),
           "how": cv.get("how"), "prefill_s": cv.get("prefill_s"),
           "ttft_s": cv.get("ttft_s"), "total_s": cv.get("total_s"),
           "peak_gb": cv.get("peak_gb"), "split": cv.get("split"),
           "speculate": cv.get("speculate"),
           "content": (msg.get("content") or "")[:240]}
    if u.get("completion_tokens", 0) > 1 and cv.get("total_s") and cv.get("ttft_s"):
        rec["write_tps"] = round((u["completion_tokens"] - 1) / (cv["total_s"] - cv["ttft_s"]), 1)
    return rec


def quality():
    q = []
    for i, prompt in enumerate([
        "What is 2+2? Reply with just the number.",
        "Name the capital of France. One word.",
        "Is ice cream typically hot or cold? One word.",
    ]):
        q.append(post([{"role": "user", "content": prompt + NT}], 32,
                      uuid.uuid4().hex[:16], f"quality_{i}"))
    return q


session = uuid.uuid4().hex[:16]
warm = post([{"role": "user", "content": "Say hi in three words." + NT}], 16, session, "warm")
runs = []
for i in range(2):
    s = uuid.uuid4().hex[:16]
    prompt = ("Count from one to three hundred in words, separated by commas." + NT)
    runs.append(post([{"role": "user", "content": prompt}], 128, s, f"{TAG}_tg128_{i}"))
q = quality()
ok_q = sum(1 for r in q if r.get("ok"))
out = {"tag": TAG, "model": MODEL, "url": URL, "warm": warm, "tg128": runs, "quality": q,
       "quality_ok": f"{ok_q}/3"}
Path(OUT).write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps({
    "tag": TAG,
    "tg128": [{"ok": r.get("ok"), "write_tps": r.get("write_tps"), "speculate": r.get("speculate"),
               "peak_gb": r.get("peak_gb"), "ttft_s": r.get("ttft_s"), "error": r.get("error")}
              for r in runs],
    "quality_ok": out["quality_ok"],
}, indent=2))
