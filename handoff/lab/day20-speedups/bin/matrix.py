import argparse,copy,datetime,hashlib,json,sys,time,urllib.request
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('label');ap.add_argument('--model',default='mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit');ap.add_argument('--thinking',default='medium');ap.add_argument('--routes',nargs='+',default=['direct','hermes']);ap.add_argument('--max-tokens',type=int,default=512);ap.add_argument('--same-warm',action='store_true');args=ap.parse_args()
root=Path.home()/'day20-speedups';out=root/'raw'/args.label;out.mkdir(exist_ok=True)
open_http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
prefix=json.loads((root/'private/hermes-prefix.json').read_text())
question='Give three brief checks for confirming a local AI service recovered after reboot. Do not run tools. Keep the answer under 45 words.'
for route in args.routes:
 for cache in ['cold','warm']:
  name=route+'-'+cache
  if (out/(name+'.json')).exists():continue
  b=copy.deepcopy(prefix) if route=='hermes' else {'messages':[{'role':'system','content':'You are a helpful assistant. Answer briefly and plainly.'}]}
  b.update(model=args.model,max_tokens=args.max_tokens,temperature=0,stream=True,stream_options={'include_usage':True},reasoning_effort=args.thinking)
  b['messages'].append({'role':'user','content':question+(' Use plain language.' if cache=='warm' and not args.same_warm else '')})
  url='http://127.0.0.1:'+('18190' if route=='direct' else '18090')+'/v1/chat/completions'
  private=root/'private'/(args.label+'-'+name+'.json');private.write_text(json.dumps(b));private.chmod(0o600)
  result={'label':args.label,'route':route,'cache_label':cache,'start_CST':datetime.datetime.now().astimezone().isoformat(),'tools':len(b.get('tools',[])),'max_tokens':args.max_tokens,'reasoning_effort':args.thinking,'request_sha256':hashlib.sha256(private.read_bytes()).hexdigest()}
  print('START',args.label,name,result['start_CST'],flush=True);t=time.monotonic();first=None;visible=None;events=[];text='';reason='';usage=None
  try:
   req=urllib.request.Request(url,data=json.dumps(b).encode(),headers={'Content-Type':'application/json','X-Caravan-Session':'d20-'+args.label+'-'+route})
   with open_http.open(req,timeout=900) as r:
    result['http']=r.status
    for line in r:
     if not line.startswith(b'data:'):continue
     s=line[5:].strip()
     if s==b'[DONE]':break
     try:d=json.loads(s)
     except ValueError:continue
     events.append(d)
     if d.get('usage'):usage=d['usage']
     for c in d.get('choices',[]):
      delta=c.get('delta') or c.get('message') or {};a=delta.get('content') or '';h=delta.get('reasoning_content') or delta.get('reasoning') or ''
      if (a or h or delta.get('tool_calls')) and first is None:first=time.monotonic()-t
      if a and visible is None:visible=time.monotonic()-t
      text+=a;reason+=h
      if c.get('finish_reason'):result['finish_reason']=c['finish_reason']
   result.update(ok=result.get('http')==200 and usage is not None and result.get('finish_reason') in ['stop','length'],wall_s=time.monotonic()-t,first_wire_token_s=first,first_visible_s=visible,usage=usage,answer=text,reasoning_chars=len(reason))
  except Exception as e:result.update(ok=False,error=str(e),wall_s=time.monotonic()-t)
  result['end_CST']=datetime.datetime.now().astimezone().isoformat();(out/(name+'.json')).write_text(json.dumps(result,indent=2));(out/(name+'-events.json')).write_text(json.dumps(events));print('DONE',json.dumps(result),flush=True)

  if not result.get("ok"):raise SystemExit("Invalid stream; saved raw result, stopping matrix")
