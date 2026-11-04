"""usage: imp_bench.py <tag> <model.gguf> <max_tokens> <ubatch> <n_slots> <ctx_per_slot> [phases]
2026-10-30 improvements bench -- caravan_bench.py (the v0 bench) with knobs, on TEST ports
(llama-server :8180, proxy :8190; production 8080/8090, exo 52415 untouched):
  CARAVAN_DIR  caravan checkout whose supervisor/proxy is used (default ~/dev/caravan-improvements; v0 = ~/dev/caravan)
  LLAMA_BIN    dir with llama-server (default ~/dev/llama.cpp/build-rebase/bin; old = ~/dev/llama.cpp/build/bin)
  KV           q8_0 (v0 default) | auto (improvement 3; needs the improved CARAVAN_DIR) | f16
  SWA_FULL=1   append --swa-full
phases: main,quality,d16k,resume,resume_raw. Everything measured THROUGH the proxy."""
import json, os, signal, subprocess, sys, time, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, str(Path.home() / "dev/caravan-v3/bench/improvements")); from common import *
TAG, MODEL, MAXTOK, UB, NS, CPS = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
PHASES = (sys.argv[7] if len(sys.argv) > 7 else "main,quality,d16k,resume").split(",")
NO_THINK = os.environ.get("NO_THINK", "")
B = Path.home() / ".caravan/bench-2026-11-04/v19/v0" / TAG; B.mkdir(parents=True, exist_ok=True)
CDIR = Path(os.environ.get("CARAVAN_DIR", str(Path.home() / "dev/caravan-improvements"))).expanduser()
LBIN = Path(os.environ.get("LLAMA_BIN", str(Path.home() / "dev/llama.cpp/build-rebase/bin"))).expanduser()
KV = os.environ.get("KV", "q8_0"); SWA_FULL = os.environ.get("SWA_FULL") == "1"
LP, PP = 8194, 8190
SLOTS = B / "slots"; SLOTS.mkdir(exist_ok=True)
os.environ["CARAVAN_CONFIG"] = str(B / "no-config.json")  # nonexistent -> Caravan defaults + our overrides
os.environ["CARAVAN_GPU_WORKING_SET_MIB"] = os.environ.get("CARAVAN_GPU_WORKING_SET_MIB", "")
sys.path.insert(0, str(CDIR / "agent"))
import config, supervisor  # noqa
LOG = open(B / "run.log", "a")
def log(*a):
    s = time.strftime("%T ") + " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
PX = f"http://127.0.0.1:{PP}"; LL = f"http://127.0.0.1:{LP}"
import contextlib, io
KV_DECISION = [None]
def post(url, body, timeout=1800):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t = time.time(); r = json.load(urllib.request.urlopen(req, timeout=timeout)); return r, time.time() - t
def wait_health(port, proc, limit=300):
    t = time.time()
    while time.time() - t < limit:
        if proc.poll() is not None: raise SystemExit(f"process exited rc={proc.returncode}")
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).status == 200: return time.time() - t
        except Exception: pass
        time.sleep(0.5)
    raise SystemExit("health timeout")
