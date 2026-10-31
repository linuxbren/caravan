"""usage: resume_bench.py <ollama|exo> <tag> <model> <max_tokens> <tok_per_line>
Same 3-turn ~16k conversation as caravan_bench.py resume phase:
 t1 cold -> t2 warm-in-memory -> restart runtime (ollama: stop/start `ollama serve` + preload model;
 exo: DELETE instance + re-place single-node + wait RunnerReady) -> t3 TTFT after restart."""
import json, os, signal, subprocess, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); from common import *
RT, TAG, MODEL, MAXTOK, TPL = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5])
NO_THINK = os.environ.get("NO_THINK", "")
B = Path.home() / ".caravan/bench-2026-10-30/runtime-compare/resume" / RT / TAG; B.mkdir(parents=True, exist_ok=True)
LOG = open(B / "run.log", "a")
def log(*a):
    s = time.strftime("%T ") + " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
NC = 18432
def req(url, body=None, method=None, timeout=1800):
    return urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"}, method=method)
def call(url, body=None, method=None, timeout=120):
    return json.load(urllib.request.urlopen(req(url, body, method), timeout=timeout))
# ---------- ollama ----------
OL = str(Path.home() / "ollama-bench" / "ollama"); OH = "http://127.0.0.1:11434"
def ol_serve():
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_FLASH_ATTENTION="1", OLLAMA_KV_CACHE_TYPE="q8_0",
               OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_KEEP_ALIVE="-1", OLLAMA_NOPRUNE="1")
    t0 = time.time(); p = subprocess.Popen([OL, "serve"], stdout=open(B / "serve.log", "a"), stderr=subprocess.STDOUT, env=env)
    for _ in range(120):
        try: urllib.request.urlopen(OH + "/api/version", timeout=2); break
        except Exception: time.sleep(0.5)
    r = call(OH + "/api/generate", {"model": MODEL, "keep_alive": -1, "options": {"num_ctx": NC, "num_gpu": 999}}, timeout=600)
    dt = round(time.time() - t0, 1); log(f"[ollama serve] pid {p.pid} up+model loaded in {dt}s"); return p, dt
def ol_stop(p):
    p.send_signal(signal.SIGTERM)
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    time.sleep(3); log("[ollama serve] stopped", p.returncode)
def ol_chat(messages, name):
    body = {"model": MODEL, "stream": True, "keep_alive": -1, "messages": messages,
            "options": {"num_predict": MAXTOK, "num_ctx": NC, "num_gpu": 999, "temperature": 0, "seed": 1}}
    t0 = time.time(); ttft = None; content = ""; th = 0; fin = {}
    with urllib.request.urlopen(req(OH + "/api/chat", body), timeout=1800) as r:
        for raw in r:
            j = json.loads(raw)
            m = j.get("message") or {}
            if (m.get("content") or m.get("thinking")) and ttft is None: ttft = time.time() - t0
            content += m.get("content") or ""; th += len(m.get("thinking") or "")
            if j.get("done"): fin = j
    out = {"name": name, "ttft_s": round(ttft, 3) if ttft else None, "wall_s": round(time.time() - t0, 2),
           "prompt_n": fin.get("prompt_eval_count"), "prompt_s": round(fin.get("prompt_eval_duration", 0) / 1e9, 3),
           "load_s": round(fin.get("load_duration", 0) / 1e9, 3), "gen_n": fin.get("eval_count"),
           "content": content, "thinking_chars": th, "score": score(content)}
    log(json.dumps(out)); return out
