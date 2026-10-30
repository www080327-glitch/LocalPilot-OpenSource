"""Actual Codex and DSH model -> installed Skill/MCP -> real LocalPilot provider."""
import argparse,json,os,re,subprocess,sys,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('host',choices=['codex','dsh']);a=p.parse_args()
 caller=Path.home()/'.local/share/localpilot-permission-agent-caller';out=Path(__file__).resolve().parents[1]/'docs/evidence/permission-agent-20261024';report={'host':a.host,'evidence_kind':'ACTUAL_HOST_MODEL_MCP_ATTEMPT','started':time.time()}
 prompt='Use $localpilot-agent from .agents/skills/localpilot-agent/SKILL.md. You must actually load the Skill and call LocalPilot MCP tools. First call localpilot_capabilities. Submit exactly one read-only task with model analysis, input "Read analysis.txt through read_file and return its exact marker. Do not change files or delegate.", idempotency_key "'+a.host+'-permission-real-analysis-v1", origin_agent "'+a.host+'-headless", parent_task_id "permission-agent-20261024". Save task and session IDs. Use localpilot_events for actual progress, then localpilot_result on the same task until quiescent. Report the exact marker and verification. Do not approve or continue, do not read credentials, do not execute LocalPilot tool proposals locally, do not submit a second key. If the host denies a call, report Host Denied and stop; never use shell/HTTP/another identity to bypass the denial.'
 env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ['OPERATOR','RESOURCE_TOKEN','LOCALPILOT_TOKEN','DEEPSEEK_API_KEY'])};secret=None
 if a.host=='codex':
  # Transient MCP configuration only. No global trust or approval policy changes.
  conf=__import__('tomllib').loads((caller/'.codex/config.toml').read_text())['mcp_servers']['localpilot']
  command=['codex','exec','-C',str(caller),'--skip-git-repo-check','--ephemeral','--json','-s','read-only']
  for k,v in conf.items():command+=['-c','mcp_servers.localpilot.'+k+'='+json.dumps(v)]
  command+=[prompt]
 else:
  from agent.cloud_credentials import resolve_deepseek_key
  secret=resolve_deepseek_key(key_file=Path.home()/'Desktop/aic竞赛/LocalPilot/.localpilot/secrets/deepseek.key');env['DEEPSEEK_API_KEY']=secret
  command=['/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh','headless','--patch',str(caller/'.localpilot/dsh.patch.json'),'--json',prompt]
 try:
  result=subprocess.run(command,cwd=caller,env=env,capture_output=True,text=True,timeout=240)
  raw=result.stdout+'\n'+result.stderr;report['exit_code']=result.returncode
 except subprocess.TimeoutExpired as e:
  raw=(e.stdout or b'').decode() if isinstance(e.stdout,bytes) else e.stdout or '';raw+='\n'+((e.stderr or b'').decode() if isinstance(e.stderr,bytes) else e.stderr or '');report['status']='HOST_TIMEOUT'
 if secret:raw=raw.replace(secret,'[REDACTED_PROVIDER_CREDENTIAL]')
 raw=re.sub(r'sk-[A-Za-z0-9_-]{16,}','[REDACTED_PROVIDER_CREDENTIAL]',raw)
 (out/(a.host+'-headless-redacted.jsonl')).write_text(raw)
 report['elapsed_seconds']=time.time()-report['started'];report['transcript']=a.host+'-headless-redacted.jsonl'
 (out/(a.host+'-host-attempt.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
