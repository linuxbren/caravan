"""usage: localai_bench.py <tag> <short> <max_tokens> [phases]
LocalAI (native darwin-arm64 binary, llama-cpp backend) on EXO1. Server started/stopped by this script on 127.0.0.1:8081.
Models: <short>-f16 (ctx 8192, f16 KV) for main+quality; <short>-q8-16k (ctx 18432, q8_0 KV) for d16k+resume.
Measured via LocalAI's OpenAI API with the 'Extra-Usage' header -> usage.timing_prompt_processing / timing_token_generation (ms, from llama.cpp timings)."""
import json, os, signal, subprocess, sys, time, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); from common import *
TAG, SHORT, MAXTOK = sys.argv[1], sys.argv[2], int(sys.argv[3])
PHASES = (sys.argv[4] if len(sys.argv) > 4 else "main,quality,d16k,resume").split(",")
NO_THINK = os.environ.get("NO_THINK", "")
LA = Path.home() / "localai-bench"
B = Path.home() / ".caravan/bench-2026-10-30/runtime-compare/localai" / TAG; B.mkdir(parents=True, exist_ok=True)
LOG = open(B / "run.log", "a")
def log(*a):
    s = time.strftime("%T ") + " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
URL = "http://127.0.0.1:8081"
M_MAIN, M_16K = f"{SHORT}-f16", f"{SHORT}-q8-16k"
def post(path, body, timeout=1800):
    req = urllib.request.Request(URL + path, json.dumps(body).encode(), {"Content-Type": "application/json", "Extra-Usage": "1"})
    t = time.time(); r = json.load(urllib.request.urlopen(req, timeout=timeout)); return r, time.time() - t
NSTART = [0]
def start():
    NSTART[0] += 1; n = NSTART[0]
    cmd = [str(LA / "local-ai"), "run", "--models-path", str(LA / "models"), "--backends-path", str(LA / "backends"),
           "--data-path", str(LA / "data"), "--localai-config-dir", str(LA / "config"), "--address", "127.0.0.1:8081",
           "--max-active-backends", "1", "--autoload-galleries=false", "--log-level", "debug"]
    log("server cmd:", " ".join(cmd)); t0 = time.time()
    p = subprocess.Popen(cmd, cwd=str(LA), env=dict(os.environ, DOCKER_CONFIG=str(LA / "docker-cfg")), stdout=open(B / f"server-{n}.log", "w"), stderr=subprocess.STDOUT)
    while time.time() - t0 < 180:
        if p.poll() is not None: raise SystemExit(f"local-ai exited rc={p.returncode}")
        try:
            if urllib.request.urlopen(URL + "/readyz", timeout=2).status == 200: break
        except Exception: pass
        time.sleep(0.5)
    else: raise SystemExit("readyz timeout")
    dt = round(time.time() - t0, 1); log(f"start #{n}: ready {dt}s pid {p.pid}"); return p, dt
def stop(p, name="local-ai"):
    if p.poll() is None:
        p.send_signal(signal.SIGTERM)
        try: p.wait(60)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
    time.sleep(2)
    left = subprocess.run(["pgrep", "-fl", "localai-bench"], capture_output=True, text=True).stdout.strip()
    log(f"[{name}] stopped rc={p.returncode}; leftover: {left!r}")
    if left:
        subprocess.run(["pkill", "-TERM", "-f", "localai-bench/backends"]); time.sleep(3)
import re
RX_P = re.compile(r"task (\d+) \| prompt eval time =\s*([\d.]+) ms /\s*(\d+) tokens")
RX_G = re.compile(r"task (\d+) \|        eval time =\s*([\d.]+) ms /\s*(\d+) tokens")
def llama_timing():
    time.sleep(0.5)
    t = open(B / f"server-{NSTART[0]}.log", errors="ignore").read()
    ps, gs = RX_P.findall(t), RX_G.findall(t)
    if not ps: return {}
    task, pms, pn = ps[-1]; g = [x for x in gs if x[0] == task]
    d = {"task": int(task), "prompt_ms": float(pms), "prompt_n": int(pn)}
    if g: d.update(gen_ms=float(g[-1][1]), gen_n=int(g[-1][2]))
    return d
