"""usage: ab_bench.py <tag> <mlx model id> [rounds] [reps] [variants]
Caravan v2.1 A/B (2026-10-31): alternate v1 / v2 / v2.1 (and v2.1 with
CARAVAN_MLX_SAVE_MIN_TURNS=2) in ONE session so day-to-day drift cancels.
Each round starts every variant fresh (server + proxy), in a rotated order,
then: warm-up, calib, pp512 x reps, pp4096 x reps (max_tokens=1, non-streamed,
back-to-back like bench/v2). Memory (rss/footprint/free%/swap) sampled every 2 s.
TEST ports only: mlx 8192, proxy 8190. Results: $BENCH_ROOT/<tag>/results.json."""
import json, os, re, signal, socket, subprocess, sys, time, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "improvements")); from common import MemSampler, filler, med
TAG, MODEL = sys.argv[1], sys.argv[2]
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
REPS = int(sys.argv[4]) if len(sys.argv) > 4 else 2
H = Path.home()
VARIANTS = {   # name: (caravan dir, extra proxy env)
    "v1": (H / "dev/caravan-improvements", {}),
    "v2": (H / "dev/caravan-v2", {}),
    "v2.1": (H / "dev/caravan-v2.1", {}),
    "v2.1-save2": (H / "dev/caravan-v2.1", {"CARAVAN_MLX_SAVE_MIN_TURNS": "2"}),
}
ORDER = (sys.argv[5].split(",") if len(sys.argv) > 5 else list(VARIANTS))
EXTRA = os.environ.get("CARAVAN_MLX_EXTRA_ARGS", "")
B = Path(os.environ.get("BENCH_ROOT", str(H / ".caravan/bench-2026-10-31/v2.1"))).expanduser() / TAG
B.mkdir(parents=True, exist_ok=True)
MP, PP, LP = 8192, 8190, 8180
LOG = open(B / "run.log", "a")
def log(*a):
    s = time.strftime("%T ") + " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
def port_open(port):
    with socket.socket() as s:
        s.settimeout(1); return s.connect_ex(("127.0.0.1", port)) == 0
def wait(cond, proc, limit, what):
    t = time.time()
    while time.time() - t < limit:
        if proc.poll() is not None: raise SystemExit(f"{what} exited rc={proc.returncode}")
        try:
            if cond(): return time.time() - t
        except Exception: pass
        time.sleep(0.5)
    raise SystemExit(f"{what} timeout")
def build_cmd(cdir):
    code = ("import sys,json; sys.path.insert(0, sys.argv[1]); import mlx_backend as m; "
            "print(json.dumps(m.build_mlx_command(sys.argv[2], {}, {'port': int(sys.argv[3])})))")
    out = subprocess.run(["/opt/homebrew/bin/python3", "-c", code, str(cdir / "agent"), MODEL, str(MP)],
                         capture_output=True, text=True, env=dict(os.environ, CARAVAN_MLX_EXTRA_ARGS=EXTRA))
    return json.loads(out.stdout)
def start(name, d):
    cdir, penv = VARIANTS[name]
    for port in (MP, PP):
        if port_open(port): raise SystemExit(f"port {port} busy -- refusing to start")
    cmd = build_cmd(cdir)
    log(f"[{name}] mlx cmd:", " ".join(cmd))
    t0 = time.time()
    env = dict(os.environ, CARAVAN_CONFIG=str(d / "no-config.json"), CARAVAN_MLX_CACHE_DIR=str(d / "mlx-cache"))
    p = subprocess.Popen(cmd, stdout=open(d / "mlx-server.log", "w"), stderr=subprocess.STDOUT, env=env)
    def ok(): return urllib.request.urlopen(f"http://127.0.0.1:{MP}/v1/models", timeout=2).status == 200
    hs = wait(ok, p, 600, "mlx server")
    penv = dict(env, CARAVAN_PROXY_PORT=str(PP), CARAVAN_UPSTREAM_PORT=str(LP), CARAVAN_MLX_PORT=str(MP),
                CARAVAN_N_SLOTS="1", CARAVAN_SLOT_SAVE_DIR=str(d / "slots"), CARAVAN_PROXY_STATE_FILE=str(d / "session_slots.json"),
                CARAVAN_SLOT_CLEANUP="off", **penv)
    (d / "slots").mkdir(exist_ok=True)
    px = subprocess.Popen(["/opt/homebrew/bin/python3", "-u", str(cdir / "proxy/slot_pin_proxy.py")],
                          stdout=open(d / "proxy.log", "w"), stderr=subprocess.STDOUT, env=penv)
    wait(lambda: port_open(PP), px, 30, "proxy")
    return p, px, cmd, round(hs, 1)
def stop(p):
    if p.poll() is None:
        p.send_signal(signal.SIGTERM)
        try: p.wait(90)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
