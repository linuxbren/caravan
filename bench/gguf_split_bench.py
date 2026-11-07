#!/usr/bin/env python3
"""Day 17 GGUF bench through the web UI API (same path as the browser).

  python3 bench/gguf_split_bench.py --model gguf/Qwen3-30B-A3B-Q4_K_S \
      --placement split:exo1,exo2 --runs 3 --out bench/results/day17/gguf-split.jsonl

Loads via /api/models/load, waits for ready (records load seconds), then
sends each prompt `runs` times via /api/chat (non-stream) and records the
stats Caravan shows (Read/Write tok/s, first token, total) plus llama.cpp's
own timings. Every row has prompt, settings, placement, commit, CT time.
"""
import argparse, json, subprocess, time, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "http://127.0.0.1:8190"
PROMPTS = [
    ("short", "Explain in three sentences why the sky is blue."),
    ("code", "Write a Python function that returns the n-th Fibonacci number iteratively, with a docstring."),
    ("long", "Write a 300-word story about two Mac minis that share one brain over a Thunderbolt cable."),
]


def api(path, body=None, timeout=1800):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def now_ct():
    return datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M:%S CT")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--placement", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    out = open(a.out, "a")
    base = {"model": a.model, "placement": a.placement, "commit": commit, "label": a.label}
    t0 = time.time()
    try:
        api("/api/models/load", {"model_id": a.model, "placement_id": a.placement})
    except Exception as e:
        out.write(json.dumps({**base, "kind": "load", "ok": False, "error": str(e), "ct": now_ct()}) + "\n")
        raise
    st = {}
    time.sleep(3)  # let the switch thread take over the status
    while time.time() - t0 < 1500:
        st = api("/api/status")["worker"]
        if st.get("model_id") == a.model and st["status"] in ("ready", "error"):
            break
        if st["status"] in ("idle", "error") and time.time() - t0 > 10:
            break
        time.sleep(2)
    load_s = round(time.time() - t0, 1)
    row = {**base, "kind": "load", "ok": st.get("status") == "ready", "load_s": load_s, "ct": now_ct(),
           "error": st.get("error"), "progress_tail": [p["msg"] for p in st.get("progress", [])[-6:]]}
    out.write(json.dumps(row) + "\n"); out.flush()
    print(json.dumps(row))
    if not row["ok"]:
        return 1
    for run in range(1, a.runs + 1):
        for name, prompt in PROMPTS:
            body = {"messages": [{"role": "user", "content": prompt}], "stream": False,
                    "max_tokens": a.max_tokens, "temperature": 0.6}
            ts = time.time()
            try:
                d = api("/api/chat", body)
                cw = d.get("caravan_web") or {}
                r = {**base, "kind": "chat", "ok": True, "run": run, "prompt_name": name, "prompt": prompt,
                     "max_tokens": a.max_tokens, "temperature": 0.6, "stats": cw.get("stats"),
                     "timings": d.get("timings"), "usage": d.get("usage"),
                     "wall_s": round(time.time() - ts, 3), "ct": now_ct(),
                     "reply_head": ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "")[:120]}
            except Exception as e:
                r = {**base, "kind": "chat", "ok": False, "run": run, "prompt_name": name, "error": str(e), "ct": now_ct()}
            out.write(json.dumps(r) + "\n"); out.flush()
            s = r.get("stats") or {}
            print(run, name, {k: s.get(k) for k in ("read_tok_s", "write_tok_s", "ttft_s", "total_s")} if r["ok"] else r.get("error"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
