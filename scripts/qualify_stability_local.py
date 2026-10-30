"""Revision 2 real OS/file/network matrix; scripted approvals, no GUI/model claim."""
from pathlib import Path
from agent.registry import create_default_registry
from agent.scope_permissions import configure
from agent.host_tools import register
import json
out=Path('docs/evidence/stability-20261025');rows=[]
for mode,risk in [('request','approve-mutations'),('workspace','workspace-auto'),('full','full-permission')]:
 base=(out/'local-native-final'/mode).resolve();work=base/'work';outside=base/'outside';work.mkdir(parents=True);outside.mkdir()
 for p in [work,outside]:(p/'source.txt').write_text('PUBLIC-STABILITY\n')
 r=create_default_registry(work,permission_mode=risk,file_operations=True);configure(r,mode,revision=2);register(r,mode,[])
 cases={'read_inside':('read_file',{'path':'source.txt'}),'read_outside':('read_file',{'path':str(outside/'source.txt')}),'write_inside':('apply_patch',{'changes':[{'path':'new.txt','operation':'create','content':'proof'}]}),'write_outside':('apply_patch',{'changes':[{'path':str(outside/'new.txt'),'operation':'create','content':'proof'}]}),'shell':('shell',{'command':'printf shell-ok > shell.txt; cat shell.txt'}),'shell_outside_escalation':('shell',{'command':"printf escalation-ok > '"+str(outside/'shell.txt')+"'",'access':'full'}),'network':('http_get',{'url':'https://api.github.com/zen'})}
 for name,(tool,args) in cases.items():
  value=r.call(tool,args);requests=0
  if isinstance(value,dict) and value.get('status')=='approval_required':requests=1;value=r.call(tool,args,approved=True,scope_approval=value.get('scope_request'))
  if name=='network':value={k:v for k,v in value.items() if k!='body'}
  rows.append({'mode':mode,'case':name,'scripted_host_requests':requests,'result':value,'evidence_kind':'REAL_OS_FILES_TOOLS_SCRIPTED_HOST_NO_GUI'})
(out/'local-native-matrix-final.json').write_text(json.dumps({'scope_revision':2,'rows':rows},indent=2)+'\n')
print([(r['mode'],r['case'],r['scripted_host_requests'],r['result'].get('status') if isinstance(r['result'],dict) else 'read') for r in rows])
