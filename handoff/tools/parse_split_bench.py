import json,sys,statistics as st
def load(f):
    R={}
    for l in open(f):
        l=l.strip()
        if not l: continue
        try: d=json.loads(l)
        except: continue
        if 'name' in d: R[d['name']]=d
    return R
for t in sys.argv[1:]:
  for tag in ['-old','']:
    try: R=load(f'{t}{tag}.jsonl')
    except FileNotFoundError: continue
    w=[R[k]['write_tps'] for k in ('tg128_0','tg128_1') if k in R]
    p5=[R[k]['read_tps'] for k in ('pp512_0','pp512_1') if k in R]
    p4=[R[k]['read_tps'] for k in ('pp4096_0','pp4096_1') if k in R]
    q=R.get('quality_score',{}).get('score')
    halves=[]
    for k in ('tg128_0','tg128_1'):
        d=R[k]; s=d['split']; n=s['calls']
        gen=d['total_s']-d['ttft_s']
        halves.append((s['front_s']/n*1e3, s['net_s']/n*1e3, (d['total_s']-s['wait_s'])/n*1e3, n, d['gen_n']))
    print(t+tag, 'write',w,st.median(w),'pp512',st.median(p5),'pp4k',st.median(p4),'q',q,'peak',[R[k]['peak_gb'] for k in ('tg128_0','tg128_1')])
    for h in halves: print('   packer %.2f cable %.2f lead %.2f calls %d gen %d'%h)
    print('   keys',list(R))
