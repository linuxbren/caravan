"""Sequential single-node exo runs on this Mini. usage: exo_suite.py [models...]"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path
API = "http://127.0.0.1:52415"; B = Path.home() / ".caravan/bench-2026-10-30/runtime-compare"; (B / "exo").mkdir(exist_ok=True)
LOG = open(B / "exo/suite.log", "a")
def log(*a):
    s = time.strftime("%T ") + " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
def call(path, body=None, method=None, timeout=60):
    req = urllib.request.Request(API + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=timeout))
def state(): return call("/state", timeout=20)
RUNS = [("qwen3-30b-a3b-4bit", "mlx-community/Qwen3-30B-A3B-4bit", 200, "/no_think"),
        ("gemma4-26b-a4b-it-4bit", "mlx-community/gemma-4-26b-a4b-it-4bit", 1000, ""),
        ("gpt-oss-20b-mxfp4-q8", "mlx-community/gpt-oss-20b-MXFP4-Q8", 800, "")]
want = sys.argv[1:] or [r[0] for r in RUNS]
for tag, mid, maxtok, nothink in RUNS:
    if tag not in want: continue
    s = state(); log(tag, "nodes", len(s["topology"]["nodes"]), "instances before", list(s["instances"]))
    try:
        log("place", call("/place_instance", {"model_id": mid, "sharding": "Pipeline", "instance_meta": "MlxRing", "min_nodes": 1}))
    except urllib.error.HTTPError as e:
        log("place FAILED", e.code, e.read().decode()[:1000]); continue
    iid = None; t0 = time.time(); kinds = []
    while time.time() - t0 < 900:
        s = state()
        for k, v in s["instances"].items():
            if v[next(iter(v))]["shardAssignments"]["modelId"] == mid: iid = k
        if iid:
            inst = s["instances"][iid]; rids = list(inst[next(iter(inst))]["shardAssignments"]["runnerToShard"])
            kinds = [next(iter(s["runners"].get(r, {"none": 0}))) for r in rids]
            if kinds and all(k == "RunnerReady" for k in kinds): break
            if any("Fail" in k for k in kinds): log("runner failed", s["runners"]); break
        time.sleep(3)
    log(tag, "instance", iid, "runners", kinds, f"after {time.time()-t0:.0f}s")
    if iid: json.dump(s["instances"][iid], open(B / f"exo/{tag}-instance.json", "w"), indent=1)
    if iid and kinds and all(k == "RunnerReady" for k in kinds):
        env = dict(os.environ, NO_THINK=nothink)
        rc = subprocess.run(["/opt/homebrew/bin/python3", "-u", str(B / "exo_bench.py"), tag, mid, str(maxtok)],
                            stdout=open(B / f"exo/{tag}.out", "a"), stderr=subprocess.STDOUT, env=env).returncode
        log(tag, "bench rc", rc)
    if iid:
        log("delete", call(f"/instance/{iid}", method="DELETE"))
        for _ in range(60):
            s = state()
            if iid not in s["instances"] and not s["runners"]: break
            time.sleep(3)
        log("after delete instances", list(s["instances"]), "runners", s["runners"]); time.sleep(10)
log("EXO SUITE DONE")
