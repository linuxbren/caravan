import json, glob, os
os.chdir(os.path.expanduser("~/.caravan/bench-2026-10-30/improvements"))
for f in sorted(glob.glob("*/results.json")):
    t = f.split("/")[0]; r = json.load(open(f)); c = r.get("config", {})
    print(f"== {t} kv={c.get('kv')} dec={str(c.get('kv_decision'))[:260]!r} swa_full={c.get('swa_full')} ns={c.get('n_slots')} ctx={c.get('ctx_per_slot')}")
    if "main" in r: m = r["main"]; print("  main pp512 %s pp4096 %s tg128 %s" % (m.get("pp512"), m.get("pp4096"), m.get("tg128")))
    if "d16k" in r: d = r["d16k"]; print("  d16k pp %s tg %s new %s" % (d.get("pp512_d16k"), d.get("tg128_d16k"), d.get("new_ntok")))
    if "quality" in r: print("  quality", {k: v.get("score") for k, v in r["quality"].items()})
    if "mem" in r: print("  mem", r["mem"])
    if "start_s" in r: print("  start_s", r["start_s"])
    if "resume" in r:
        q = r["resume"]
        for k in ("t1_cold", "t2_warm_in_memory", "t3_resume_after_restart", "t3_after_restart"):
            if k in q: x = q[k]; print(f"  {k}: ttft {x.get('ttft_s')} prompt_n {x.get('prompt_n')} cache_n {x.get('cache_n')} gen_tps {x.get('gen_tps')} -> {x.get('content','')[:40]!r}")
        print("  restart_s", q.get("restart_s"), "slotfiles", q.get("slot_files_after_t2"))
        for l in (q.get("server_log_after_restart") or []) + (q.get("proxy_log") or []):
            if "checkpoint" in l or "restor" in l.lower() or "forcing" in l or "mlx" in l: print("   |", l[:230])
    if "resume_raw" in r:
        q = r["resume_raw"]
        for k in ("cold", "warm_in_memory", "after_restart"):
            x = q[k]; print(f"  raw {k}: wall {x.get('wall_s')} prompt_n {x.get('prompt_n')} cache_n {x.get('cache_n')}")
        for l in q.get("server_log_after_restart") or []:
            if "checkpoint" in l or "forcing" in l: print("   |", l[:230])
