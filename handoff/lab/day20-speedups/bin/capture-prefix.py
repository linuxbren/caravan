"""Run with Hermes's venv Python, from the desired workspace; offline only.

Writes PRIVATE system/tool instructions locally. Never publish private/.
Uses Hermes inspection APIs, which may change with Hermes versions.
"""
import argparse,hashlib,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--hermes-repo',default=str(Path.home()/'.hermes/hermes-agent'));p.add_argument('--out',default=str(Path.home()/'day20-speedups'));p.add_argument('--model',default='mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit');a=p.parse_args()
sys.path.insert(0,a.hermes_repo)
from hermes_cli.prompt_size import _build_inspection_agent
from agent.system_prompt import build_system_prompt
from agent.title_generator import _TITLE_PROMPT_TEMPLATE,_TITLE_RESPONSE_FORMAT,_LANGUAGE_RULE_MATCH_USER
agent=_build_inspection_agent('cli');system=build_system_prompt(agent);tools=agent.tools
root=Path(a.out);private=root/'private';private.mkdir(parents=True,exist_ok=True);private.chmod(0o700);(root/'raw').mkdir(exist_ok=True)
for name,body in {
 'hermes-prefix.json':{'messages':[{'role':'system','content':system}],'tools':tools},
 'title.json':{'model':a.model,'messages':[{'role':'system','content':_TITLE_PROMPT_TEMPLATE.replace('__LANGUAGE_RULE__',_LANGUAGE_RULE_MATCH_USER)},{'role':'user','content':'Checking Caravan after reboot and improving Hermes speed'}],'response_format':_TITLE_RESPONSE_FORMAT,'reasoning_effort':'none','max_tokens':64,'stream':False,'temperature':0}
}.items():
 f=private/name;f.write_text(json.dumps(body));f.chmod(0o600)
meta={'configured_tool_count':len(tools),'system_chars':len(system),'system_sha256':hashlib.sha256(system.encode()).hexdigest(),'tools_sha256':hashlib.sha256(json.dumps(tools,sort_keys=True).encode()).hexdigest(),'cwd':str(Path.cwd()),'note':'Offline inspection; no model or tool invocation; private instructions excluded from published evidence.'}
(root/'raw/prefix-metadata.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta,indent=2))
