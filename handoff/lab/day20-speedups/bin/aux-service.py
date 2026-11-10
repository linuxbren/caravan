import subprocess,sys
ACTION=sys.argv[1]
code=r"""
import os,plistlib,subprocess
from pathlib import Path
h=Path.home();p=h/'Library/LaunchAgents/com.caravan.v3.aux.plist';label='com.caravan.v3.aux';target=f'gui/{os.getuid()}'
ACTION='__ACTION__'
if ACTION=='start':
 log=h/'.caravan/logs/day20-aux.log';log.parent.mkdir(parents=True,exist_ok=True)
 args=[str(h/'.caravan/venvs/mlx/bin/python'),str(h/'dev/caravan-v3/tools/aux_worker.py'),'--model',str(h/'.caravan/mlx-models/drafts/Qwen2.5-0.5B-Instruct-4bit'),'--budget-gb','0.9']
 body={'Label':label,'ProgramArguments':args,'WorkingDirectory':str(h/'dev/caravan-v3'),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,'StandardOutPath':str(log),'StandardErrorPath':str(log),'EnvironmentVariables':{'HOME':str(h),'PYTHONUNBUFFERED':'1','CARAVAN_NO_LEARN':'1','PATH':str(h/'.caravan/venvs/mlx/bin')+':/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'}}
 p.write_bytes(plistlib.dumps(body));r=subprocess.run(['launchctl','bootstrap',target,str(p)]);print('AUX-START',r.returncode,p,log)
elif ACTION=='stop':
 r=subprocess.run(['launchctl','bootout',target+'/'+label]);print('AUX-STOP',r.returncode)
else:raise ValueError(ACTION)
"""
if ACTION not in ['start','stop']:raise ValueError(ACTION)
subprocess.run(['ssh','exo1','python3','-'],input=code.replace('__ACTION__',ACTION),text=True,check=True)