def chat(text, name):
    body = {"model": MODEL, "temperature": 0, "seed": 1, "max_tokens": 1, "stream": False,
            "messages": [{"role": "user", "content": text}]}
    req = urllib.request.Request(f"http://127.0.0.1:{PP}/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r: j = json.load(r)
    wall = time.time() - t0; u = j.get("usage") or {}
    out = {"name": name, "t_start": round(t0, 3), "wall_s": round(wall, 3), "prompt_n": u.get("prompt_tokens"),
           "prompt_tps": round(u["prompt_tokens"] / wall, 1) if u.get("prompt_tokens") else None, "caravan": u.get("caravan")}
    cv = u.get("caravan") or {}
    if cv.get("prefill_s") and u.get("prompt_tokens"): out["prefill_tps"] = round(u["prompt_tokens"] / cv["prefill_s"], 1)
    log(json.dumps(out)); return out
SW = re.compile(r"used = ([\d.]+)M")
def mem_stats(path):
    rss, fp, free, sw = [], [], [], []
    for line in open(path):
        m = re.search(r"rss=([\d.]+)GB fp=([\d.]+)GB free=(\d+)%", line); s = SW.search(line)
        if m: rss.append(float(m[1])); fp.append(float(m[2])); free.append(int(m[3]))
        if s: sw.append(float(s[1]))
    return {"peak_rss_gb": max(rss, default=None), "median_rss_gb": med(rss), "peak_footprint_gb": max(fp, default=None),
            "min_free_pct": min(free, default=None), "swap_used_mb_min": min(sw, default=None), "swap_used_mb_max": max(sw, default=None)}
res = json.load(open(B / "results.json")) if (B / "results.json").exists() else {"model": MODEL, "sessions": []}
def save(): json.dump(res, open(B / "results.json", "w"), indent=1)
log(f"=== {TAG}: {MODEL} rounds={ROUNDS} reps={REPS} order={ORDER}")
for rnd in range(ROUNDS):
    order = ORDER[rnd % len(ORDER):] + ORDER[:rnd % len(ORDER)]
    for name in order:
        d = B / f"r{rnd}-{name}"; d.mkdir(exist_ok=True)
        p, px, cmd, hs = start(name, d)
        sess = {"variant": name, "round": rnd, "cmd": cmd, "ready_s": hs,
                "commit": subprocess.run(["git", "-C", str(VARIANTS[name][0]), "rev-parse", "--short", "HEAD"],
                                         capture_output=True, text=True).stdout.strip(), "runs": {}}
        pat = f"mlx_worker.py.*--port {MP}" if "mlx_worker.py" in " ".join(cmd) else f"mlx_lm server.*--port {MP}"
        try:
            with MemSampler(d / "mem.log", pat):
                chat("Hello there, this is a warm-up request.", "warm")
                c = chat(f"[calib {uuid.uuid4().hex[:8]}]\n" + "\n".join(filler(200)), "calib200")
                tpl = c["prompt_n"] / 200.0
                for n in (512, 4096):
                    t0 = time.time()
                    rs = [chat(f"[pp{n} r{rnd} {i} {uuid.uuid4().hex[:6]}]\n" + "\n".join(filler(max(1, int(round((n - 20) / tpl))))),
                               f"pp{n}_{i}") for i in range(REPS)]
                    sess["runs"][f"pp{n}"] = rs
                    sess[f"pp{n}_loop_s"] = round(time.time() - t0, 2)
                    sess[f"pp{n}_gap_s"] = round(time.time() - t0 - sum(x["wall_s"] for x in rs), 2)
                time.sleep(2)   # let the last save finish inside the sampler window
        finally:
            stop(px); stop(p)
        sess["mem"] = mem_stats(d / "mem.log")
        wl = [l.strip() for l in open(d / "mlx-server.log") if "wired" in l.lower()][:3]
        sess["wired_log"] = wl
        log(f"[{name}] r{rnd} done: mem {sess['mem']} wired {wl}")
        res["sessions"].append(sess); save()
        time.sleep(5)
summ = {}
for s in res["sessions"]:
    v = summ.setdefault(s["variant"], {"pp512": [], "pp4096": [], "pp512_prefill": [], "pp4096_prefill": [], "pp4096_gap": []})
    for n in ("pp512", "pp4096"):
        v[n] += [x["prompt_tps"] for x in s["runs"].get(n, [])]
        v[n + "_prefill"] += [x.get("prefill_tps") for x in s["runs"].get(n, [])]
    v["pp4096_gap"].append(s.get("pp4096_gap_s"))
res["summary"] = {k: {kk: (med(vv), vv) for kk, vv in v.items()} for k, v in summ.items()}
save(); log("summary", json.dumps({k: {kk: vv[0] for kk, vv in v.items()} for k, v in res["summary"].items()}))
log("ABDONE")
