"""Freeze argparse command/option metadata, stopping BEFORE parsing or execution.
Runs only during development against the specified owning source checkout.
"""
import argparse, importlib, json, sys, hashlib
from pathlib import Path
(Path(__file__).resolve().parents[1]/'docs/evidence/runs/v0.2.0').mkdir(parents=True,exist_ok=True)
root=Path(sys.argv[1]).resolve();sys.path[:0]=[str(root),str(root/'suite')]
class Captured(BaseException):pass
captured=[]
real_parse=argparse.ArgumentParser.parse_args
def capture(self,*a,**kw):captured.append(self);raise Captured()
argparse.ArgumentParser.parse_args=capture
entries=[]
parsers={}
def fields(parser,group):
 result=[]
 for i,a in enumerate(parser._actions):
  if isinstance(a,(argparse._HelpAction,argparse._VersionAction,argparse._SubParsersAction)):continue
  if not a.option_strings and a.dest==argparse.SUPPRESS:continue
  options=list(a.option_strings)
  result.append({'key':f'{group}-{i}-{a.dest}','dest':a.dest,'options':options,'flag':next((f for f in options if f.startswith('--')),options[0] if options else None),'type':'boolean' if isinstance(a,(argparse._StoreTrueAction,argparse._StoreFalseAction)) else 'integer' if a.type is int else 'number' if a.type is float else 'text','action':'append' if isinstance(a,argparse._AppendAction) else 'store_false' if isinstance(a,argparse._StoreFalseAction) else 'store','choices':list(a.choices) if a.choices is not None else None,'required':bool(a.required),'nargs':a.nargs,'default':a.default if isinstance(a.default,(str,int,float,bool,list,type(None))) else None,'help':a.help if isinstance(a.help,str) else '', 'group':group})
 return result
def walk(parser,module,label,command=(),parents=(),source=None):
 own=fields(parser,len(command));allfields=[*parents,*own]
 sub=next((a for a in parser._actions if isinstance(a,argparse._SubParsersAction)),None)
 if sub:
  for name,p in sub.choices.items():walk(p,module,label,(*command,name),allfields,source)
 else:
  entry={'id':f'{module}'+('/'+'/'.join(command) if command else ''),'module':module,'label':label+(' / '+' '.join(command) if command else ''),'command':list(command),'fields':allfields,'source':source,'source_sha256':hashlib.sha256((root/source).read_bytes()).hexdigest() if source else None,'execution':'trusted_terminal_only'}
  entries.append(entry)
modules=[
 ('localpilot_service.cli','Core service CLI（localpilot-core）'),('localpilot_service.__main__','认证服务启动（localpilot-service）'),('localpilot_service.adapter','HTTP / MCP 适配器（localpilot-adapter）'),('localpilot_service.configure','Host 配置生成'),('localpilot_service.backup','运行数据库一致性备份'),('localpilot_service.task_control','任务心跳控制（内部维护）'),
 ('agent.__main__','历史 Agent 交互与后端诊断'),('agent.tool_budget','工具预算报告'),('agent.cloud_credentials','可信终端录入云端凭据'),('localpilot_api.__main__','历史 Runtime API Host'),
 ('computer.cli','Computer Use 交互控制台'),('computer.build','Computer Use 测试构建'),('computer.probe','Computer Use 观察诊断'),('computer.poc','Computer Use PoC'),('computer.native_cases','Computer Use 原生资格案例'),('computer.research','Computer Use 研究'),('computer.real_apps','Computer Use 实际应用案例'),('computer.validate','Computer Use 验证'),('companion.cli','Companion 全部选项')]
for module,label in modules:
 mod=importlib.import_module(module);captured.clear()
 try:mod.main()
 except Captured:pass
 if not captured:raise ValueError('No parser captured: '+module)
 parsers[module]=captured[-1]
 source=str(Path(mod.__file__).relative_to(root));walk(captured[-1],module,label,source=source)
