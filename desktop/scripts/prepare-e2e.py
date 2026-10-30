"""Prepare an isolated Suite home using released CLI and JSON host configuration.
No imports from Core/Companion internals; no database access; provider credential is referenced only.
"""
import json,os,subprocess,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RELEASE=ROOT.parent/'LocalPilot-suite-release-20261021'
CLI=Path.home()/'.local/share/localpilot-desktop-runtime/bin/localpilot'
if not CLI.exists():CLI=RELEASE/'published-env/bin/localpilot'
HOME=Path.home()/'.local/share/localpilot-desktop-e2e'
WORK=Path.home()/'LocalPilotDesktopWorkspace'
HOME.mkdir(parents=True,mode=0o700,exist_ok=True);WORK.mkdir(mode=0o700,exist_ok=True)
fixture=WORK/'fixture.txt'
if not fixture.exists():fixture.write_text('LOCALPILOT-DESKTOP-RC2-VERIFIED\n')
# Never overwrite user-created configuration. Repeated runs only print a connection location.
if not (HOME/'connection.json').exists():
 subprocess.run([str(CLI),'--home',str(HOME),'init','--workspace',str(WORK),'--model','Qwen3.6-35B-A3B-4bit','--base-url','http://127.0.0.1:1234/v1','--port','8876'],check=True,capture_output=True)
 config=json.loads((HOME/'service.json').read_text())
 cloud_key=ROOT.parent/'LocalPilot/.localpilot/secrets/deepseek.key'
 # A bounded, fixture-only cloud Agent route. Do not add write access or an operator grant to the GUI.
 base={'workspace':str(WORK),'backend':{'kind':'deepseek','model':'deepseek-flash','key_file':str(cloud_key),'timeout':40},'thinking':'none','cloud_egress':'CLOUD_ALLOWED','cloud_egress_paths':['fixture.txt'],'permissions':'approve-mutations','prompt_profile':'standard','tool_profile':'full','capabilities':{'read':True,'write':False,'execute':False},'budgets':{'max_steps':5,'max_tool_calls':4,'max_output_tokens':1024},'verification':{'id':'desktop-fixture-current','files':{'fixture.txt':hashlib.sha256(fixture.read_bytes()).hexdigest()},'required_text':'LOCALPILOT-DESKTOP-RC2-VERIFIED'}}
 if cloud_key.is_file():
  config['routes']['gui-cloud-read']=base
  reasoning={**base,'reasoning_only':True,'prompt_profile':'minimal_0','tool_profile':'compact','capabilities':{'read':False,'write':False,'execute':False}}
  reasoning.pop('verification',None);reasoning['cloud_egress']='REQUIRES_APPROVAL';config['routes']['gui-cloud-question']=reasoning
  approval={**base,'capabilities':{'read':True,'write':True,'execute':False},'cloud_egress_paths':['fixture.txt','approved.txt'],'verification':{'id':'desktop-approved-file','files':{'approved.txt':hashlib.sha256(b'DESKTOP-APPROVAL-OK\n').hexdigest()},'required_text':'DESKTOP-APPROVAL-OK'}}
  config['routes']['gui-cloud-approval']=approval
 # Public route that cannot execute: verifies explicit unavailability rejection.
 config['routes']['gui-unavailable']={'workspace':str(WORK),'backend':{'kind':'unavailable','model':'unavailable-fixture'},'deployment_status':'not_deployed','cloud_egress':'LOCAL_ONLY'}
 http=next(c for c in config['clients'] if c['subject']=='http')
 http['routes'].update({'unavailable-fixture':'gui-unavailable'})
 if cloud_key.is_file():http['routes'].update({'deepseek-read':'gui-cloud-read','deepseek-question':'gui-cloud-question','deepseek-approval':'gui-cloud-approval'})
 # Keep the default local route in the catalog, but no inference is triggered automatically.
 path=HOME/'service.json';path.write_text(json.dumps(config,indent=2));path.chmod(0o600)
 # Sharing the ordinary HTTP namespace with CLI is intentional for the concurrent-client check.
print(json.dumps({'suite_home':str(HOME),'cli':str(CLI),'workspace':str(WORK),'fixture':'fixture.txt','existing_config_preserved':True,'cloud_credential':'host reference only; not read by this script'}))
