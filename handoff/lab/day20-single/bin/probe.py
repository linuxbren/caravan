import argparse,datetime,hashlib,json,time,urllib.request
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('label');ap.add_argument('--payload',required=True);ap.add_argument('--url',default='http://127.0.0.1:18090/v1/chat/completions');ap.add_argument('--thinking');ap.add_argument('--lookup');ap.add_argument('--max-tokens',type=int);ap.add_argument('--session');args=ap.parse_args()
root=Path.home()/'day20-single';b=json.loads(Path(args.payload).expanduser().read_text());b['stream']=False;b.pop('stream_options',None)
if args.thinking:b['reasoning_effort']=args.thinking
if args.lookup:b['prompt_lookup']=args.lookup
if args.max_tokens:b['max_tokens']=args.max_tokens
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));result={'label':args.label,'start_CST':datetime.datetime.now().astimezone().isoformat(),'tools':len(b.get('tools',[])),'reasoning_effort':b.get('reasoning_effort'),'max_tokens':b.get('max_tokens'),'lookup':b.get('prompt_lookup'),'request_sha256':hashlib.sha256(json.dumps(b,sort_keys=True).encode()).hexdigest()};t=time.monotonic();print('START',args.label,flush=True)
try:
 req=urllib.request.Request(args.url,data=json.dumps(b).encode(),headers={'Content-Type':'application/json','X-Caravan-Session':args.session or ('d20-'+args.label)})
 with opener.open(req,timeout=900) as r:result.update(http=r.status,aux_header=r.headers.get("X-Caravan-Aux"),response=json.load(r),ok=r.status==200)
except Exception as e:
 result.update(ok=False,error=str(e))
 try:result['error_body']=e.read().decode()
 except Exception:pass
result.update(wall_s=time.monotonic()-t,end_CST=datetime.datetime.now().astimezone().isoformat());(root/'raw'/(args.label+'.json')).write_text(json.dumps(result,indent=2));r=result.get('response') or {};u=r.get('usage') or {};c=u.get('caravan') or {};print('DONE',args.label,result.get('ok'),round(result['wall_s'],3),c,flush=True)
