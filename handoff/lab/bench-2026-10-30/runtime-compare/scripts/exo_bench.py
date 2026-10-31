"""usage: exo_bench.py <tag> <model_id> <max_tokens>
Assumes an exo instance for <model_id> is RunnerReady on this node (API 127.0.0.1:52415).
Streaming /v1/chat/completions: TTFT (prefill) + decode rate between first and last token.
Cross-check + peak memory via /bench/chat/completions generation_stats. 3 reps, median."""
import json, os, sys, time, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); from common import *
TAG, MODEL, MAXTOK = sys.argv[1], sys.argv[2], int(sys.argv[3])
PHASES = (sys.argv[4] if len(sys.argv) > 4 else "main,quality,d16k").split(",")
NO_THINK = os.environ.get("NO_THINK", ""); API = "http://127.0.0.1:52415"
OUT = Path.home() / ".caravan/bench-2026-10-30/runtime-compare/exo" / TAG; OUT.mkdir(parents=True, exist_ok=True)
LOG = open(OUT / "run.log", "a")
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
EXTRA = json.loads(os.environ.get("EXTRA_BODY", "{}"))
def body(content, max_tokens, **kw):
    b = {"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens, "temperature": 0, "seed": 1}
    b.update(EXTRA); b.update(kw); return b
def stream(content, max_tokens, name):
    b = body(content, max_tokens, stream=True, stream_options={"include_usage": True})
    req = urllib.request.Request(API + "/v1/chat/completions", json.dumps(b).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); tf = tl = None; nchunks = 0; usage = None; text = ""
    with urllib.request.urlopen(req, timeout=3600) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:"): continue
            data = line[5:].strip()
            if data == "[DONE]": break
            j = json.loads(data)
            if j.get("usage"): usage = j["usage"]
            for c in j.get("choices") or []:
                d = c.get("delta") or {}
                piece = (d.get("content") or "") + (d.get("reasoning_content") or d.get("reasoning") or "")
                if piece:
                    now = time.time(); tf = tf or now; tl = now; nchunks += 1; text += piece
    ttft = (tf - t0) if tf else None
    pt = (usage or {}).get("prompt_tokens"); ct = (usage or {}).get("completion_tokens") or nchunks
    out = {"name": name, "ttft_s": round(ttft, 3) if ttft else None, "wall_s": round(time.time() - t0, 2), "prompt_n": pt,
           "prompt_tps": round(pt / ttft, 1) if pt and ttft else None, "gen_n": ct, "chunks": nchunks,
           "gen_tps": round((ct - 1) / (tl - tf), 1) if tf and tl and tl > tf and ct > 1 else None}
    log(json.dumps(out)); return out
def bench(content, max_tokens, name):
    b = body(content, max_tokens)
    req = urllib.request.Request(API + "/bench/chat/completions", json.dumps(b).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); r = json.load(urllib.request.urlopen(req, timeout=3600))
    gs = r.get("generation_stats") or {}; msg = r["choices"][0].get("message", {})
    out = {"name": name, "wall_s": round(time.time() - t0, 2), "prompt_n": gs.get("prompt_tokens"), "prompt_tps": round(gs.get("prompt_tps", 0), 1),
           "gen_n": gs.get("generation_tokens"), "gen_tps": round(gs.get("generation_tps", 0), 1),
           "peak_mem_gb": round((gs.get("peak_memory_usage") or {}).get("inBytes", 0) / 1e9, 2), "prefix_cache_hit": gs.get("prefix_cache_hit"),
           "power": r.get("power_usage")}
    log(json.dumps(out)); return out, msg
def chat(content, name):
    b = body(content + NO_THINK, MAXTOK)
    req = urllib.request.Request(API + "/v1/chat/completions", json.dumps(b).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); r = json.load(urllib.request.urlopen(req, timeout=3600)); dt = time.time() - t0
    m = r["choices"][0]["message"]; txt = m.get("content") or ""
    rc = m.get("reasoning_content") or m.get("reasoning") or ""
    out = {"name": name, "wall_s": round(dt, 2), "usage": r.get("usage"), "finish": r["choices"][0].get("finish_reason"),
           "content": txt, "reasoning": rc[:300], "reasoning_chars": len(rc), "score": score(txt)}
    log(json.dumps(out)); return out
# token calibration: chars->tokens via usage on a 200-line filler
def calib():
    o = stream(f"[calib {uuid.uuid4().hex[:8]}]\n" + "\n".join(filler(200)), 1, "calib200")
    o2 = stream(f"[calib0 {uuid.uuid4().hex[:8]}]\nhi", 1, "calib_overhead")
    return (o["prompt_n"] - o2["prompt_n"]) / 200.0, o2["prompt_n"]
def sized(ntok, tpl, ovh, tag, off=0):
    return f"[{tag}]\n" + "\n".join(filler(max(1, int(round((ntok - ovh - 8) / tpl))), off))
TG_PROMPT = "Write the numbers from 1 to 1000 in words, separated by commas: one, two, three,"
res = json.load(open(OUT / "results.json")) if (OUT / "results.json").exists() else {}
def save(): json.dump(res, open(OUT / "results.json", "w"), indent=1)
with MemSampler(OUT / "mem.log", "EXO.app/Contents/Resources/exo/exo") as ms:
    if "main" in PHASES:
        stream("Hello", 1, "warm")
        tpl, ovh = calib(); log(f"tokens/line {tpl:.2f} overhead {ovh}")
        r = {"tok_per_line": tpl, "template_overhead": ovh, "runs": {}}
        for n in (512, 4096):
            rs = [stream(sized(n, tpl, ovh, f"pp{n} rep{i} {uuid.uuid4().hex[:6]}"), 1, f"pp{n}_r{i}") for i in range(3)]
            r["runs"][f"pp{n}"] = rs; r[f"pp{n}"] = med([x["prompt_tps"] for x in rs]); r[f"pp{n}_ntok"] = med([x["prompt_n"] for x in rs])
            r["runs"][f"pp{n}_bench"] = bench(sized(n, tpl, ovh, f"pp{n} bench {uuid.uuid4().hex[:6]}"), 1, f"pp{n}_bench")[0]
        rs = [stream(f"[tg {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT, 128, f"tg128_r{i}") for i in range(3)]
        r["runs"]["tg128"] = rs; r["tg128"] = med([x["gen_tps"] for x in rs]); r["tg128_ntok"] = med([x["gen_n"] for x in rs])
        r["runs"]["tg128_bench"] = bench(f"[tg bench {uuid.uuid4().hex[:6]}] " + TG_PROMPT, 128, "tg128_bench")[0]
        res["main"] = r; save()
    if "quality" in PHASES:
        P = prompts(); res["quality"] = {k: chat(v, k) for k, v in P.items()}
        res["quality2"] = {k: chat(v, k + "_repeat") for k, v in P.items()}; save()
    if "d16k" in PHASES:
        tpl, ovh = res.get("main", {}).get("tok_per_line") or calib()[0], res.get("main", {}).get("template_overhead", 20)
        A = sized(16384, tpl, ovh, "depth base")
        r = {"prime": stream(A, 1, "prime_16k"), "runs": [], "bench": []}
        for i in range(3):
            B = "\n" + "\n".join(filler(max(1, int(round(512 / tpl))), 400 + 50 * i)) + f"\n[rep {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT
            r["runs"].append(stream(A + B, 128, f"d16k_r{i}"))
        B = "\n" + "\n".join(filler(max(1, int(round(512 / tpl))), 700)) + f"\n[bench {uuid.uuid4().hex[:6]}] " + TG_PROMPT
        r["bench"].append(bench(A + B, 128, "d16k_bench")[0])
        r["ttft_d16k"] = med([x["ttft_s"] for x in r["runs"]]); r["tg128_d16k"] = med([x["gen_tps"] for x in r["runs"]])
        res["d16k"] = r; save()
res["mem_" + "_".join(PHASES)] = ms.summary(); save(); log("mem", ms.summary()); log("DONE", TAG)
