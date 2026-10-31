import json, os, subprocess, sys, time, urllib.request
from pathlib import Path
B = Path.home() / ".caravan/bench-2026-10-30/runtime-compare"; API = "http://127.0.0.1:52415"
LOG = open(B / "exo/retry.log", "a")
def log(*a):
    s = time.strftime("%T ") + " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
def call(path, body=None, method=None, timeout=60):
    req = urllib.request.Request(API + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=timeout))
tag, mid, maxtok, nothink, phases = "qwen3-30b-a3b-4bit-retry", "mlx-community/Qwen3-30B-A3B-4bit", 200, "/no_think", "quality,d16k"
log("instances before", list(call("/state")["instances"]))
log("place", str(call("/place_instance", {"model_id": mid, "sharding": "Pipeline", "instance_meta": "MlxRing", "min_nodes": 1}))[:200])
iid = None; kinds = []
for _ in range(100):
    s = call("/state")
    for k, v in s["instances"].items():
        inner = next(iter(v.values())); iid = k
        rids = list(inner["shardAssignments"]["runnerToShard"].keys())
        kinds = [next(iter(s["runners"].get(r, {"none": 0}))) for r in rids]
    if kinds and (all(k == "RunnerReady" for k in kinds) or any("Fail" in k for k in kinds)): break
    time.sleep(3)
log("instance", iid, kinds)
if iid and all(k == "RunnerReady" for k in kinds):
    rc = subprocess.run(["/opt/homebrew/bin/python3", "-u", str(B / "exo_bench.py"), tag, mid, str(maxtok), phases],
        stdout=open(B / f"exo/{tag}.out", "a"), stderr=subprocess.STDOUT, env=dict(os.environ, NO_THINK=nothink)).returncode
    log("bench rc", rc)
    s = call("/state"); log("runners after bench", s["runners"])
if iid:
    log("delete", call(f"/instance/{iid}", method="DELETE"))
    for _ in range(40):
        s = call("/state")
        if not s["instances"]: break
        time.sleep(3)
log("RETRY DONE")
