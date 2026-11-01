"""Idea 3 guess-ahead bench. Talks to the split lead (test ports).

  speculate_bench.py URL MODEL OUT.json [tag] [mode]

mode: standard (default) | suite
  standard — warm + tg128 x2 + quality 3/3 (count prompt; same as before)
  suite    — also edit/code/repetitive prompts (prompt-lookup friendly), medians of 2

Lead flags: --split-draft-model / --split-speculate-k / --split-prompt-lookup
LPM off. Does not start/stop workers.
"""
import json, sys, time, uuid, urllib.request
from pathlib import Path

URL, MODEL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
TAG = sys.argv[4] if len(sys.argv) > 4 else "spec"
MODE = sys.argv[5] if len(sys.argv) > 5 else "standard"
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
        denom = cv["total_s"] - cv["ttft_s"]
        if denom > 0:
            rec["write_tps"] = round((u["completion_tokens"] - 1) / denom, 1)
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


PROMPTS = {
    "count": ("Count from one to three hundred in words, separated by commas." + NT, 128),
    "repeat": (
        "Repeat the following paragraph exactly, twice in a row, with no other text:\n"
        "The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.\n"
        + NT, 128),
    "code_edit": (
        "Here is a Python function:\n\n"
        "def add(a, b):\n    return a + b\n\n"
        "Rewrite ONLY the function so it adds three numbers a, b, c. "
        "Output only the new function, nothing else.\n" + NT, 128),
    "code_cont": (
        "Continue this code with a standard iterative Fibonacci implementation. "
        "Output only code.\n\n"
        "def fib(n):\n    if n < 2:\n        return n\n" + NT, 128),
}


def run_pair(key):
    prompt, ntok = PROMPTS[key]
    runs = []
    for i in range(2):
        s = uuid.uuid4().hex[:16]
        runs.append(post([{"role": "user", "content": prompt}], ntok, s, f"{TAG}_{key}_{i}"))
    return runs


session = uuid.uuid4().hex[:16]
warm = post([{"role": "user", "content": "Say hi in three words." + NT}], 16, session, "warm")
results = {"count": run_pair("count")}
if MODE == "suite":
    for key in ("repeat", "code_edit", "code_cont"):
        results[key] = run_pair(key)
q = quality()
ok_q = sum(1 for r in q if r.get("ok"))


def med_tps(runs):
    vals = sorted(r.get("write_tps") for r in runs if r.get("write_tps") is not None)
    if not vals:
        return None
    return vals[len(vals) // 2] if len(vals) % 2 else vals[len(vals) // 2 - 1]  # lower median for even


out = {"tag": TAG, "model": MODEL, "url": URL, "mode": MODE, "warm": warm,
       "prompts": results, "quality": q, "quality_ok": f"{ok_q}/3",
       "medians": {k: med_tps(v) for k, v in results.items()}}
# back-compat alias
out["tg128"] = results["count"]
Path(OUT).write_text(json.dumps(out, indent=2) + "\n")
summary = {
    "tag": TAG, "mode": MODE, "quality_ok": out["quality_ok"], "medians": out["medians"],
    "count": [{"ok": r.get("ok"), "write_tps": r.get("write_tps"), "speculate": r.get("speculate"),
               "peak_gb": r.get("peak_gb"), "error": r.get("error")} for r in results["count"]],
}
if MODE == "suite":
    for key in ("repeat", "code_edit", "code_cont"):
        summary[key] = [{"write_tps": r.get("write_tps"), "speculate": r.get("speculate")}
                        for r in results[key]]
print(json.dumps(summary, indent=2))