# Suite forwards the same complete Core parser, with an additional Companion model cache path.
for e in list(entries):
 if e['module']=='localpilot_service.cli':
  item=json.loads(json.dumps(e));item['id']=item['id'].replace('localpilot_service.cli','localpilot_suite.cli');item['module']='localpilot_suite.cli';item['label']=item['label'].replace('Core service CLI（localpilot-core）','统一 Suite 全部选项');item['source']='suite/localpilot_suite/cli.py';item['source_sha256']=hashlib.sha256((root/item['source']).read_bytes()).hexdigest()
  if item['command']==['init']:item['fields'].append({'key':'1-companion-model-path','dest':'companion_model_path','options':['--companion-model-path'],'flag':'--companion-model-path','type':'text','action':'store','choices':None,'required':False,'nargs':None,'default':None,'help':'Existing cached Companion model directory; no download.','group':1})
  entries.append(item)
mod=importlib.import_module('localpilot_suite.cli');captured.clear()
try:mod.upgrade([],root)
except Captured:pass
walk(captured[-1],'localpilot_suite.cli','Suite 模块升级',('upgrade',),source='suite/localpilot_suite/cli.py')
# main.py is an interactive wrapper around exactly the historical Agent options.
agent=next(e for e in entries if e['module']=='agent.__main__');wrapper=json.loads(json.dumps(agent));wrapper.update(id='legacy-main',module=None,label='历史硬件推荐与 Agent 入口（main.py）',source='main.py',source_sha256=hashlib.sha256((root/'main.py').read_bytes()).hexdigest());wrapper['fields'].append({'key':'0-verbose','dest':'verbose','options':['--verbose'],'flag':'--verbose','type':'boolean','action':'store','choices':None,'required':False,'nargs':None,'default':False,'help':'Show heuristic model/context recommendation details.','group':0});entries.append(wrapper)
value={'version':1,'source_commit':'3f0e7b5e5c8c6731a98369c1973f59ad7ba965f8','entrypoints':entries,'interactive_controls':{'agent':['/help','/exit','/quit','/settings','/model','/backend','/policy local-only|local-first|balanced|cloud-first|cloud-only','/thinking [value]','/reasoning hidden|summary|full','/permissions MODE','/plan on|off','/plan revise TEXT','/approve','/reject [REASON]','/goals','/goals add TEXT','/goals update ID STATE [TEXT]','/goals cancel ID','/computer status','/computer takeover','/computer done'],'computer':['/help','/exit','/takeover','/done','/status','/approve','/reject','tool_name JSON']}}
if len(sys.argv)==2:Path('src/developer-catalog.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'entrypoints':len(entries),'option_fields':sum(len(e['fields']) for e in entries),'modules':len(modules)+2}))

if len(sys.argv)>2:
 cases=json.loads(Path(sys.argv[2]).read_text());failures=[]
 for case in cases:
  eid=case['entry_id'];entry=next(e for e in entries if e['id']==eid);module=entry['module'];argv=case['argv']
  if eid=='legacy-main':parser=parsers['agent.__main__'];argv=[a for a in argv if a!='--verbose']
  elif module=='localpilot_suite.cli':
   if entry['command']==['upgrade']:parser=captured[-1];argv=argv[1:]
   else:
    parser=parsers['localpilot_service.cli']
    argv=[a for a in argv if not a.startswith('--companion-model-path=')]
  else:parser=parsers[module]
  try:real_parse(parser,argv)
  except SystemExit as exc:failures.append({'entry_id':eid,'field':case['field'],'exit':exc.code})
 value={'evidence_kind':'ORIGINAL_ARGPARSE_ONLY_NO_EXECUTION','case_count':len(cases),'passed':len(cases)-len(failures),'failures':failures,'source_commit':value['source_commit']}
 Path('docs/evidence/runs/v0.2.0/developer-parser-validation.json').write_text(json.dumps(value,indent=2)+'\n')
 print(json.dumps(value))
 if failures:sys.exit(1)