NSTART = [0]
def start():
    s = config.resolve_llama_settings({"n_slots": NS, "ctx_per_slot": CPS, "ubatch_size": UB, "batch_size": max(2048, UB),
                                       "cache_type_k": KV, "cache_type_v": KV, "flash_attn": "on", "n_gpu_layers": "999"})
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        cmd = supervisor.build_head_command(MODEL, [], s)
    if err.getvalue().strip():
        KV_DECISION[0] = err.getvalue().strip(); log("kv decision:", KV_DECISION[0])
    i = cmd.index("--slot-save-path"); cmd[i + 1] = str(SLOTS) + "/"
    i = cmd.index("--port"); cmd[i + 1] = str(LP)
    cmd[0] = str(LBIN / "llama-server")
    if SWA_FULL and "--swa-full" not in cmd: cmd.append("--swa-full")
    NSTART[0] += 1; n = NSTART[0]
    log("server cmd:", " ".join(cmd))
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=open(B / f"server-{n}.log", "w"), stderr=subprocess.STDOUT)
    hs = wait_health(LP, p)
    env = dict(os.environ, CARAVAN_PROXY_PORT=str(PP), CARAVAN_UPSTREAM_PORT=str(LP), CARAVAN_N_SLOTS=str(NS), CARAVAN_SLOT_SAVE_DIR=str(SLOTS),
               CARAVAN_PROXY_STATE_FILE=str(B / "session_slots.json"), CARAVAN_SLOT_CLEANUP="off")
    px = subprocess.Popen(["/opt/homebrew/bin/python3", "-u", str(CDIR / "proxy/slot_pin_proxy.py")],
                          stdout=open(B / f"proxy-{n}.log", "w"), stderr=subprocess.STDOUT, env=env)
    wait_health(PP, px, 30)
    log(f"start #{n}: server ready {hs:.1f}s, proxy ready, total {time.time()-t0:.1f}s; pids {p.pid}/{px.pid}")
    return p, px, round(time.time() - t0, 1)
def stop(p, name):
    if p.poll() is None:
        p.send_signal(signal.SIGTERM)
        try: p.wait(60)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
    log(f"[{name}] stopped rc={p.returncode}")
def comp(prompt, n_predict, name):
    body = {"prompt": prompt, "n_predict": n_predict, "cache_prompt": True, "temperature": 0, "seed": 1}
    r, dt = post(PX + "/completion", body); t = r.get("timings", {})
    out = {"name": name, "wall_s": round(dt, 2), "prompt_n": t.get("prompt_n"), "cache_n": t.get("cache_n"),
           "prompt_tps": round(t["prompt_per_second"], 1) if t.get("prompt_per_second") else None,
           "gen_n": t.get("predicted_n"), "gen_tps": round(t["predicted_per_second"], 1) if t.get("predicted_per_second") and n_predict > 1 else None}
    log(json.dumps(out)); return out
