"""Static public command audit against the frozen release owning sources.
Does not execute state-changing commands. Options and runtime qualification are separate.
"""
import ast,json,sys,hashlib
from pathlib import Path
(Path(__file__).resolve().parents[1]/'docs/evidence/runs/v0.2.0').mkdir(parents=True,exist_ok=True)
source=Path(sys.argv[1])
core=ast.parse((source/'localpilot_service/cli.py').read_text())
comp=ast.parse((source/'companion/cli.py').read_text())
def collect(tree, function):
 node=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==function)
 names=[]
 for n in ast.walk(node):
  if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='add_parser' and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str):names.append(n.args[0].value)
  if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='name' and isinstance(n.iter,(ast.List,ast.Tuple)):
   if any(isinstance(k,ast.Call) and isinstance(k.func,ast.Attribute) and k.func.attr=='add_parser' for k in ast.walk(n)):
    names.extend(k.value for k in n.iter.elts if isinstance(k,ast.Constant) and isinstance(k.value,str))
 return sorted(set(names))
commands=json.loads(Path('src/cli-tools.json').read_text()); ids={c['id'] for c in commands}
core_names=collect(core,'parser'); comp_names=collect(comp,'main')
core_map={'init':'native initialize_suite (basic local/managed presets; advanced credentials/connect flags require trusted setup)','ask':'Composer + reasoning_only Core route','chat':'same Core Session, new turn only','agent':'Composer + tool-capable route','task':'task show/watch/cancel and trusted approve/reject/resume','approve':'trusted terminal handoff with current action ID','reject':'trusted terminal handoff with current action ID','resume':'trusted terminal handoff only SAFE_TO_RESUME','show':'Suite tools task-show','watch':'native SSE / Suite tools task-watch','cancel':'native cancel / Suite tools task-cancel','_serve':'INTERNAL_EXCLUDED'}
core_rows=[{'command':c,'entry':('Suite tools '+c) if c in ids else core_map.get(c,'MISSING')} for c in core_names]
comp_map={'run':'managed Companion start (foreground terminal process is not embedded)'}
comp_rows=[{'command':c,'entry':('Suite tools companion-'+c) if 'companion-'+c in ids else comp_map.get(c,'MISSING')} for c in comp_names]
value={'evidence_kind':'STATIC_COMMAND_SURFACE_AUDIT','source_commit':'3f0e7b5e5c8c6731a98369c1973f59ad7ba965f8','core':core_rows,'companion':comp_rows,'suite_upgrade':'native wheel plan and reviewed execute for core/companion/suite','suite_tool_entries':len(commands),'all_flags_and_real_workflows_qualified':False,'limits':['init advanced --connect/--token-env/--api-key-env/--cloud-key-file/--companion-model-path remain trusted installation setup','Composer timeout fixed at 600s; custom --timeout not surfaced','custom --key is replaced by native durable key and original-request recovery','state-changing Companion commands have schema/confirmation tests, not full per-command real E2E','independent localpilot-core legacy commands and localpilot-adapter are not Suite command parity']}
assert all(r['entry']!='MISSING' for r in core_rows+comp_rows),value
Path('docs/evidence/runs/v0.2.0/cli-coverage.json').write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'core_commands':len(core_rows),'companion_commands':len(comp_rows),'suite_tool_entries':len(commands),'missing_command_entries':0,'all_flags_and_workflows_qualified':False}))