# ---------- exo ----------
EX = "http://127.0.0.1:52415"
def ex_state(): return call(EX + "/state", timeout=20)
def ex_place():
    t0 = time.time()
    log("place", call(EX + "/place_instance", {"model_id": MODEL, "sharding": "Pipeline", "instance_meta": "MlxRing", "min_nodes": 1}))
    iid = None
    while time.time() - t0 < 900:
        s = ex_state()
        for k, v in s["instances"].items():
            if v[next(iter(v))]["shardAssignments"]["modelId"] == MODEL: iid = k
        if iid:
            inst = s["instances"][iid]; rids = list(inst[next(iter(inst))]["shardAssignments"]["runnerToShard"])
            kinds = [next(iter(s["runners"].get(r, {"none": 0}))) for r in rids]
            if kinds and all(k == "RunnerReady" for k in kinds): break
            if any("Fail" in k for k in kinds): raise SystemExit(f"runner failed {kinds}")
        time.sleep(1)
    dt = round(time.time() - t0, 1); log(f"[exo] instance {iid} ready in {dt}s"); return iid, dt
def ex_delete(iid):
    log("delete", call(EX + f"/instance/{iid}", method="DELETE"))
    for _ in range(60):
        s = ex_state()
        if iid not in s["instances"] and not s["runners"]: break
        time.sleep(2)
    time.sleep(5)
def ex_chat(messages, name):
    body = {"model": MODEL, "messages": messages, "max_tokens": MAXTOK, "temperature": 0, "seed": 1, "stream": True, "stream_options": {"include_usage": True}}
    t0 = time.time(); ttft = None; content = ""; th = 0; usage = {}
    with urllib.request.urlopen(req(EX + "/v1/chat/completions", body), timeout=3600) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:"): continue
            d = line[5:].strip()
            if d == "[DONE]": break
            j = json.loads(d)
            if j.get("usage"): usage = j["usage"]
            for c in j.get("choices") or []:
                dl = c.get("delta") or {}; rc = dl.get("reasoning_content") or dl.get("reasoning") or ""
                if ((dl.get("content") or "") + rc) and ttft is None: ttft = time.time() - t0
                content += dl.get("content") or ""; th += len(rc)
    out = {"name": name, "ttft_s": round(ttft, 3) if ttft else None, "wall_s": round(time.time() - t0, 2),
           "prompt_n": usage.get("prompt_tokens"), "gen_n": usage.get("completion_tokens"),
           "content": content, "thinking_chars": th, "score": score(content)}
    log(json.dumps(out)); return out
# ---------- conversation (identical to caravan_bench.py) ----------
lines = filler(int(16000 / TPL)); lines.insert(len(lines) // 3, NEEDLE)
u1 = "Here is a long inventory log.\n" + "\n".join(lines) + "\n\nWhat is the vault access code? Answer in one short line." + NO_THINK
u2 = "What is 17 multiplied by 23? Answer in one short line." + NO_THINK
u3 = "What is the capital of Australia? Answer in one short line." + NO_THINK
rr = {"runtime": RT, "model": MODEL}
chat = ol_chat if RT == "ollama" else ex_chat
if RT == "ollama": p, rr["start_s"] = ol_serve()
else:
    for k in list(ex_state()["instances"]): ex_delete(k)
    iid, rr["start_s"] = ex_place()
try:
    m = [{"role": "user", "content": u1}]
    rr["t1_cold"] = chat(m, "t1_cold"); m.append({"role": "assistant", "content": rr["t1_cold"]["content"]})
    m.append({"role": "user", "content": u2})
    rr["t2_warm_in_memory"] = chat(m, "t2_warm_in_memory"); m.append({"role": "assistant", "content": rr["t2_warm_in_memory"]["content"]})
    if RT == "ollama": ol_stop(p); p, rr["restart_s"] = ol_serve()
    else: ex_delete(iid); iid, rr["restart_s"] = ex_place()
    m.append({"role": "user", "content": u3})
    rr["t3_resume_after_restart"] = chat(m, "t3_resume_after_restart")
finally:
    json.dump(rr, open(B / "results.json", "w"), indent=1)
    if RT == "ollama": ol_stop(p)
    else:
        try: ex_delete(iid)
        except Exception as e: log("delete err", e)
log("DONE", RT, TAG)