def text_of(n, off=0): return "\n".join(filler(n, off))
def sized(ntok, tpl, tag, off=0): return f"[{tag}]\n" + text_of(max(1, int(round((ntok - 12) / tpl))), off)
def chat(messages, name, stream=True):
    body = {"model": "x", "temperature": 0, "seed": 1, "max_tokens": MAXTOK, "messages": messages, "stream": stream}
    if stream: body["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(PX + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); ttft = None; content = ""; reasoning = ""; timings = {}; usage = {}; finish = None
    with urllib.request.urlopen(req, timeout=1800) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:"): continue
            d = line[5:].strip()
            if d == "[DONE]": break
            j = json.loads(d)
            if j.get("timings"): timings = j["timings"]
            if j.get("usage"): usage = j["usage"]
            for c in j.get("choices", []):
                dl = c.get("delta", {})
                piece = (dl.get("content") or "") + (dl.get("reasoning_content") or "")
                if piece and ttft is None: ttft = time.time() - t0
                content += dl.get("content") or ""; reasoning += dl.get("reasoning_content") or ""
                finish = c.get("finish_reason") or finish
    out = {"name": name, "ttft_s": round(ttft, 3) if ttft else None, "wall_s": round(time.time() - t0, 2),
           "prompt_n": timings.get("prompt_n"), "cache_n": timings.get("cache_n"), "prompt_ms": timings.get("prompt_ms"),
           "prompt_tps": round(timings["prompt_per_second"], 1) if timings.get("prompt_per_second") else None,
           "gen_n": timings.get("predicted_n"), "gen_tps": round(timings["predicted_per_second"], 1) if timings.get("predicted_per_second") else None,
           "usage": usage, "finish": finish, "content": content, "reasoning_chars": len(reasoning), "score": score(content)}
    log(json.dumps({k: v for k, v in out.items() if k != "usage"})); return out
TG_PROMPT = "Write the numbers from 1 to 1000 in words, separated by commas: one, two, three,"
res = json.load(open(B / "results.json")) if (B / "results.json").exists() else {}
def save(): json.dump(res, open(B / "results.json", "w"), indent=1)
PAT = f"llama-server.*--port {LP}"
ver = subprocess.run([str(LBIN / "llama-server"), "--version"], capture_output=True, text=True)
p, px, _ = start()
res["config"] = {"model": MODEL, "n_slots": NS, "ctx_per_slot": CPS, "ubatch": UB, "batch": max(2048, UB), "kv": KV,
                 "kv_decision": KV_DECISION[0], "swa_full": SWA_FULL, "fa": "on", "ngl": 999, "max_tokens": MAXTOK,
                 "no_think": NO_THINK, "caravan_dir": str(CDIR), "llama_bin": str(LBIN),
                 "llama_version": (ver.stdout + ver.stderr).strip().splitlines()[-2:],
                 "caravan_commit": subprocess.run(["git", "-C", str(CDIR), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()}
def server_evidence(n):
    pat = ("checkpoint", "restor", "n_past", "cache", "re-process", "reprocess", "SWA", "prompt processing", "n_tokens")
    return [l.strip()[:300] for l in open(B / f"server-{n}.log", errors="replace").read().splitlines()
            if any(k in l for k in pat) and "llama_kv_cache" not in l][-40:]
try:
    with MemSampler(B / "mem.log", PAT) as ms:
        if "main" in PHASES:
            comp("Hello there, this is a warm-up request.", 1, "warm")
            c = comp(f"[calib {uuid.uuid4().hex[:8]}]\n" + text_of(200), 1, "calib200"); tpl = c["prompt_n"] / 200.0
            log(f"tokens/line {tpl:.2f}"); r = {"tok_per_line": tpl, "runs": {}}
            for n in (512, 4096):
                rs = [comp(sized(n, tpl, f"pp{n} rep{i} {uuid.uuid4().hex[:6]}"), 1, f"pp{n}_r{i}") for i in range(3)]
                r["runs"][f"pp{n}"] = rs; r[f"pp{n}"] = med([x["prompt_tps"] for x in rs]); r[f"pp{n}_ntok"] = med([x["prompt_n"] for x in rs])
            rs = [comp(f"[tg {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT, 128, f"tg128_r{i}") for i in range(3)]
            r["runs"]["tg128"] = rs; r["tg128"] = med([x["gen_tps"] for x in rs])
            res["main"] = r; save()
        if "quality" in PHASES:
            P = prompts(); res["quality"] = {k: chat([{"role": "user", "content": v + NO_THINK}], k, stream=True) for k, v in P.items()}; save()
        if "d16k" in PHASES:
            tpl = res.get("main", {}).get("tok_per_line") or float(os.environ.get("TPL", "23.5"))
            A = sized(16384, tpl, "depth base"); a = comp(A, 1, "prime_16k"); r = {"prime": a, "runs": []}
            for i in range(3):
                Bq = "\n" + text_of(max(1, int(round(512 / tpl))), 400 + 50 * i) + f"\n[rep {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT
                r["runs"].append(comp(A + Bq, 128, f"d16k_r{i}"))
            r["pp512_d16k"] = med([x["prompt_tps"] for x in r["runs"]]); r["tg128_d16k"] = med([x["gen_tps"] for x in r["runs"]])
            r["new_ntok"] = med([x["prompt_n"] for x in r["runs"]]); res["d16k"] = r; save()
    res["mem"] = ms.summary(); log("mem", res["mem"]); save()
    if "resume" in PHASES:
        tpl = res.get("main", {}).get("tok_per_line") or float(os.environ.get("TPL", "23.5"))
        lines = filler(int(16000 / tpl)); lines.insert(len(lines) // 3, NEEDLE)
        u1 = "Here is a long inventory log.\n" + "\n".join(lines) + "\n\nWhat is the vault access code? Answer in one short line." + NO_THINK
        u2 = "What is 17 multiplied by 23? Answer in one short line." + NO_THINK
        u3 = "What is the capital of Australia? Answer in one short line." + NO_THINK
        rr = {}
        with MemSampler(B / "mem-resume.log", PAT) as ms2:
            m = [{"role": "user", "content": u1}]
            rr["t1_cold"] = chat(m, "t1_cold"); m.append({"role": "assistant", "content": rr["t1_cold"]["content"]})
            m.append({"role": "user", "content": u2})
            rr["t2_warm_in_memory"] = chat(m, "t2_warm_in_memory"); m.append({"role": "assistant", "content": rr["t2_warm_in_memory"]["content"]})
            time.sleep(2)
            rr["slot_files_after_t2"] = {f.name: f.stat().st_size for f in SLOTS.iterdir()}
            log("slot files", rr["slot_files_after_t2"])
        rr["mem"] = ms2.summary()
        # direct llama-server save/restore timing reference (bench file, removed at cleanup)
        try:
            sv, _ = post(LL + "/slots/0?action=save", {"filename": "bench-timing-ref.bin"}, 300)
            sl, _ = post(LL + "/slots/1?action=save", {"filename": "bench-timing-ref1.bin"}, 300) if NS > 1 else ({}, 0)
            rr["direct_save_slot0"] = sv; rr["direct_save_slot1"] = sl; log("direct save", sv, sl)
        except Exception as e: log("direct save err", e)
        stop(px, "proxy"); stop(p, "server")
        p, px, rr["restart_s"] = start()
        m.append({"role": "user", "content": u3})
        rr["t3_resume_after_restart"] = chat(m, "t3_resume_after_restart")
        # proxy log lines about restore
        rr["proxy_log_after_restart"] = [l for l in open(B / f"proxy-{NSTART[0]}.log").read().splitlines() if "restor" in l or "save" in l][:10]
        log("proxy restore log", rr["proxy_log_after_restart"])
        rr["server_log_after_restart"] = server_evidence(NSTART[0]); log("server evidence", rr["server_log_after_restart"])
        time.sleep(3)
        try:
            rs_, _ = post(LL + "/slots/%d?action=restore" % (NS - 1), {"filename": "bench-timing-ref.bin"}, 300)
            rr["direct_restore_ref"] = rs_; log("direct restore", rs_)
        except Exception as e: log("direct restore err", e)
        rr["slot_files_end"] = {f.name: f.stat().st_size for f in SLOTS.iterdir()}
        res["resume"] = rr; save()
    if "resume_raw" in PHASES:
        # prefix-exact resume (raw /completion, no chat template): prime 16k -> restart server+proxy -> same prefix + ~550 new tokens
        tpl = res.get("main", {}).get("tok_per_line") or float(os.environ.get("TPL", "23.5"))
        A = sized(16384, tpl, "resume raw base " + uuid.uuid4().hex[:6]); q = {}
        q["cold"] = comp(A, 1, "raw_cold_16k")
        Bq = "\n" + text_of(max(1, int(round(512 / tpl))), 900) + "\n[resume] " + TG_PROMPT
        q["warm_in_memory"] = comp(A + Bq, 1, "raw_warm_in_memory")
        time.sleep(2); stop(px, "proxy"); stop(p, "server")
        p, px, q["restart_s"] = start()
        Bq2 = "\n" + text_of(max(1, int(round(512 / tpl))), 1000) + "\n[resume2] " + TG_PROMPT
        q["after_restart"] = comp(A + Bq2, 1, "raw_after_restart")
        q["proxy_log"] = [l for l in open(B / f"proxy-{NSTART[0]}.log").read().splitlines() if "restor" in l or "cache=" in l][:10]
        log("raw proxy log", q["proxy_log"])
        q["server_log_after_restart"] = server_evidence(NSTART[0]); log("raw server evidence", q["server_log_after_restart"])
        res["resume_raw"] = q; save()
finally:
    stop(px, "proxy"); stop(p, "server")
log("DONE", TAG)
