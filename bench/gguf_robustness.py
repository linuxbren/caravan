#!/usr/bin/env python3
"""Day 17 GGUF robustness run on EXO1 through the web UI API.

Cycles GGUF split -> MLX -> GGUF one -> GGUF split (N times), Stop mid-load,
kill EXO2's rpc-server mid-chat. After every step: what's running on EXO1
(llama-server, ssh tunnels, mlx_worker) and EXO2 (ggml-rpc-server, :50052),
compared with what the step should leave. One JSON row per step.

  python3 bench/gguf_robustness.py --cycles 5 --out bench/results/day17/gguf-robustness.jsonl
"""
import argparse, json, subprocess, threading, time, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "http://127.0.0.1:8190"
GG = "gguf/Qwen3-30B-A3B-Q4_K_S"
MLX = "qwen3-30b-a3b-4bit"
PEER = "brenden@169.254.103.191"


def api(path, body=None, timeout=1800):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def ct():
    return datetime.now(ZoneInfo("America/Chicago")).strftime("%H:%M:%S")


def sh(cmd, timeout=20):
    return subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True, timeout=timeout).stdout


def procs():
    l = sh("pgrep -f 'build/bin/llama-server' | wc -l").strip()
    t = sh("pgrep -f 'ssh .*-L 127.0.0.1:5006' | wc -l").strip()
    m = sh("pgrep -f 'agent/mlx_worker.py' | wc -l").strip()
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", PEER,
                        "pgrep -f ggml-rpc-server | wc -l; lsof -nP -iTCP:50052 -sTCP:LISTEN | grep -c LISTEN"],
                       capture_output=True, text=True, timeout=20).stdout.split()
    return {"llama": int(l), "tunnels": int(t), "mlx": int(m),
            "exo2_rpc": int(r[0]) if r else -1, "exo2_50052": int(r[1]) if len(r) > 1 else -1}


EXPECT = {"split": {"llama": 1, "tunnels": 1, "mlx": 0, "exo2_rpc": 1, "exo2_50052": 1},
          "one": {"llama": 1, "tunnels": 0, "mlx": 0, "exo2_rpc": 0, "exo2_50052": 0},
          "mlx": {"llama": 0, "tunnels": 0, "mlx": 1, "exo2_rpc": 0, "exo2_50052": 0},
          "idle": {"llama": 0, "tunnels": 0, "mlx": 0, "exo2_rpc": 0, "exo2_50052": 0}}


def wait(model, t0, timeout=900):
    time.sleep(3)
    st = {}
    while time.time() - t0 < timeout:
        st = api("/api/status")["worker"]
        if st.get("model_id") == model and st["status"] in ("ready", "error"):
            break
        if st["status"] in ("idle", "error") and time.time() - t0 > 8:
            break
        time.sleep(1.5)
    return st


def chat(max_tokens=64):
    d = api("/api/chat", {"messages": [{"role": "user", "content": "Name three rivers in one line."}],
                          "stream": False, "max_tokens": max_tokens, "temperature": 0.6})
    return (d.get("caravan_web") or {}).get("stats") or {}


def step(out, name, model, placement, expect):
    t0 = time.time()
    body = {"model_id": model}
    if placement:
        body["placement_id"] = placement
    err = None
    try:
        api("/api/models/load", body)
        st = wait(model, t0)
    except Exception as e:
        st, err = {}, str(e)
    load_s = round(time.time() - t0, 1)
    stats = {}
    if st.get("status") == "ready":
        try:
            stats = chat()
        except Exception as e:
            err = f"chat: {e}"
    time.sleep(1)
    p = procs()
    ok = st.get("status") == "ready" and p == EXPECT[expect] and not err
    row = {"ct": ct(), "step": name, "model": model, "placement": placement, "status": st.get("status"),
           "error": err or st.get("error"), "load_s": load_s, "write_tok_s": stats.get("write_tok_s"),
           "procs": p, "expected": EXPECT[expect], "ok": ok}
    out.write(json.dumps(row) + "\n"); out.flush()
    print(json.dumps(row))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    commit = sh("git rev-parse --short HEAD").strip()
    out = open(a.out, "a")
    out.write(json.dumps({"ct": ct(), "step": "start", "commit": commit}) + "\n")
    if a.only in ("", "cycles"):
        for c in range(1, a.cycles + 1):
            step(out, f"c{c} gguf-split", GG, "split:exo1,exo2", "split")
            step(out, f"c{c} mlx", MLX, None, "mlx")
            step(out, f"c{c} gguf-one", GG, "one:exo1", "one")
            step(out, f"c{c} gguf-split-2", GG, "split:exo1,exo2", "split")
    if a.only in ("", "stopmid"):
        for when in ("starting_packer", "starting_lead"):
            api("/api/models/load", {"model_id": MLX}); wait(MLX, time.time())
            t0 = time.time()
            api("/api/models/load", {"model_id": GG, "placement_id": "split:exo1,exo2"})
            seen = None
            while time.time() - t0 < 120:
                s = api("/api/status")["worker"]["status"]
                if s == when:
                    seen = s; break
                time.sleep(0.2)
            api("/api/models/stop", {})
            time.sleep(8)
            st = api("/api/status")["worker"]; p = procs()
            row = {"ct": ct(), "step": f"stop-mid-load at {when}", "seen": seen, "status": st["status"],
                   "error": st.get("error"), "procs": p, "expected": EXPECT["idle"],
                   "ok": st["status"] == "idle" and p == EXPECT["idle"]}
            out.write(json.dumps(row) + "\n"); out.flush(); print(json.dumps(row))
    if a.only in ("", "killpeer"):
        t0 = time.time()
        api("/api/models/load", {"model_id": GG, "placement_id": "split:exo1,exo2"}); wait(GG, t0)
        res = {}
        def long_chat():
            try:
                res["stats"] = chat(max_tokens=600)
            except Exception as e:
                res["err"] = str(e)[:200]
        th = threading.Thread(target=long_chat); th.start()
        time.sleep(4)
        k = subprocess.run(["ssh", "-o", "BatchMode=yes", PEER,
                            "p=$(cat ~/.caravan/web-ui/rpc-server.pid); ps -p $p -o command= | grep -q ggml-rpc-server && kill -9 $p && echo killed $p"],
                           capture_output=True, text=True).stdout.strip()
        th.join(120)
        time.sleep(6)
        st = api("/api/status")["worker"]; p = procs()
        row = {"ct": ct(), "step": "kill EXO2 rpc-server mid-chat", "kill": k, "chat": res,
               "status": st["status"], "error": st.get("error"),
               "detail_head": (st.get("error_detail") or "")[:160], "procs": p, "expected": EXPECT["idle"],
               "ok": st["status"] == "idle" and p == EXPECT["idle"] and bool(st.get("error"))}
        out.write(json.dumps(row) + "\n"); out.flush(); print(json.dumps(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
