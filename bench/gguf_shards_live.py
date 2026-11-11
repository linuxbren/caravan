#!/usr/bin/env python3
"""Direct chat-only Day22 experiment; no Hermes, prefixes, or service switching.

Point at the isolated Caravan native GGUF backend. Appends raw SSE timing
results with wall TTFT (first non-empty text), completion usage and native
predicted tok/s when provided. Never loads/unloads a production worker.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time
import urllib.request
from zoneinfo import ZoneInfo

PROMPT = 'Explain how a rainbow forms, then give a simple experiment a child can try with water and sunlight. Use clear everyday language.'


def chat(base,max_tokens=128):
    body=dict(model='caravan-day22',messages=[dict(role='user',content=PROMPT)],
              stream=True,stream_options=dict(include_usage=True),temperature=0,
              max_tokens=max_tokens,cache_prompt=False,ignore_eos=True,seed=42)
    req=urllib.request.Request(base.rstrip('/')+'/v1/chat/completions',data=json.dumps(body).encode(),
                               headers={'Content-Type':'application/json'})
    t0=time.perf_counter();first=None;parts=[];last={};usage={};timings={}
    with urllib.request.urlopen(req,timeout=180) as r:
        for line in r:
            if not line.startswith(b'data: '): continue
            text=line[6:].strip()
            if text==b'[DONE]': break
            d=json.loads(text);last=d
            if d.get('usage'): usage=d['usage']
            if d.get('timings'): timings=d['timings']
            for choice in d.get('choices') or []:
                content=(choice.get('delta') or {}).get('content')
                if content:
                    if first is None: first=time.perf_counter()
                    parts.append(content)
    end=time.perf_counter()
    if first is None: raise RuntimeError('no text content received: '+str(last))
    tokens=usage.get('completion_tokens')
    return dict(ok=True,prompt=PROMPT,max_tokens=max_tokens,temperature=0,
                ttft_s=round(first-t0,6),wall_s=round(end-t0,6),usage=usage,timings=timings,
                wall_decode_tok_s=round((tokens-1)/(end-first),3) if tokens and tokens>1 else None,
                text=''.join(parts),endpoint=base,
                ct=datetime.now(ZoneInfo('America/Chicago')).isoformat())


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--base',required=True)
    ap.add_argument('--label',required=True);ap.add_argument('--runs',type=int,default=3)
    ap.add_argument('--out',required=True);a=ap.parse_args()
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    for i in range(a.runs):
        try: row=chat(a.base)
        except Exception as e: row=dict(ok=False,error=str(e))
        row.update(label=a.label,run=i+1)
        with open(a.out,'a') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
        if not row['ok']:raise SystemExit(1)

if __name__=='__main__':main()
