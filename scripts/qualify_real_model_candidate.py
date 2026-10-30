"""Real cached Qwen35, isolated official Core/worker, fixed host-verified tasks.

No daily model service configuration, cloud provider, platform account, downloads
or original user workspace is changed. Existing power/memory/swap guards remain.
"""
import argparse
from copy import deepcopy
import hashlib
import http.client
from urllib.parse import urlsplit
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from uuid import uuid4

MODEL='Qwen3.6-35B-A3B-4bit'
REVISION='38740b847e4cb78f352aba30aa41c76e08e6eb46'
TERMINAL={'completed','incomplete','failed','cancelled','timed_out'}

def checksum(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def free_port():
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));return listener.getsockname()[1]

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=True,indent=2)+'\n');path.chmod(0o600)

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();bundle=Path(a.bundle).resolve(strict=True);out=Path(a.out).resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    installation=out/'core';installation.mkdir(mode=0o700);workspace=out/'workspace';workspace.mkdir(mode=0o700)
    marker='LOCALPILOT-35B-READ-20261028';source=workspace/'source.txt';source.write_text(marker+'\n17 25\n')
    approved=b'LOCALPILOT-35B-WRITE-OK\n';expected=hashlib.sha256(approved).hexdigest()
    env={k:v for k,v in os.environ.items() if not (k.startswith(('LOCALPILOT_','DEEPSEEK_','OPENAI_','OMLX_')) or k in {'PYTHONHOME','PYTHONPATH'})}
    env.update(PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1')
    cli=bundle/'localpilot';daily=[Path.home()/'.omlx/settings.json',Path.home()/'.omlx/model_settings.json']
    before={str(path):checksum(path) for path in daily if path.is_file()}
    report={'kind':'REAL_LOCAL_MODEL_NOT_SCRIPTED','model':MODEL,'revision':REVISION,'cloud':'NOT_RUN','real_qq':'NOT_RUN','real_wechat':'NOT_RUN','cases':[], 'daily_configuration_before':before}
    def record():write(out/'acceptance.json',report)
    def invoke(args,timeout=90,allow_failure=False):
        result=subprocess.run([str(cli),'--home',str(installation),'--json',*args],env=env,capture_output=True,text=True,timeout=timeout)
        values=[]
        for line in result.stdout.splitlines():
            try:values.append(json.loads(line))
            except ValueError:pass
        value=values[-1] if values else {'error':'NON_JSON_OR_NO_RESULT'}
        if result.returncode and not allow_failure:raise RuntimeError('CORE_CLI_'+str(result.returncode)+':'+str(value.get('error','operation_not_completed')))
        return value
    def snapshot(task_id):
        connection=json.loads((installation/'connection.json').read_text());values={}
        for line in (installation/'clients.env').read_text().splitlines():
            name,value=line.removeprefix('export ').split('=',1);values[name]=value
        origin=urlsplit(connection['url']);assert origin.scheme=='http' and origin.hostname=='127.0.0.1'
        client=http.client.HTTPConnection(origin.hostname,origin.port,timeout=10)
        try:
            client.request('GET','/localpilot/v1/tasks/'+task_id,headers={'Authorization':'Bearer '+values[connection['token_env']]})
            response=client.getresponse();value=json.loads(response.read())
            if response.status!=200:raise RuntimeError('READ_ONLY_TASK_QUERY_HTTP_'+str(response.status))
            return value
        finally:client.close()
    def settled(task_id,deadline):
        while time.monotonic()<deadline:
            value=snapshot(task_id)
            if value.get('status')=='requires_approval' or value.get('quiescent') and value.get('status') in TERMINAL|{'requires_human'}:return value
            time.sleep(2)
        return snapshot(task_id)
    def receipts(task):
        return sum(row.get('payload',{}).get('ok') is True and row.get('receipt_reused') is False
            and row.get('side_effect_status')!='unknown' for row in task.get('tools',[]))
    def run_case(name,command,model,text,decision=None):
        started=time.monotonic();key='qualification-'+name+'-'+uuid4().hex
        initial=invoke([command,text,'--model',model,'--key',key,'--timeout','360','--detach'],timeout=90)
        task_id=initial.get('id')
        if not task_id:raise RuntimeError('TASK_ID_NOT_CONFIRMED_NO_RESUBMISSION')
        value=settled(task_id,time.monotonic()+370)
        item={'name':name,'official_task_id':task_id,'initial_status':initial.get('status'),'pending_seen':value.get('status')=='requires_approval'}
        if decision:
            item['file_absent_before_decision']=not (workspace/('approved.txt' if decision=='approve' else 'rejected.txt')).exists()
            action=value.get('required_action') or {}
            if value.get('status')=='requires_approval' and isinstance(action.get('id'),str):
                serialized=json.dumps(action,ensure_ascii=False)
                # Review the concrete Core action. Never approve an unexpected executable/target.
                target='approved.txt' if decision=='approve' else 'rejected.txt'
                safe=target in serialized and 'apply_patch' in serialized and not any(token in serialized for token in ['"name": "execute"','../','/Users/'])
                item['reviewed_action_matches_fixed_fixture']=safe
                if decision=='approve' and not safe:
                    item['approval_withheld']=True
                else:
                    invoke(['task',decision,task_id,'--action-id',action['id'],'--operator-token-env','LOCALPILOT_OPERATOR_TOKEN'])
                    value=settled(task_id,time.monotonic()+370)
            else:item['decision_not_run']='NO_CURRENT_CORE_APPROVAL'
        write(out/(name+'-task.json'),value)
        item.update(status=value.get('status'),quiescent=value.get('quiescent'),successful_non_reused_receipts=receipts(value),core_verification=value.get('verification_summary'),elapsed_seconds=round(time.monotonic()-started,3))
        if name=='chat':item['host_oracle']=str((value.get('result') or {}).get('text','')).find('LOCALPILOT-35B-CHAT-OK')>=0
        elif name=='read':item['host_oracle']=marker in str((value.get('result') or {}).get('text','')) and checksum(source)==hashlib.sha256((marker+'\n17 25\n').encode()).hexdigest() and receipts(value)>0
        elif name=='approve':item['host_oracle']=(workspace/'approved.txt').is_file() and checksum(workspace/'approved.txt')==expected and receipts(value)>0 and item.get('file_absent_before_decision') is True
        else:item['host_oracle']=not (workspace/'rejected.txt').exists() and item.get('file_absent_before_decision') is True
        item['pass']=item['host_oracle'] and (value.get('status')=='completed' if name!='reject' else value.get('status') in TERMINAL)
        report['cases'].append(item);record();print(json.dumps(item),flush=True)
        return value
    try:
        import psutil
        battery=psutil.sensors_battery();report['admission_observed']={'available_memory_bytes':psutil.virtual_memory().available,'ac_power':battery.power_plugged if battery else None,'no_memory_or_power_override':True};record()
        invoke(['init','--workspace',str(workspace),'--model',MODEL,'--managed-qwen35','--port',str(free_port())])
        config_path=installation/'service.json';config=json.loads(config_path.read_text());model_port=free_port()
        for route in config['routes'].values():
            if route.get('managed_local_model'):
                route['managed_local_model']['port']=model_port;route['backend']['base_url']=f'http://127.0.0.1:{model_port}/v1'
            route['engine']='v5';route['budgets']={'max_steps':8,'max_tool_calls':8,'max_output_tokens':1024,'max_token_units':131072}
        template=deepcopy(config['routes']['companion-execution'])
        read=deepcopy(template);read['capabilities']={'read':True,'write':False,'execute':False};read['verification']={'id':'fixed-read','files':{'source.txt':checksum(source)},'required_text':marker}
        approved_route=deepcopy(template);approved_route['verification']={'id':'fixed-approved-file','files':{'approved.txt':expected},'required_text':'LOCALPILOT-35B-WRITE-OK'}
        rejected_route=deepcopy(template)
        config['routes'].update({'fixed-read':read,'fixed-approve':approved_route,'fixed-reject':rejected_route})
        for principal in config['clients']:
            if principal['subject']=='local':principal['routes'].update({'fixed-read':'fixed-read','fixed-approve':'fixed-approve','fixed-reject':'fixed-reject'})
        write(config_path,config)
        # Detached Core; only the already-approved private cached worker is loaded on demand.
        request={'version':1,'operation':'service_control','args':{'module':'core','action':'start','confirmed':True}}
        invoke(['product-control','--request-json',json.dumps(request)],timeout=150)
        report['isolated_model_port']=model_port;report['bundle_modules']=json.loads((bundle/'verified-modules.json').read_text())['actual_module_versions'];record()
        value=run_case('chat','ask','companion-reasoning','用中文回复一行：LOCALPILOT-35B-CHAT-OK。不调用工具。')
        if value.get('status')=='completed':
            run_case('read','agent','fixed-read','请读取 source.txt，并列出当前目录。用中文报告第二行两个数字的和，原样包含第一行标记。不要修改文件或运行 Shell。')
            value=run_case('approve','agent','fixed-approve','用 apply_patch 创建 approved.txt，文件内容严格为 LOCALPILOT-35B-WRITE-OK 后加一个换行。完成后读取核对，并回复 LOCALPILOT-35B-WRITE-OK。不要运行 Shell。','approve')
            if value.get('status') in TERMINAL:run_case('reject','agent','fixed-reject','请用 apply_patch 创建 rejected.txt，写入 REJECTED-SHOULD-NOT-EXIST。不要运行 Shell。','reject')
        report['status']='MEASURED_REVIEW_REQUIRED';record()
    except Exception as error:
        report.update(status='FAILED_OR_BLOCKED',error=str(error)[:800]);record();print(json.dumps({'status':report['status'],'error':report['error']}),flush=True)
    finally:
        try:
            request={'version':1,'operation':'service_control','args':{'module':'core','action':'stop','confirmed':True}}
            report['stop_result']=invoke(['product-control','--request-json',json.dumps(request)],allow_failure=True)
        except Exception:report['stop_result']={'status':'UNKNOWN','automatic_force_kill':False}
        after={str(path):checksum(path) for path in daily if path.is_file()};report['daily_configuration_unchanged']=after==before
        report['unknown_policy']='No unknown task is resubmitted, approved or cleared automatically';record()

if __name__=='__main__':main()
