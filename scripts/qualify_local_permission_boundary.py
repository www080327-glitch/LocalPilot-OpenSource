"""Real files with deterministic tool calls and scripted host decisions, not GUI/model E2E."""
from pathlib import Path
import hashlib,json,time
from agent.registry import create_default_registry
from agent.scope_permissions import configure
out=Path('docs/evidence/desktop-permission-parity-20261024');rows=[]
for mode,riskmode in [('request','approve-mutations'),('workspace','workspace-auto'),('full','full-permission')]:
 base=(out/'local-boundary-files'/mode).resolve();work=base/'work';outside=base/'outside';work.mkdir(parents=True);outside.mkdir()
 for folder in (work,outside):(folder/'source.txt').write_text('PARITY-PUBLIC-FIXTURE\n')
 r=create_default_registry(work,permission_mode=riskmode,file_operations=True);configure(r,mode)
 cases={'read_inside':[('read_file',{'path':'source.txt'})],'read_outside':[('read_file',{'path':str(outside/'source.txt')})],
 'write_inside':[('apply_patch',{'changes':[{'path':'new.txt','operation':'create','content':'parity'}]})],
 'write_outside':[('apply_patch',{'changes':[{'path':str(outside/'new.txt'),'operation':'create','content':'parity'}]})],
 'organize':[('make_directory',{'path':'sorted'}),('copy_file',{'source':'source.txt','destination':'copy.txt','expected_sha256':hashlib.sha256(b'PARITY-PUBLIC-FIXTURE\n').hexdigest()}),('move_file',{'source':'copy.txt','destination':'sorted/renamed.txt','expected_sha256':hashlib.sha256(b'PARITY-PUBLIC-FIXTURE\n').hexdigest()})],
 'shell':[('execute',{'argv':['echo','shell-ok']})]}
 for name,calls in cases.items():
  start=time.perf_counter();requests=0;values=[]
  for tool,args in calls:
   value=r.call(tool,args)
   if isinstance(value,dict) and value.get('status')=='approval_required':
    requests+=1;value=r.call(tool,args,approved=True,scope_approval=value.get('scope_request'))
   values.append(value)
  rows.append({'mode':mode,'case':name,'results':values,'scripted_host_approval_requests':requests,'seconds':time.perf_counter()-start,'popups':None,'human_interactions':None})
(out/'local-boundary.json').write_text(json.dumps({'kind':'REAL_FILES_DETERMINISTIC_TOOLS_SCRIPTED_HOST_NOT_GUI_OR_MODEL','rows':rows},indent=2)+'\n')
print([{'mode':r['mode'],'case':r['case'],'scripted_host_approval_requests':r['scripted_host_approval_requests']} for r in rows])