def comp(model, prompt, max_tokens, name):
    body = {"model": model, "prompt": prompt, "max_tokens": max_tokens, "temperature": 0, "seed": 1}
    r, dt = post("/v1/completions", body); u = r.get("usage", {})
    pms, gms = u.get("timing_prompt_processing"), u.get("timing_token_generation"); lt = llama_timing(); pms = pms or lt.get("prompt_ms"); gms = gms or lt.get("gen_ms")
    pn, gn = lt.get("prompt_n"), lt.get("gen_n")
    out = {"name": name, "wall_s": round(dt, 2), "prompt_tokens": pn, "completion_tokens": gn, "usage_api": u, "llama_log": lt,
           "prompt_ms": pms, "gen_ms": gms,
           "prompt_tps": round(pn / pms * 1000, 1) if pms and pn else None,
           "gen_tps": round(gn / gms * 1000, 1) if gms and max_tokens > 1 and gn else None,
           "text": (r.get("choices") or [{}])[0].get("text", "")[:80]}
    log(json.dumps(out)); return out
def text_of(n, off=0): return "\n".join(filler(n, off))
def sized(ntok, tpl, tag, off=0): return f"[{tag}]\n" + text_of(max(1, int(round((ntok - 12) / tpl))), off)
def chat(model, messages, name):
    body = {"model": model, "temperature": 0, "seed": 1, "max_tokens": MAXTOK, "messages": messages, "stream": True,
            "stream_options": {"include_usage": True}}
    req = urllib.request.Request(URL + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json", "Extra-Usage": "1"})
    t0 = time.time(); ttft = None; content = ""; reasoning = ""; usage = {}; finish = None
    with urllib.request.urlopen(req, timeout=1800) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:"): continue
            d = line[5:].strip()
            if d == "[DONE]": break
            j = json.loads(d)
            if j.get("usage"): usage = j["usage"]
            for c in j.get("choices", []):
                dl = c.get("delta", {}) or {}
                rs = (dl.get("reasoning_content") or dl.get("reasoning") or "")
                piece = (dl.get("content") or "") + rs
                if piece and ttft is None: ttft = time.time() - t0
                content += dl.get("content") or ""; reasoning += rs
                finish = c.get("finish_reason") or finish
    wall = time.time() - t0; lt = llama_timing(); gms = lt.get("gen_ms")
    out = {"name": name, "ttft_s": round(ttft, 3) if ttft else None, "wall_s": round(wall, 2), "usage_api": usage, "llama_log": lt,
           "prompt_tokens_processed": lt.get("prompt_n"), "completion_tokens": lt.get("gen_n"),
           "prompt_ms": lt.get("prompt_ms"), "gen_ms": gms,
           "gen_tps": round(lt["gen_n"] / gms * 1000, 1) if gms and lt.get("gen_n") else None,
           "finish": finish, "content": content, "reasoning_chars": len(reasoning), "score": score(content)}
    log(json.dumps(out)); return out
TG_PROMPT = "Write the numbers from 1 to 1000 in words, separated by commas: one, two, three,"
res = json.load(open(B / "results.json")) if (B / "results.json").exists() else {}
def save(): json.dump(res, open(B / "results.json", "w"), indent=1)
res["config"] = {"short": SHORT, "max_tokens": MAXTOK, "no_think": NO_THINK, "phases": PHASES,
                 "yaml_main": open(LA / "models" / f"{M_MAIN}.yaml").read(), "yaml_16k": open(LA / "models" / f"{M_16K}.yaml").read()}
PAT = "localai-bench"
p, res["start_s"] = start()
try:
    with MemSampler(B / "mem.log", PAT) as ms:
        if "main" in PHASES:
            w = comp(M_MAIN, "Hello there, this is a warm-up request.", 1, "warm_incl_load")
            c = comp(M_MAIN, f"[calib {uuid.uuid4().hex[:8]}]\n" + text_of(200), 1, "calib200"); tpl = c["prompt_tokens"] / 200.0
            log(f"tokens/line {tpl:.2f}"); r = {"tok_per_line": tpl, "warm": w, "runs": {}}
            for n in (512, 4096):
                rs = [comp(M_MAIN, sized(n, tpl, f"pp{n} rep{i} {uuid.uuid4().hex[:6]}"), 1, f"pp{n}_r{i}") for i in range(3)]
                r["runs"][f"pp{n}"] = rs; r[f"pp{n}"] = med([x["prompt_tps"] for x in rs]); r[f"pp{n}_ntok"] = med([x["prompt_tokens"] for x in rs])
            rs = [comp(M_MAIN, f"[tg {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT, 128, f"tg128_r{i}") for i in range(3)]
            r["runs"]["tg128"] = rs; r["tg128"] = med([x["gen_tps"] for x in rs])
            res["main"] = r; save(); log("MAIN", {k: r[k] for k in ("pp512", "pp4096", "tg128")})
        if "quality" in PHASES:
            P = prompts(); res["quality"] = {k: chat(M_MAIN, [{"role": "user", "content": v + NO_THINK}], k) for k, v in P.items()}; save()
        res["mem_main"] = ms.summary(); log("mem main", res["mem_main"])
        if "d16k" in PHASES:
            tpl = res.get("main", {}).get("tok_per_line") or float(os.environ.get("TPL", "23.5"))
            comp(M_16K, "Hello there, this is a warm-up request.", 1, "warm16k_incl_load")
            A = sized(16384, tpl, "depth base"); a = comp(M_16K, A, 1, "prime_16k"); r = {"prime": a, "runs": []}
            for i in range(3):
                Bq = "\n" + text_of(max(1, int(round(512 / tpl))), 400 + 50 * i) + f"\n[rep {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT
                x = comp(M_16K, A + Bq, 128, f"d16k_r{i}")
                x["new_tokens_est"] = x["prompt_tokens"]
                x["pp_new_tps"] = round(x["new_tokens_est"] / x["prompt_ms"] * 1000, 1) if x["prompt_ms"] else None
                log("d16k est", x["new_tokens_est"], x["pp_new_tps"]); r["runs"].append(x)
            r["pp512_d16k"] = med([x["pp_new_tps"] for x in r["runs"]]); r["tg128_d16k"] = med([x["gen_tps"] for x in r["runs"]])
            r["new_ntok"] = med([x["new_tokens_est"] for x in r["runs"]]); res["d16k"] = r; save()
            log("D16K", r["pp512_d16k"], r["tg128_d16k"], r["new_ntok"])
    res["mem"] = ms.summary(); log("mem", res["mem"]); save()
    if "resume" in PHASES:
        tpl = res.get("main", {}).get("tok_per_line") or float(os.environ.get("TPL", "23.5"))
        lines = filler(int(16000 / tpl)); lines.insert(len(lines) // 3, NEEDLE)
        u1 = "Here is a long inventory log.\n" + "\n".join(lines) + "\n\nWhat is the vault access code? Answer in one short line." + NO_THINK
        u2 = "What is 17 multiplied by 23? Answer in one short line." + NO_THINK
        u3 = "What is the capital of Australia? Answer in one short line." + NO_THINK
        rr = {}
        comp(M_16K, "Hello there, this is a warm-up request.", 1, "warm_resume_incl_load")
        m = [{"role": "user", "content": u1}]
        rr["t1_cold"] = chat(M_16K, m, "t1_cold"); m.append({"role": "assistant", "content": rr["t1_cold"]["content"]})
        m.append({"role": "user", "content": u2})
        rr["t2_warm_in_memory"] = chat(M_16K, m, "t2_warm_in_memory"); m.append({"role": "assistant", "content": rr["t2_warm_in_memory"]["content"]})
        stop(p); p, rr["restart_s"] = start()
        t = time.time(); comp(M_16K, "Hello there, this is a warm-up request.", 1, "reload_after_restart"); rr["reload_s"] = round(time.time() - t, 1)
        m.append({"role": "user", "content": u3})
        rr["t3_resume_after_restart"] = chat(M_16K, m, "t3_resume_after_restart")
        res["resume"] = rr; save()
        log("RESUME", rr["t1_cold"]["ttft_s"], rr["t2_warm_in_memory"]["ttft_s"], rr["t3_resume_after_restart"]["ttft_s"])
finally:
    stop(p)
log("DONE", TAG)
