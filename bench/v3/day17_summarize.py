#!/usr/bin/env python3
"""Reproducible Day17 medians + restricted, timed semantic code checks."""
import ast
import datetime
from zoneinfo import ZoneInfo
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path


def code_quality(text):
    code=re.sub(r'^```(?:python)?\s*|\s*```$', '', text.strip())
    try: tree=ast.parse(code)
    except SyntaxError:return {'syntax':False}
    # No arbitrary imports, I/O, attribute traversal or hidden builtins. Run
    # only the small merge-sort language subset, in a time/resource-limited child.
    names={'merge','merge_sort','len','range','sorted','list'}
    for n in ast.walk(tree):
        if isinstance(n,(ast.Import,ast.ImportFrom,ast.With,ast.AsyncWith,ast.ClassDef,ast.Global,ast.Nonlocal)):
            return {'syntax':True,'execution_refused':'outside safe subset'}
        if isinstance(n,ast.Attribute) and n.attr not in {'append','extend','copy'}:
            return {'syntax':True,'execution_refused':'attribute outside safe subset'}
        if isinstance(n,ast.Name) and n.id.startswith('__'):
            return {'syntax':True,'execution_refused':'hidden name'}
        if isinstance(n,ast.Call) and not ((isinstance(n.func,ast.Name) and n.func.id in names) or
                                          (isinstance(n.func,ast.Attribute) and n.func.attr in {'append','extend','copy'})):
            return {'syntax':True,'execution_refused':'call outside safe subset'}
    child='''import json,resource,sys
resource.setrlimit(resource.RLIMIT_CPU,(1,1))
resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
scope={"__builtins__":{"len":len,"range":range,"sorted":sorted,"list":list}}
exec(compile(sys.stdin.read(),"generated-check","exec"),scope)
for x in ([],[1],[2,1],[3,1,4,1,5],[5,5,5],[-2,0,-2,9],list(range(40,-1,-1))):
 assert scope["merge_sort"](x.copy())==sorted(x),repr(x)
print("PASS")
'''
    try:
        r=subprocess.run([sys.executable,'-I','-c',child],input=code,text=True,capture_output=True,timeout=2)
        return {'syntax':True,'assert_count':sum(isinstance(n,ast.Assert) for n in ast.walk(tree)),
                'generated_and_seven_extra_cases_pass':r.returncode==0,'error':r.stderr or None}
    except subprocess.TimeoutExpired:return {'syntax':True,'execution_timeout':True}


def summarize(path):
    rows=[json.loads(x) for x in path.read_text().splitlines()]
    out={'validation_timestamp_ct':datetime.datetime.now(ZoneInfo('America/Chicago')).isoformat(),'file':str(path),'rows':len(rows),'errors':sum('error' in r for r in rows),'groups':{},'quality':[]}
    for mode in sorted({r['mode'] for r in rows}):
        good=[r for r in rows if r['mode']==mode and 'error' not in r]
        if not good:continue
        spec=[r.get('response',{}).get('usage',{}).get('caravan',{}).get('speculate') or {} for r in good]
        n=sum(s.get('proposed',0) for s in spec);a=sum(s.get('accepted',0) for s in spec)
        out['groups'][mode]={'n':len(good),'median_write_tps':statistics.median(r['write_tps'] for r in good),
            'median_ttft_s':statistics.median(r['ttft_s'] for r in good),'native_proposed':n,'native_accepted':a,
            'native_acceptance':a/n if n else None,
            'median_drafted_token_share':statistics.median(r['acceptance'] for r in good) if mode.startswith('pl-') and all(r.get('acceptance') is not None for r in good) else None,'per_prompt':{}}
        for prompt in sorted({r['prompt_id'] for r in good}):
            sub=[r for r in good if r['prompt_id']==prompt]
            waves={r['wave']:r['wave_aggregate_tps'] for r in sub}
            out['groups'][mode]['per_prompt'][prompt]={'median_write_tps':statistics.median(r['write_tps'] for r in sub),
                'median_ttft_s':statistics.median(r['ttft_s'] for r in sub),
                'median_wave_aggregate_tps':statistics.median(waves.values())}
    for r in rows:
        if 'text' not in r:continue
        q={k:v for k,v in r.items() if k.startswith('quality_')}
        q.update({'timestamp_ct':r['timestamp_ct'],'mode':r['mode'],'prompt_id':r['prompt_id'],
            'finish_reason':r['response']['choices'][0].get('finish_reason'),
            'byte_identical_all_modes':len({s['text'] for s in rows if s.get('prompt_id')==r['prompt_id'] and 'text' in s})==1})
        if r['prompt_id']=='code':q['semantic']=code_quality(r['text'])
        if r['prompt_id']=='quality':q['lines_ignoring_trailing_spaces']= '\n'.join(x.rstrip() for x in r['text'].strip().splitlines())=='2 + 2 = 4\nFrance: Paris\nWater: H2O'
        out['quality'].append(q)
    return out

if __name__=='__main__':
    directory=Path('bench/results/day17')
    files=[p for p in sorted(directory.glob('*.jsonl'))]
    data=[summarize(p) for p in files]
    (directory/'complete-summary.json').write_text(json.dumps(data,indent=2)+'\n')
    for d in data:print(d['file'],json.dumps(d['groups']))
