"""usage: smoke.py <tag> <model.gguf> [max_tokens]
Caravan head-only smoke test (no --rpc) + KV quality check (q8_0 vs f16, short vs long)."""
import json, os, signal, subprocess, sys, time, urllib.request
from pathlib import Path
TAG, MODEL = sys.argv[1], sys.argv[2]
MAXTOK = int(sys.argv[3]) if len(sys.argv) > 3 else 200
B = Path.home() / ".caravan" / "bench-2026-10-30" / TAG
SLOTS = B / "slots"; SLOTS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path.home() / "dev" / "caravan" / "agent"))
os.environ["CARAVAN_CONFIG"] = str(B / "no-config.json")
import config, supervisor  # noqa
LOG = open(B / "smoke.log", "a")
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()

def post(url, body, timeout=900):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t = time.time(); r = json.load(urllib.request.urlopen(req, timeout=timeout)); return r, time.time() - t

def wait_health(port, proc, limit=300):
    t = time.time()
    while time.time() - t < limit:
        if proc.poll() is not None: raise SystemExit(f"process exited rc={proc.returncode}")
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).status == 200: return time.time() - t
        except Exception: pass
        time.sleep(1)
    raise SystemExit("health timeout")

def start_server(name, n_slots, ctx, ctk):
    s = config.resolve_llama_settings({"n_slots": n_slots, "ctx_per_slot": ctx, "cache_type_k": ctk, "cache_type_v": ctk})
    cmd = supervisor.build_head_command(MODEL, [], s)
    i = cmd.index("--slot-save-path"); cmd[i + 1] = str(SLOTS) + "/"
    log(f"[{name}] cmd:", " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=open(B / f"server-{name}.log", "w"), stderr=subprocess.STDOUT)
    log(f"[{name}] ready in {wait_health(8080, p):.1f}s pid {p.pid}")
    return p

def stop(p, name):
    p.send_signal(signal.SIGTERM)
    try: p.wait(60)
    except subprocess.TimeoutExpired:
        log(f"[{name}] SIGTERM timeout, SIGKILL"); p.kill(); p.wait()
    log(f"[{name}] stopped rc={p.returncode}")

CITIES = ["Lisbon","Oslo","Kyoto","Denver","Nairobi","Lima","Perth","Tallinn","Quebec","Hanoi","Porto","Bergen"]
ITEMS = ["copper wire","glass jars","oak planks","wool blankets","steel bolts","rice sacks","tea chests","solar panels"]
def filler(n):
    lines = []
    for i in range(n):
        c = CITIES[(i * 7) % len(CITIES)]; it = ITEMS[(i * 5) % len(ITEMS)]
        lines.append(f"Record {i+1}: the {c} depot logged {(i * 37) % 900 + 100} units of {it} on day {(i % 28) + 1}.")
    return lines
NEEDLE = "Important note: the vault access code is ORCHID-7419."
def prompts():
    q = ("Answer in one short line each, no explanation. 1) What is the vault access code? "
         "2) What is 17 multiplied by 23? 3) What is the capital of Australia?")
    short = NEEDLE + "\n" + q
    lines = filler(290); lines.insert(60, NEEDLE)
    long_ = "Here is a long inventory log.\n" + "\n".join(lines) + "\n\n" + q
    return {"short": short, "long": long_}
NO_THINK = os.environ.get("NO_THINK", "")

def chat(base, content, name):
    body = {"model": "x", "temperature": 0, "seed": 1, "max_tokens": MAXTOK,
            "messages": [{"role": "user", "content": content + NO_THINK}]}
    r, dt = post(base + "/v1/chat/completions", body)
    tm = r.get("timings", {}); msg = r["choices"][0]["message"]
    out = {"name": name, "wall_s": round(dt, 2), "prompt_n": tm.get("prompt_n"), "prompt_tps": tm.get("prompt_per_second"),
           "gen_n": tm.get("predicted_n"), "gen_tps": tm.get("predicted_per_second"),
           "content": msg.get("content"), "reasoning": (msg.get("reasoning_content") or "")[:400]}
    log(json.dumps(out)); return out

results = {}
# 1) Caravan settings (q8_0, fa on, Caravan flags) minus --rpc, 2 slots x 8192, through the proxy
p = start_server("q8", 2, 8192, "q8_0")
try:
    env = dict(os.environ, CARAVAN_PROXY_PORT="8090", CARAVAN_N_SLOTS="2", CARAVAN_SLOT_SAVE_DIR=str(SLOTS),
               CARAVAN_PROXY_STATE_FILE=str(B / "session_slots.json"), CARAVAN_SLOT_CLEANUP="off")
    px = subprocess.Popen([sys.executable, str(Path.home() / "dev/caravan/proxy/slot_pin_proxy.py")],
                          stdout=open(B / "proxy.log", "w"), stderr=subprocess.STDOUT, env=env)
    try:
        log(f"[proxy] ready in {wait_health(8090, px, 30):.1f}s")
        P = prompts()
        results["proxy_smoke"] = chat("http://127.0.0.1:8090", "Say hello in five words.", "proxy_smoke")
        results["proxy_smoke_2"] = chat("http://127.0.0.1:8090", "Say hello in five words.", "proxy_smoke_repeat")
        results["q8_short"] = chat("http://127.0.0.1:8080", P["short"], "q8_short")
        results["q8_long"] = chat("http://127.0.0.1:8080", P["long"], "q8_long")
    finally:
        stop(px, "proxy")
finally:
    stop(p, "q8")
# 2) same prompts with f16 KV, 1 slot x 8192 (keeps memory in bounds)
p = start_server("f16", 1, 8192, "f16")
try:
    P = prompts()
    results["f16_short"] = chat("http://127.0.0.1:8080", P["short"], "f16_short")
    results["f16_long"] = chat("http://127.0.0.1:8080", P["long"], "f16_long")
finally:
    stop(p, "f16")
json.dump(results, open(B / "smoke.json", "w"), indent=1)
log("SMOKE DONE")
