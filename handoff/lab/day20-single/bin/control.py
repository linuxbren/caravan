import argparse,datetime,json,time,urllib.request,urllib.error,threading
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('label');ap.add_argument('--model',required=True);ap.add_argument('--single',action='store_true');ap.add_argument('--counts',default='24,24');ap.add_argument('--kv',default='16');args=ap.parse_args()
root=Path.home()/'day20-single/raw';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));ids=['exo1'] if args.single else ['exo2','exo1']
b={'model_id':args.model,'engine':'mlx','placement':{'mode':'one' if args.single else 'split','node_ids':ids},'node_ids':ids,'settings':{'self_tune':'off','guess_ahead':'off','prompt_lookup':'off','shared_start':'off','pipeline_chats':'1','kv_bits':args.kv}}
if not args.single:b.update(balance=True,counts=[int(n) for n in args.counts.split(',')])
with opener.open('http://127.0.0.1:18190/api/status',timeout=15) as x:before=json.load(x)
old_pid=before['worker'].get('lead_pid')
r={'old_lead_pid':old_pid,'start_CST':datetime.datetime.now().astimezone().isoformat(),'request':b};print('LOAD',args.label,flush=True)
try:
 req=urllib.request.Request('http://127.0.0.1:18190/api/models/load',data=json.dumps(b).encode(),headers={'Content-Type':'application/json'})
 with opener.open(req,timeout=180) as x:r.update(http=x.status,body=json.load(x))
 if r['http']==200:
  until=time.monotonic()+600
  while time.monotonic()<until:
   try:
    with opener.open('http://127.0.0.1:18190/api/status',timeout=15) as x:s=json.load(x)
    status=s['worker']['status'];print('STATUS',args.label,status,flush=True)
    w=s['worker']; actual=(s.get('active') or {}).get('kv_bits'); expected_counts=[int(n) for n in args.counts.split(',')]
    target_ready=(status=='ready' and w.get('model_id')==args.model and w.get('lead_pid')!=old_pid and s.get('lead_healthy') and actual==int(args.kv) and ((args.single and not w.get('split')) or (not args.single and (w.get('balance') or {}).get('counts')==expected_counts)))
    if status=='error' or target_ready:
     r['final_status']=s;break
   except Exception as e:print('STATUS-WAIT',str(e),flush=True)
   threading.Event().wait(2)
except Exception as e:
 r['error']=str(e)
 try:r['error_body']=e.read().decode()
 except Exception:pass
r['end_CST']=datetime.datetime.now().astimezone().isoformat();(root/(args.label+'-load.json')).write_text(json.dumps(r,indent=2));print('LOAD-RESULT',args.label,r.get('http'),r.get('error'),r.get('error_body'),(r.get('final_status') or {}).get('worker',{}).get('status'),flush=True)
if r.get('http')==200 and (r.get('final_status') or {}).get('worker',{}).get('status')!='ready':raise SystemExit(2)

if r.get("http")!=200:raise SystemExit(3)
