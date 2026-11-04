"""Day 12 spanned light bench: warm, tg128 x2, pp512 x2, quality 3/3. No pp4096.
Usage: day12_fuse_light_bench.py URL MODEL OUT.json
"""
import json, sys, time, urllib.request, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "improvements"))
from common import filler, prompts, score  # noqa: E402

URL, MODEL, OUT = sys.argv[1:4]
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
        rec = {"name": name, "ok": False, "error": repr(e)[:300],
               "wall_s": round(time.time() - t0, 2)}
        print(json.dumps(rec), flush=True)
        open(OUT + "l", "a").write(json.dumps(rec) + "\n")
        return rec, None
    wall = time.time() - t0
    u = j.get("usage") or {}
    cv = u.get("caravan") or {}
    msg = j["choices"][0]["message"]
    rec = {"name": name, "ok": True, "wall_s": round(wall, 3),
           "prompt_n": u.get("prompt_tokens"), "gen_n": u.get("completion_tokens"),
           "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
           "how": cv.get("how"), "prefill_s": cv.get("prefill_s"),
           "ttft_s": cv.get("ttft_s"), "total_s": cv.get("total_s"),
           "peak_gb": cv.get("peak_gb"), "split": cv.get("split"),
           "speculate": cv.get("speculate"), "pipeline": cv.get("pipeline"),
           "content": (msg.get("content") or "")[:400]}
    if cv.get("prefill_s") and u.get("prompt_tokens"):
        rec["read_tps"] = round(u["prompt_tokens"] / cv["prefill_s"], 1)
    if u.get("completion_tokens", 0) > 1 and cv.get("total_s") and cv.get("ttft_s"):
        rec["write_tps"] = round(
            (u["completion_tokens"] - 1) / (cv["total_s"] - cv["ttft_s"]), 1)
    print(json.dumps(rec), flush=True)
    open(OUT + "l", "a").write(json.dumps(rec) + "\n")
    return rec, msg


def sid():
    return uuid.uuid4().hex[:16]


def calib():
    r, _ = post([{"role": "user",
                  "content": f"[calib {sid()}]\n" + "\n".join(filler(200))}],
                1, sid(), "calib")
    return (r.get("prompt_n") or 4800) / 200.0


def lines_for(n, tpl):
    return max(1, int(round((n - 40) / tpl)))


post([{"role": "user", "content": "Hello there, this is a warm-up request." + NT}],
     8, sid(), "warm")
for i in range(2):
    post([{"role": "user",
           "content": (f"[{sid()}] Count from one to three hundred in words, "
                       f"separated by commas." + NT)}],
         128, sid(), f"tg128_{i}")
tpl = calib()
for i in range(2):
    post([{"role": "user",
           "content": f"[pp512 {sid()}]\n" + "\n".join(filler(lines_for(512, tpl)))}],
         1, sid(), f"pp512_{i}")
mt = 200 if NT else 1536
r, msg = post([{"role": "user", "content": prompts()["long"] + NT}], mt, sid(), "quality")
if r["ok"] and msg is not None:
    sc = score((msg.get("content") or ""))
    sr = score((msg.get("content") or "") +
               (msg.get("reasoning") or msg.get("reasoning_content") or ""))
    rec = {"name": "quality_score", "score": sum(sc.values()), "detail": sc,
           "score_incl_reasoning": sum(sr.values()), "finish": r.get("gen_n")}
    print(json.dumps(rec), flush=True)
    open(OUT + "l", "a").write(json.dumps(rec) + "\n")
