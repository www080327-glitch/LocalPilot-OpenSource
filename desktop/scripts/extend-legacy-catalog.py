"""Index every tracked historical executable Python entry point without importing it.
Tests and retained raw evidence are not product entry points. Unresolved dynamic CLI
expressions are reported, with quoted additional argv available only in terminal preview.
"""
import ast,json,subprocess,sys,hashlib
from pathlib import Path
(Path(__file__).resolve().parents[1]/'docs/evidence/runs/v0.2.0').mkdir(parents=True,exist_ok=True)
root=Path(sys.argv[1]);p=Path('src/developer-catalog.json');catalog=json.loads(p.read_text());entries=[e for e in catalog['entrypoints'] if not e['id'].startswith('source:')];catalog['entrypoints']=entries;known={e['source'] for e in entries}
def literal(n):
 try:return ast.literal_eval(n)
 except Exception:return None
inventory=[]
for name in subprocess.check_output(['git','ls-files','*.py'],cwd=root,text=True).splitlines():
 if name.startswith(('desktop/','tests/','docs/','research/')) or '/tests/' in name or Path(name).name.startswith('test_'):continue
 text=(root/name).read_text();tree=ast.parse(text)
 has_parser='ArgumentParser' in text
 has_main=any(isinstance(n,ast.If) and '__main__' in ast.unparse(n.test) for n in tree.body)
 has_argv=any(isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='sys' and n.attr=='argv' for n in ast.walk(tree))
 if not has_parser and not has_main and not has_argv:continue
 if name in known:
  inventory.append({'source':name,'coverage':'ORIGINAL_ARGPARSE_CAPTURE'});continue
 fields=[];seen=set();unresolved=[]
 for n in ast.walk(tree):
  if not isinstance(n,ast.Call) or not isinstance(n.func,ast.Attribute) or n.func.attr!='add_argument':continue
  opts=[literal(a) for a in n.args]
  if not opts or any(not isinstance(o,str) for o in opts):unresolved.append(ast.unparse(n));continue
  kw={k.arg:k.value for k in n.keywords if k.arg};flags=[s for s in opts if s.startswith('-')];dest=literal(kw['dest']) if 'dest' in kw else (flags[-1].lstrip('-').replace('-','_') if flags else opts[0])
  if dest in seen:continue
  seen.add(dest);action=literal(kw['action']) if 'action' in kw else 'store';kind=ast.unparse(kw['type']) if 'type' in kw else 'str';choices=literal(kw['choices']) if 'choices'in kw else None
  if 'choices'in kw and choices is None:unresolved.append('choices: '+ast.unparse(kw['choices']))
  if isinstance(choices,tuple):choices=list(choices)
  fields.append({'key':f'static-{len(fields)}-{dest}','dest':dest,'options':flags,'flag':next((f for f in flags if f.startswith('--')),flags[0] if flags else None),'type':'boolean' if action in ['store_true','store_false'] else 'integer' if kind=='int' else 'number' if kind=='float' else 'text','action':action,'choices':choices,'required':bool(literal(kw['required'])) if 'required'in kw else not flags and ('nargs'not in kw or literal(kw['nargs']) not in ['*','?']),'nargs':literal(kw['nargs']) if 'nargs'in kw else None,'default':literal(kw['default']) if 'default'in kw else None,'help':literal(kw['help']) if 'help'in kw else '', 'group':0})
 # A fixed script plus reviewed/quoted tokens. This never becomes an executable IPC.
 fields.append({'key':'static-additional-argv','dest':'附加 CLI 参数（每行一个参数，仅预览）','options':[],'flag':None,'type':'text','action':'raw_argv','choices':None,'required':False,'nargs':'*','default':None,'help':'For dynamic argparse branches or scripts that read sys.argv directly. Each token remains shell-quoted. Only the original CLI may validate or execute it.','group':0})
 entries.append({'id':'source:'+name,'module':None,'label':'历史研究 / '+name,'command':[],'fields':fields,'source':name,'source_sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),'execution':'trusted_terminal_only','schema_evidence':'STATIC_AST_NOT_RUNTIME_VALIDATED','unresolved_expressions':unresolved})
 inventory.append({'source':name,'coverage':'STATIC_AST_TERMINAL_ONLY','unresolved':unresolved})
catalog['metrics']={'entrypoints':len(entries),'parameter_fields':sum(len(e['fields'])for e in entries),'original_argparse_entrypoints':99,'original_argparse_fields':480,'tracked_executable_source_files':len(inventory)}
p.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
Path('docs/evidence/runs/v0.2.0/full-cli-inventory.json').write_text(json.dumps({'source_commit':catalog['source_commit'],'metrics':catalog['metrics'],'files':inventory,'all_indexed':True,'execution':'No historical experiment was executed by this inventory'},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(catalog['metrics']))
