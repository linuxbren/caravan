"""usage: mlx_bench.py <tag> <mlx model id> <max_tokens> [phases]
MLX step (a) end-to-end: mlx_lm.server (venv ~/.caravan/venvs/mlx, local copy from ~/.exo/models,
command built by caravan-improvements agent/mlx_backend.py) on TEST port 8192, behind the improved
slot_pin_proxy on TEST port 8190 (llama upstream 8180 not running). Everything goes THROUGH the proxy.
phases: main (pp512/pp4096/tg128), quality, resume (4k 3-turn chat, restart server+proxy before t3).
pp here = prompt_tokens / wall of a max_tokens=1 non-streamed chat (includes 1 decode step + HTTP);
tg = (completion_tokens - 1) / (wall - TTFT) of a streamed 128-token chat."""
import json, os, signal, socket, subprocess, sys, time, urllib.request, urllib.error, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); from common import *
TAG, MODEL, MAXTOK = sys.argv[1], sys.argv[2], int(sys.argv[3])
PHASES = (sys.argv[4] if len(sys.argv) > 4 else "main,quality,resume").split(",")
NO_THINK = os.environ.get("NO_THINK", "")
CDIR = Path(os.environ.get("CARAVAN_DIR", str(Path.home() / "dev/caravan-improvements"))).expanduser()
B = Path.home() / ".caravan/bench-2026-10-30/improvements" / TAG; B.mkdir(parents=True, exist_ok=True)
os.environ["CARAVAN_CONFIG"] = str(B / "no-config.json")
sys.path.insert(0, str(CDIR / "agent"))
import mlx_backend  # noqa
MP, PP, LP = 8192, 8190, 8180
PX = f"http://127.0.0.1:{PP}"
LOG = open(B / "run.log", "a")
def log(*a):
    s = time.strftime("%T ") + " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
def port_open(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0
def wait(cond, proc, limit, what):
    t = time.time()
    while time.time() - t < limit:
        if proc.poll() is not None: raise SystemExit(f"{what} exited rc={proc.returncode}")
        try:
            if cond(): return time.time() - t
        except Exception: pass
        time.sleep(0.5)
    raise SystemExit(f"{what} timeout")
def models_ok():
    return urllib.request.urlopen(f"http://127.0.0.1:{MP}/v1/models", timeout=2).status == 200
NSTART = [0]
def start():
    for port in (MP, PP):
        if port_open(port): raise SystemExit(f"port {port} busy -- refusing to start")
    cmd = mlx_backend.build_mlx_command(MODEL, {}, {"port": MP})
    NSTART[0] += 1; n = NSTART[0]; log("mlx cmd:", " ".join(cmd))
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=open(B / f"mlx-server-{n}.log", "w"), stderr=subprocess.STDOUT)
    hs = wait(models_ok, p, 600, "mlx_lm.server")
    env = dict(os.environ, CARAVAN_PROXY_PORT=str(PP), CARAVAN_UPSTREAM_PORT=str(LP), CARAVAN_MLX_PORT=str(MP),
               CARAVAN_N_SLOTS="1", CARAVAN_SLOT_SAVE_DIR=str(B / "slots"), CARAVAN_PROXY_STATE_FILE=str(B / "session_slots.json"),
               CARAVAN_SLOT_CLEANUP="off")
    (B / "slots").mkdir(exist_ok=True)
    px = subprocess.Popen(["/opt/homebrew/bin/python3", "-u", str(CDIR / "proxy/slot_pin_proxy.py")],
                          stdout=open(B / f"proxy-{n}.log", "w"), stderr=subprocess.STDOUT, env=env)
    wait(lambda: port_open(PP), px, 30, "proxy")
    log(f"start #{n}: mlx ready {hs:.1f}s, total {time.time()-t0:.1f}s; pids {p.pid}/{px.pid}")
    return p, px, round(time.time() - t0, 1)
def stop(p, name):
    if p.poll() is None:
        p.send_signal(signal.SIGTERM)
        try: p.wait(60)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
    log(f"[{name}] stopped rc={p.returncode}")
