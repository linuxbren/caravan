import datetime,json,threading,time,urllib.request,sys
from pathlib import Path
label=sys.argv[1];http=urllib.request.build_opener(urllib.request.ProxyHandler({}));r={'at_CST':datetime.datetime.now().astimezone().isoformat()}
req=urllib.request.Request('http://127.0.0.1:18190/api/models/stop',data=b'{}',headers={'Content-Type':'application/json'})
with http.open(req,timeout=60) as x:r['response']=json.load(x)
until=time.monotonic()+45
while time.monotonic()<until:
 with http.open('http://127.0.0.1:18190/api/status',timeout=10) as x:s=json.load(x)
 w=s['worker'];print('STOP-WAIT',label,w['status'],flush=True)
 if w['status']=='idle' and not w.get('lead_pid'):r['final']=s;break
 threading.Event().wait(2)
else:raise SystemExit('normal Stop did not release model; refusing another load')
(Path.home()/'day20-single/raw'/(label+'-stop.json')).write_text(json.dumps(r,indent=2))
