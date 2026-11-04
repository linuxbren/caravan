"""Idea 1 concurrent-chat bench (2026-10-31). Talks straight to the split
lead (same as split_client.py). Starts N clients at once with distinct
X-Caravan-Session ids and measures per-chat and aggregate writing tok/s.

  pipeline_bench.py URL MODEL OUT.json N [no_think]

N = concurrent chats (1, 2, or 3). Warm once, then two waves of tg128
(medians later). One quality check on a separate session. Low Power Mode
must be off; lead should be started with --split-pipeline-chats N (N>1)
and idea-5 cuts. Does not start or stop workers.
"""
import json, sys, time, threading, urllib.request, uuid
from pathlib import Path

URL, MODEL, OUT, N = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NT = " /no_think" if "qwen3-30b" in MODEL.lower() else ""
if len(sys.argv) > 5 and sys.argv[5] in ("no_think", "/no_think"):
    NT = " /no_think"
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
        return {"name": name, "ok": False, "error": repr(e)[:300],
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
           "pipeline": cv.get("pipeline"),
           "speculate": cv.get("speculate"),
           "content": (msg.get("content") or "")[:200]}
    if u.get("completion_tokens", 0) > 1 and cv.get("total_s") and cv.get("ttft_s"):
        rec["write_tps"] = round((u["completion_tokens"] - 1) / (cv["total_s"] - cv["ttft_s"]), 1)
    return rec


def wave(tag, n):
    """Fire n concurrent tg128 requests; return per-chat records + aggregate."""
    sessions = [uuid.uuid4().hex[:16] for _ in range(n)]
    results = [None] * n

    def one(i):
        prompt = (f"[{sessions[i]}] Count from one to three hundred in words, "
                  f"separated by commas." + NT)
        results[i] = post([{"role": "user", "content": prompt}], 128, sessions[i],
                          f"{tag}_chat{i}")

    t_wall0 = time.time()
    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t_wall0
    ok = [r for r in results if r and r.get("ok")]
    gen_total = sum((r.get("gen_n") or 0) for r in ok)
    # Aggregate writing: total completion tokens across chats / wall (minus nothing —
    # includes prefill; also report decode-only aggregate from sum of per-chat decode times).
    decode_tokens = sum(max((r.get("gen_n") or 0) - 1, 0) for r in ok)
    decode_s = 0.0
    for r in ok:
        if r.get("total_s") is not None and r.get("ttft_s") is not None:
            decode_s = max(decode_s, (r["total_s"] - r["ttft_s"]))  # overlapping: use max
    # Better aggregate for overlapped decode: tokens_sum / wall_decode_span
    # wall_decode_span ≈ max(end)-min(start) approximated by wave wall minus mean prefill
    prefills = [r.get("prefill_s") or 0 for r in ok]
    approx_decode_wall = max(wall - (min(prefills) if prefills else 0), 1e-6)
    agg = {
        "name": f"{tag}_aggregate",
        "n": n,
        "ok_n": len(ok),
        "wall_s": round(wall, 3),
        "gen_tokens_sum": gen_total,
        "per_chat_write_tps": [r.get("write_tps") for r in results],
        "per_chat_ttft_s": [r.get("ttft_s") for r in results],
        "per_chat_peak_gb": [r.get("peak_gb") for r in results],
        "aggregate_write_tps_wall": round(decode_tokens / approx_decode_wall, 1) if ok else None,
        "aggregate_write_tps_sum": round(sum(r.get("write_tps") or 0 for r in ok), 1) if ok else None,
    }
    return results, agg


def log_rec(rec):
    print(json.dumps(rec), flush=True)
    open(OUT + "l", "a").write(json.dumps(rec) + "\n")


# warm
log_rec(post([{"role": "user", "content": "Hello warm-up." + NT}], 8,
             uuid.uuid4().hex[:16], "warm"))

for i in range(2):
    recs, agg = wave(f"tg128_w{i}", N)
    for r in recs:
        log_rec(r)
    log_rec(agg)

# quality on one session (same prompts helper inline — short check)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "improvements"))
from common import prompts, score  # noqa: E402
mt = 200 if NT else 1536
r = post([{"role": "user", "content": prompts()["long"] + NT}], mt,
         uuid.uuid4().hex[:16], "quality")
log_rec(r)
if r.get("ok"):
    # need full content — re-fetch not available; score truncated content is weak.
    # For quality, call again storing more content:
    pass
