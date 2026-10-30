"""Final installed b12/b9: actual DSH model, project Skill, MCP and real files."""
from pathlib import Path
import json,os,subprocess,time,re
from agent.cloud_credentials import resolve_deepseek_key
root=Path(__file__).resolve().parents[1];out=root/'docs/evidence/permission-agent-20261024';authorization=json.loads((out/'dsh-final-authorization.json').read_text());sid=authorization['session_id']
text='Use list_entries on the authorized folder, inspect_file source.txt for its actual SHA-256, make_directory sorted, move_file source.txt to sorted/source.txt using that hash, then copy_file sorted/source.txt to copied.txt using its actual hash. Verify both targets with inspect_file. Only these test files. No shell, deletion, overwriting or delegation. Report exact receipts, physical verification and any failure or UNKNOWN. Never replay an uncertain effect.'
prompt='Load $localpilot-agent. Use only LocalPilot MCP tools for actual work. First call localpilot_capabilities and inspect the authorized session/effective_scope. Submit exactly one task with input '+json.dumps(text)+' session_id '+sid+' model desktop-file-agent-v1 origin_agent dsh-installed-final parent_task_id permission-agent-20261024 idempotency_key dsh-installed-b12-final-v1. Follow actual localpilot_events and localpilot_result until settled. Then repeat the EXACT submit body and key and confirm the same ID, no extra side effects. Report Task/Session IDs and file_operation_verification. Do not approve or continue. If host denies, report Host Denied; never bypass through other tools, shell or credentials.'
key=resolve_deepseek_key(key_file=Path.home()/'Desktop/aic竞赛/LocalPilot/.localpilot/secrets/deepseek.key');env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ['OPERATOR','RESOURCE_TOKEN','LOCALPILOT_TOKEN','DEEPSEEK_API_KEY'])};env['DEEPSEEK_API_KEY']=key
start=time.monotonic()
try:
 r=subprocess.run(['/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh','headless','--patch',str(root/'.localpilot/dsh.patch.json'),'--json',prompt],cwd=root,env=env,capture_output=True,text=True,timeout=180);raw=r.stdout+'\n'+r.stderr;report={'exit':r.returncode,'evidence_kind':'ACTUAL_DSH_MODEL_PROJECT_SKILL_MCP_INSTALLED_B12_REAL_FILES'}
except subprocess.TimeoutExpired as e:raw=(e.stdout or b'').decode() if isinstance(e.stdout,bytes) else e.stdout or '';report={'status':'HOST_TIMEOUT'}
raw=raw.replace(key,'[REDACTED_PROVIDER_CREDENTIAL]');raw=re.sub(r'sk-[A-Za-z0-9_-]{16,}','[REDACTED_PROVIDER_CREDENTIAL]',raw)
(out/'dsh-installed-final-redacted.jsonl').write_text(raw);report['seconds']=time.monotonic()-start;(out/'dsh-installed-final-attempt.json').write_text(json.dumps(report,indent=2));print(report)
