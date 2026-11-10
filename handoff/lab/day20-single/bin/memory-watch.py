import datetime,json,subprocess,threading
from pathlib import Path
p=Path.home()/'day20-single';code="import sys,json,subprocess;from pathlib import Path;sys.path.insert(0,str(Path.home()/'dev/caravan-v3/agent'));from mlx_split import host_memory_gb;print(json.dumps({'memory_gb':host_memory_gb(),'swap':subprocess.check_output(['/usr/sbin/sysctl','vm.swapusage'],text=True).strip()}))"
while not (p/'stop-memory-watch').exists():
 d={'at_CST':datetime.datetime.now().astimezone().isoformat()}
 try:d.update(json.loads(subprocess.check_output(['ssh','-o','ConnectTimeout=3','exo1','python3','-'],input=code,text=True,timeout=10)))
 except Exception as e:d['error']=str(e)
 with (p/'raw/memory-watch.jsonl').open('a') as f:f.write(json.dumps(d)+'\n')
 print(json.dumps(d),flush=True);threading.Event().wait(5)
