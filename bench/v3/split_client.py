"""Caravan v3 bench client (2026-10-31). Talks straight to an MLX worker
(v2.1 single Mini, or the v3 split head) with X-Caravan-Session, so both
variants take the same path.

  split_client.py bench  URL MODEL OUT.json [no_think]   warm, tg128 x2, pp512 x2, pp4096 x2, quality 3/3
  split_client.py chat   URL MODEL OUT.json TOKENS TAG   turn 1 + turn 2 of a TOKENS-long chat (state kept in OUT)
  split_client.py resume URL MODEL OUT.json TAG          turn 3 after a restart
Appends one JSON line per request to OUT.jsonl and prints it."""
import json, sys, time, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "improvements"))
from common import filler, prompts, score  # noqa: E402

CMD, URL, MODEL, OUT = sys.argv[1:5]
NT = " /no_think" if "qwen3-30b" in MODEL.lower() else ""   # Qwen3.6 has no /no_think switch
STATE = Path(OUT + ".state.json")


def post(msgs, max_tokens, session, name):
    body = {"model": MODEL, "messages": msgs, "max_tokens": max_tokens, "temperature": 0, "seed": 1, "stream": False}
    req = urllib.request.Request(URL + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "X-Caravan-Session": session})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            j = json.load(r)
    except Exception as e:
        rec = {"name": name, "ok": False, "error": repr(e)[:300], "wall_s": round(time.time() - t0, 2)}
        print(json.dumps(rec), flush=True); open(OUT + "l", "a").write(json.dumps(rec) + "\n"); return rec, None
    wall = time.time() - t0
    u = j.get("usage") or {}; cv = u.get("caravan") or {}
    msg = j["choices"][0]["message"]
    rec = {"name": name, "ok": True, "wall_s": round(wall, 3), "prompt_n": u.get("prompt_tokens"),
           "gen_n": u.get("completion_tokens"), "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
           "how": cv.get("how"), "prefill_s": cv.get("prefill_s"), "ttft_s": cv.get("ttft_s"), "total_s": cv.get("total_s"),
           "peak_gb": cv.get("peak_gb"), "split": cv.get("split"), "content": (msg.get("content") or "")[:400]}
    if cv.get("prefill_s") and u.get("prompt_tokens"):
        rec["read_tps"] = round(u["prompt_tokens"] / cv["prefill_s"], 1)
    if u.get("completion_tokens", 0) > 1 and cv.get("total_s") and cv.get("ttft_s"):
        rec["write_tps"] = round((u["completion_tokens"] - 1) / (cv["total_s"] - cv["ttft_s"]), 1)
    print(json.dumps(rec), flush=True); open(OUT + "l", "a").write(json.dumps(rec) + "\n")
    return rec, msg


def sid():
    return uuid.uuid4().hex[:16]


def calib():
    r, _ = post([{"role": "user", "content": f"[calib {sid()}]\n" + "\n".join(filler(200))}], 1, sid(), "calib")
    return (r.get("prompt_n") or 4800) / 200.0


def lines_for(n, tpl):
    return max(1, int(round((n - 40) / tpl)))


if CMD == "bench":
    post([{"role": "user", "content": "Hello there, this is a warm-up request." + NT}], 8, sid(), "warm")
    for i in range(2):
        post([{"role": "user", "content": f"[{sid()}] Count from one to three hundred in words, separated by commas." + NT}],
             128, sid(), f"tg128_{i}")
    tpl = calib()
    for n in (512, 4096):
        for i in range(2):
            post([{"role": "user", "content": f"[pp{n} {sid()}]\n" + "\n".join(filler(lines_for(n, tpl)))}], 1, sid(), f"pp{n}_{i}")
    mt = 200 if NT else 1536
    r, msg = post([{"role": "user", "content": prompts()["long"] + NT}], mt, sid(), "quality")
    if r["ok"]:
        sc = score((msg.get("content") or ""))
        sr = score((msg.get("content") or "") + (msg.get("reasoning") or msg.get("reasoning_content") or ""))
        rec = {"name": "quality_score", "score": sum(sc.values()), "detail": sc,
               "score_incl_reasoning": sum(sr.values()), "finish": r.get("gen_n")}
        print(json.dumps(rec)); open(OUT + "l", "a").write(json.dumps(rec) + "\n")
elif CMD == "chat":
    n, tag = int(sys.argv[5]), sys.argv[6]
    tpl = calib()
    lines = filler(lines_for(n, tpl)); lines.insert(len(lines) // 3, "Important note: the vault access code is ORCHID-7419.")
    s = sid()
    msgs = [{"role": "user", "content": "Here is a long inventory log.\n" + "\n".join(lines) +
             "\n\nWhat is the vault access code? Answer in one short line." + NT}]
    mt = 32 if NT else 768
    r1, m1 = post(msgs, mt, s, f"{tag}_t1")
    st = {"session": s, "msgs": msgs, "t1": r1}
    if m1 is not None:
        msgs = msgs + [{"role": "assistant", "content": m1.get("content") or ""},
                       {"role": "user", "content": "What is 17 multiplied by 23? Answer in one short line." + NT}]
        r2, m2 = post(msgs, mt, s, f"{tag}_t2")
        st.update(msgs=msgs, t2=r2)
        if m2 is not None:
            st["msgs"] = msgs + [{"role": "assistant", "content": m2.get("content") or ""}]
    json.dump(st, open(str(STATE) + "." + tag, "w"))
elif CMD == "resume":
    tag = sys.argv[5]
    st = json.load(open(str(STATE) + "." + tag))
    msgs = st["msgs"] + [{"role": "user", "content": "What is the capital of Australia? Answer in one short line." + NT}]
    post(msgs, 32 if NT else 768, st["session"], f"{tag}_t3_after_restart")
