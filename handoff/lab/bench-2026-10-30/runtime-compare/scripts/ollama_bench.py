"""usage: ollama_bench.py <tag> <ollama_model> <max_tokens> [phases]
phases: any of f16,q8,d16k (default all). Starts/stops its own `ollama serve` per KV type.
Measures via /api/generate timing fields (prompt_eval_*, eval_*). 3 reps, median."""
import json, os, signal, subprocess, sys, time, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); from common import *
TAG, MODEL, MAXTOK = sys.argv[1], sys.argv[2], int(sys.argv[3])
PHASES = (sys.argv[4] if len(sys.argv) > 4 else "f16,q8,d16k").split(",")
NO_THINK = os.environ.get("NO_THINK", "")
OL = str(Path.home() / "ollama-bench" / "ollama")
OUT = Path.home() / ".caravan/bench-2026-10-30/runtime-compare/ollama" / TAG; OUT.mkdir(parents=True, exist_ok=True)
LOG = open(OUT / "run.log", "a")
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
def post(path, body, timeout=1800):
    req = urllib.request.Request("http://127.0.0.1:11434" + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t = time.time(); r = json.load(urllib.request.urlopen(req, timeout=timeout)); return r, time.time() - t
def serve(kv):
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_FLASH_ATTENTION="1", OLLAMA_KV_CACHE_TYPE=kv,
               OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_KEEP_ALIVE="-1", OLLAMA_NOPRUNE="1")
    p = subprocess.Popen([OL, "serve"], stdout=open(OUT / f"serve-{kv}.log", "a"), stderr=subprocess.STDOUT, env=env)
    for _ in range(60):
        try: urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2); break
        except Exception: time.sleep(1)
    log(f"[serve {kv}] pid {p.pid}"); return p
def stop(p):
    p.send_signal(signal.SIGTERM)
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    time.sleep(3); log(f"[serve] stopped rc={p.returncode}")
def gen(prompt, n_predict, num_ctx, name):
    body = {"model": MODEL, "prompt": prompt, "raw": True, "stream": False, "keep_alive": -1,
            "options": {"num_predict": n_predict, "num_ctx": num_ctx, "num_gpu": 999, "temperature": 0, "seed": 1}}
    r, dt = post("/api/generate", body)
    out = {"name": name, "wall_s": round(dt, 2), "load_s": round(r.get("load_duration", 0) / 1e9, 2),
           "prompt_n": r.get("prompt_eval_count"), "prompt_tps": round(r["prompt_eval_count"] / r["prompt_eval_duration"] * 1e9, 1) if r.get("prompt_eval_duration") else None,
           "gen_n": r.get("eval_count"), "gen_tps": round(r["eval_count"] / r["eval_duration"] * 1e9, 1) if r.get("eval_duration") else None}
    log(json.dumps(out)); return out
def text_of(lines_needed, off=0): return "\n".join(filler(lines_needed, off))
def calib(num_ctx):
    r = gen(f"[calib {uuid.uuid4().hex[:8]}]\n" + text_of(200), 1, num_ctx, "calib200")
    return r["prompt_n"] / 200.0
def sized(ntok, tpl, tag, off=0):
    return f"[{tag}]\n" + text_of(max(1, int(round((ntok - 12) / tpl))), off)
def chat(content, name, num_ctx=8192):
    body = {"model": MODEL, "stream": False, "keep_alive": -1, "messages": [{"role": "user", "content": content + NO_THINK}],
            "options": {"num_predict": MAXTOK, "num_ctx": num_ctx, "num_gpu": 999, "temperature": 0, "seed": 1}}
    body.update(json.loads(os.environ.get("EXTRA_BODY", "{}")))
    r, dt = post("/api/chat", body)
    msg = r.get("message", {}); txt = msg.get("content", "")
    out = {"name": name, "wall_s": round(dt, 2), "prompt_n": r.get("prompt_eval_count"),
           "prompt_tps": round(r["prompt_eval_count"] / r["prompt_eval_duration"] * 1e9, 1) if r.get("prompt_eval_duration") else None,
           "gen_n": r.get("eval_count"), "gen_tps": round(r["eval_count"] / r["eval_duration"] * 1e9, 1) if r.get("eval_duration") else None,
           "done_reason": r.get("done_reason"), "content": txt, "thinking": (msg.get("thinking") or "")[:300],
           "thinking_chars": len(msg.get("thinking") or ""), "score": score(txt)}
    log(json.dumps(out)); return out
TG_PROMPT = "Write the numbers from 1 to 1000 in words, separated by commas: one, two, three,"
res = json.load(open(OUT / "results.json")) if (OUT / "results.json").exists() else {}
def save(): json.dump(res, open(OUT / "results.json", "w"), indent=1)
for kv, ph in (("f16", "f16"), ("q8_0", "q8")):
    if ph not in PHASES: continue
    p = serve(kv)
    try:
        with MemSampler(OUT / f"mem-{ph}.log", "ollama-bench/") as ms:
            w = gen("Hello", 1, 8192, "warm_load"); tpl = calib(8192); log(f"tokens/line {tpl:.2f}")
            r = {"load_s": w["load_s"], "tok_per_line": tpl, "runs": {}}
            for n in (512, 4096):
                rs = [gen(sized(n, tpl, f"pp{n} {ph} rep{i} {uuid.uuid4().hex[:6]}"), 1, 8192, f"pp{n}_r{i}") for i in range(3)]
                r["runs"][f"pp{n}"] = rs; r[f"pp{n}"] = med([x["prompt_tps"] for x in rs]); r[f"pp{n}_ntok"] = med([x["prompt_n"] for x in rs])
            rs = [gen(f"[tg {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT, 128, 8192, f"tg128_r{i}") for i in range(3)]
            r["runs"]["tg128"] = rs; r["tg128"] = med([x["gen_tps"] for x in rs]); r["tg128_ntok"] = med([x["gen_n"] for x in rs])
            P = prompts(); r["quality"] = {k: chat(v, f"{ph}_{k}") for k, v in P.items()}
        r["mem"] = ms.summary(); log(ph, "mem", r["mem"])
        ps = urllib.request.urlopen("http://127.0.0.1:11434/api/ps").read().decode(); r["api_ps"] = json.loads(ps); log("ps", ps)
        res[ph] = r; save()
    finally:
        stop(p)
if "d16k" in PHASES:
    p = serve("q8_0")
    try:
        with MemSampler(OUT / "mem-d16k.log", "ollama-bench/") as ms:
            NC = 18432
            w = gen("Hello", 1, NC, "warm_load_18k"); tpl = calib(NC)
            A = sized(16384, tpl, "depth base")
            a = gen(A, 1, NC, "prime_16k"); r = {"prime": a, "runs": []}
            for i in range(3):
                B = "\n" + text_of(max(1, int(round(512 / tpl))), 400 + 50 * i) + f"\n[rep {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT
                r["runs"].append(gen(A + B, 128, NC, f"d16k_r{i}"))
            r["pp512_d16k"] = med([x["prompt_tps"] for x in r["runs"]]); r["tg128_d16k"] = med([x["gen_tps"] for x in r["runs"]])
            r["pp_ntok"] = med([x["prompt_n"] for x in r["runs"]])
        r["mem"] = ms.summary(); log("d16k mem", r["mem"])
        ps = urllib.request.urlopen("http://127.0.0.1:11434/api/ps").read().decode(); r["api_ps"] = json.loads(ps)
        res["d16k"] = r; save()
    finally:
        stop(p)
log("DONE", TAG)
