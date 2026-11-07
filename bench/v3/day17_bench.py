#!/usr/bin/env python3
"""Auditable Day 17 HTTP benchmark. Includes error rows and full responses."""
import argparse
import ast
import re
import concurrent.futures
import datetime
import json
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

PROMPTS = [
    {"id": "count", "text": "Count from 1 to 80 in order, separated by commas. Output only the numbers."},
    {"id": "code", "text": "Write a Python function merge_sort(values) with a helper merge(left, right), then three assert tests including duplicates and an empty list. Output only Python code."},
    {"id": "quality", "text": "Reply exactly with these three lines, with no explanation:\n2 + 2 = 4\nFrance: Paris\nWater: H2O"},
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--url",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--model",required=True)
    ap.add_argument("--placement",required=True)
    ap.add_argument("--modes",default="off,on,on,off")
    ap.add_argument("--max-tokens",type=int,default=768)
    ap.add_argument("--include-repeat",action="store_true")
    ap.add_argument("--expect-pid",type=int)
    ap.add_argument("--concurrency",type=int,default=1)
    args=ap.parse_args()
    if args.include_repeat:
        passage="The little green robot walks beside the quiet blue river. " * 12
        PROMPTS.append({"id":"repeat","text":"Repeat the following passage exactly, without commentary:\n"+passage})
    commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    def request(prompt,mode,wave,member=0):
        row={"timestamp_ct":datetime.datetime.now(ZoneInfo("America/Chicago")).isoformat(),
             "timezone":"America/Chicago (CT)","commit":commit,"model":args.model,
             "placement":args.placement,"mode":mode,"wave":wave,"member":member,
             "concurrency":args.concurrency,"prompt_id":prompt["id"],"prompt":prompt["text"]}
        body={"messages":[{"role":"user","content":prompt["text"]}],"max_tokens":args.max_tokens,
              "temperature":0,"seed":17,"stream":False,"chat_template_kwargs":{"enable_thinking":False}}
        if mode in ("on","off"):body["native_mtp"]=mode=="on"
        if mode in ("pl-off","pl-adaptive"):body["prompt_lookup"]="adaptive" if mode=="pl-adaptive" else "off"
        if args.expect_pid:
            import os
            try:os.kill(args.expect_pid,0)
            except ProcessLookupError:
                raise RuntimeError("Expected worker changed; abort rather than fight UI state")
        row["settings"]=body
        req=urllib.request.Request(args.url+"/v1/chat/completions",data=json.dumps(body).encode(),
            headers={"Content-Type":"application/json","X-Caravan-Session":"d17-"+uuid.uuid4().hex})
        t=time.perf_counter()
        try:
            with urllib.request.urlopen(req,timeout=180) as r:response=json.load(r)
            row["response"]=response
            usage=response.get("usage") or {};info=usage.get("caravan") or {}
            row["ttft_s"]=info.get("ttft_s")
            row["completion_tokens"]=usage.get("completion_tokens")
            row["total_s"]=info.get("total_s")
            denom=(info.get("total_s") or 0)-(info.get("ttft_s") or 0)
            row["write_tps"]=(max((usage.get("completion_tokens") or 0)-1,0)/denom if denom>0 else None)
            row["acceptance"]=(info.get("speculate") or {}).get("accepted_frac")
            row["text"]=(response.get("choices") or [{}])[0].get("message",{}).get("content","")
            if prompt["id"] == "code":
                code=re.sub(r"^```(?:python)?\s*|\s*```$", "", row["text"].strip())
                try:
                    ast.parse(code)
                    row["quality_python_syntax"]=True
                except SyntaxError:
                    row["quality_python_syntax"]=False
            if prompt["id"] == "count":
                nums=[int(x) for x in re.findall(r"\d+", row["text"])]
                row["quality_count_prefix"]=bool(nums) and nums==list(range(1,len(nums)+1))
            row["quality_exact"]=(row["text"].strip()=="2 + 2 = 4\nFrance: Paris\nWater: H2O") if prompt["id"]=="quality" else None
        except Exception as e:
            row["error"]=repr(e)
        row["wall_s"]=time.perf_counter()-t
        return row
    for wave,mode in enumerate(args.modes.split(",")):
        for prompt in PROMPTS:
            start=time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                rows=list(pool.map(lambda i:request(prompt,mode,wave,i),range(args.concurrency)))
            wall=time.perf_counter()-start
            for row in rows:
                row["wave_wall_s"]=wall
                row["wave_aggregate_tps"]=sum(r.get("completion_tokens") or 0 for r in rows)/wall if any("response" in r for r in rows) else None
                with path.open("a") as f:f.write(json.dumps(row)+"\n")
                print(json.dumps({k:v for k,v in row.items() if k not in ("response","settings","prompt","text")}),flush=True)
if __name__=="__main__":main()
