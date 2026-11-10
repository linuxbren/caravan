import datetime,json,subprocess,threading
from pathlib import Path
p=Path.home()/'day20-single';code="import os,sys,json,subprocess;os.environ['PATH']='/usr/sbin:/sbin:/usr/bin:/bin:/opt/homebrew/bin';from pathlib import Path;sys.path.insert(0,str(Path.home()/'dev/caravan-v3/agent'));from system_stats import _vm_stat;assert _vm_stat().get('Pages active',0)>0;from mlx_split import host_memory_gb;print(json.dumps({'memory_gb':host_memory_gb(),'swap':subprocess.check_output(['/usr/sbin/sysctl','vm.swapusage'],text=True).strip()}))"
while not (p/'stop-memory-watch-real').exists():
 d={'at_CST':datetime.datetime.now().astimezone().isoformat()}
 try:d.update(json.loads(subprocess.check_output(['ssh','-o','ConnectTimeout=3','exo1','~/.caravan/venvs/mlx/bin/python','-'],input=code,text=True,timeout=10)))
 except Exception as e:d['error']=str(e)
 with (p/'raw/memory-watch-real.jsonl').open('a') as f:f.write(json.dumps(d)+'\n')
 print(json.dumps(d),flush=True);threading.Event().wait(5)
