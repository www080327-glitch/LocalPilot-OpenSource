"""Actual installed DSH model -> project MCP -> Core real file operations."""
from pathlib import Path
import json,os,subprocess,time,re
from agent.cloud_credentials import resolve_deepseek_key
root=Path(__file__).resolve().parents[1];out=root/'docs/evidence/desktop-permission-parity-20261024';auth=json.loads((out/'dsh-project-authorization-v2.json').read_text());sid=auth['session_id'];caller=Path.home()/'.local/share/localpilot-permission-parity-caller-v2'
text='Use list_entries on the authorized public fixture folder. inspect_file source.txt, make_directory sorted, move_file source.txt to sorted/source.txt using its actual SHA-256, then copy_file sorted/source.txt to copied.txt using that hash. Verify both targets with inspect_file. Only these generated files. No shell, deletion, overwriting or delegation. Report receipts, physical verification and any failure or UNKNOWN. Never replay an uncertain effect.'
prompt='Load $localpilot-agent. Use only LocalPilot MCP tools for actual work. First localpilot_capabilities. Submit one task with input '+json.dumps(text)+' session_id '+sid+' model desktop-parity origin_agent dsh-parity parent_task_id desktop-permission-parity-20261024 idempotency_key dsh-parity-workspace-v2. Follow localpilot_events and localpilot_result until settled. Then repeat the EXACT submit body and idempotency_key once and confirm the same Task ID without new effects. Never approve or continue. If host denies, report Host Denied; do not bypass via shell, HTTP or another identity.'
key=resolve_deepseek_key(key_file=Path.home()/'Desktop/aic竞赛/LocalPilot/.localpilot/secrets/deepseek.key')
env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ['OPERATOR','RESOURCE_TOKEN','LOCALPILOT_TOKEN','DEEPSEEK_API_KEY'])};env['DEEPSEEK_API_KEY']=key;start=time.monotonic()
try:
 r=subprocess.run(['/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh','headless','--patch',str(caller/'.localpilot/dsh.patch.json'),'--json',prompt],cwd=caller,env=env,capture_output=True,text=True,timeout=180);raw=r.stdout+'\n'+r.stderr;report={'exit':r.returncode,'kind':'ACTUAL_INSTALLED_DSH_0.2.1_RC2_REAL_MODEL_MCP_CORE_B14_PUBLIC_FILES'}
except subprocess.TimeoutExpired as e:
 raw=e.stdout or '';raw=raw.decode() if isinstance(raw,bytes) else raw;report={'status':'TIMEOUT','kind':'ACTUAL_INSTALLED_DSH_MODEL'}
raw=raw.replace(key,'[REDACTED_PROVIDER_CREDENTIAL]');raw=re.sub(r'sk-[A-Za-z0-9_-]{16,}','[REDACTED_PROVIDER_CREDENTIAL]',raw)
(out/'dsh-model-v2-redacted.jsonl').write_text(raw);report['seconds']=time.monotonic()-start;(out/'dsh-model-v2-attempt.json').write_text(json.dumps(report,indent=2)+'\n');print(report)