def chat(messages, name, max_tokens=None, stream=True):
    body = {"model": MODEL, "temperature": 0, "seed": 1, "max_tokens": max_tokens or MAXTOK, "messages": messages, "stream": stream}
    if stream: body["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(PX + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); ttft = None; content = ""; reasoning = ""; usage = {}; finish = None; nchunks = 0
    try: r0 = urllib.request.urlopen(req, timeout=3600)
    except urllib.error.HTTPError as e:
        log(f"HTTP {e.code} from proxy for {name}: {e.read()[:500]!r}"); raise
    with r0 as r:
        if not stream:
            j = json.load(r); usage = j.get("usage") or {}
            c = (j.get("choices") or [{}])[0]; m = c.get("message") or {}
            content = m.get("content") or ""; reasoning = m.get("reasoning") or m.get("reasoning_content") or ""; finish = c.get("finish_reason")
        else:
            for raw in r:
                line = raw.decode().strip()
                if not line.startswith("data:"): continue
                d = line[5:].strip()
                if d == "[DONE]": break
                j = json.loads(d)
                if j.get("usage"): usage = j["usage"]
                for c in j.get("choices") or []:
                    dl = c.get("delta") or {}
                    rc = dl.get("reasoning") or dl.get("reasoning_content") or ""
                    piece = (dl.get("content") or "") + rc
                    if piece:
                        nchunks += 1
                        if ttft is None: ttft = time.time() - t0
                    content += dl.get("content") or ""; reasoning += rc
                    finish = c.get("finish_reason") or finish
    wall = time.time() - t0
    gen_n = usage.get("completion_tokens") or nchunks
    out = {"name": name, "ttft_s": round(ttft, 3) if ttft else None, "wall_s": round(wall, 2),
           "prompt_n": usage.get("prompt_tokens"), "gen_n": gen_n, "finish": finish,
           "content": content, "reasoning_chars": len(reasoning), "score": score(content)}
    if stream and ttft and gen_n and gen_n > 1 and wall > ttft: out["gen_tps"] = round((gen_n - 1) / (wall - ttft), 1)
    if not stream and usage.get("prompt_tokens"): out["prompt_tps"] = round(usage["prompt_tokens"] / wall, 1)
    if stream and ttft and usage.get("prompt_tokens"): out["prompt_tps_ttft"] = round(usage["prompt_tokens"] / ttft, 1)
    log(json.dumps({k: v for k, v in out.items() if k != "content"} | {"content": content[:120]})); return out
def final_text(s):
    """What a client sends back as the assistant turn: gpt-oss on mlx_lm 0.32.2 returns raw harmony
    markup in content (no harmony reasoning parser), so keep only the final channel."""
    if "<|channel|>final<|message|>" in s: s = s.split("<|channel|>final<|message|>")[-1]
    for t in ("<|end|>", "<|return|>"): s = s.replace(t, "")
    return s.strip()
def text_of(n, off=0): return "\n".join(filler(n, off))
TG_PROMPT = "Write the numbers from 1 to 1000 in words, separated by commas: one, two, three,"
res = json.load(open(B / "results.json")) if (B / "results.json").exists() else {}
def save(): json.dump(res, open(B / "results.json", "w"), indent=1)
res["config"] = {"model": MODEL, "max_tokens": MAXTOK, "no_think": NO_THINK, "mlx_port": MP, "proxy_port": PP,
                 "caravan_commit": subprocess.run(["git", "-C", str(CDIR), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
                 "cmd": mlx_backend.build_mlx_command(MODEL, {}, {"port": MP})}
PAT = f"mlx_lm server.*--port {MP}"
p, px, res["start_s"] = start()
try:
    with MemSampler(B / "mem.log", PAT) as ms:
        if "main" in PHASES:
            chat([{"role": "user", "content": "Hello there, this is a warm-up request."}], "warm", 1, stream=False)
            c = chat([{"role": "user", "content": f"[calib {uuid.uuid4().hex[:8]}]\n" + text_of(200)}], "calib200", 1, stream=False)
            tpl = c["prompt_n"] / 200.0; log(f"tokens/line {tpl:.2f}"); r = {"tok_per_line": tpl, "runs": {}}
            for n in (512, 4096):
                rs = [chat([{"role": "user", "content": f"[pp{n} rep{i} {uuid.uuid4().hex[:6]}]\n" + text_of(max(1, int(round((n - 20) / tpl))))}],
                           f"pp{n}_r{i}", 1, stream=False) for i in range(3)]
                r["runs"][f"pp{n}"] = rs; r[f"pp{n}"] = med([x.get("prompt_tps") for x in rs]); r[f"pp{n}_ntok"] = med([x["prompt_n"] for x in rs])
            rs = [chat([{"role": "user", "content": f"[tg {i} {uuid.uuid4().hex[:6]}] " + TG_PROMPT + NO_THINK}], f"tg128_r{i}", 128) for i in range(3)]
            r["runs"]["tg128"] = rs; r["tg128"] = med([x.get("gen_tps") for x in rs]); res["main"] = r; save()
        if "quality" in PHASES:
            P = prompts(); res["quality"] = {k: chat([{"role": "user", "content": v + NO_THINK}], k) for k, v in P.items()}; save()
    res["mem"] = ms.summary(); log("mem", res["mem"]); save()
    if "resume" in PHASES:
        tpl = res.get("main", {}).get("tok_per_line") or float(os.environ.get("TPL", "23.5"))
        lines = filler(int(4000 / tpl)); lines.insert(len(lines) // 3, NEEDLE)
        u1 = "Here is a long inventory log.\n" + "\n".join(lines) + "\n\nWhat is the vault access code? Answer in one short line." + NO_THINK
        u2 = "What is 17 multiplied by 23? Answer in one short line." + NO_THINK
        u3 = "What is the capital of Australia? Answer in one short line." + NO_THINK
        rr = {}; m = [{"role": "user", "content": u1}]
        rr["t1_cold"] = chat(m, "t1_cold"); m.append({"role": "assistant", "content": final_text(rr["t1_cold"]["content"])})
        m.append({"role": "user", "content": u2})
        rr["t2_warm_in_memory"] = chat(m, "t2_warm_in_memory"); m.append({"role": "assistant", "content": final_text(rr["t2_warm_in_memory"]["content"])})
        stop(px, "proxy"); stop(p, "mlx")
        p, px, rr["restart_s"] = start()
        m.append({"role": "user", "content": u3})
        rr["t3_after_restart"] = chat(m, "t3_after_restart")
        rr["proxy_log"] = [l for n in range(1, NSTART[0] + 1) for l in open(B / f"proxy-{n}.log").read().splitlines()
                           if "mlx" in l][:20]
        log("proxy mlx log", rr["proxy_log"]); res["resume"] = rr; save()
finally:
    stop(px, "proxy"); stop(p, "mlx")
log("DONE", TAG)
