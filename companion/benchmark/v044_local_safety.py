"""One real cached Qwen35B Task with a live native UI stop surface; no cloud."""
from dataclasses import asdict
import json
from pathlib import Path
import time

from companion.config import Config, PrivateData
from companion import cli
from companion.ui.build import launch_ui
from companion.runtime.daily_trial import ROOT, provision


def main():
    root=ROOT/'companion/.data/v044-local-safety-fourth'
    private=PrivateData(root)
    output=PrivateData(ROOT/'companion/evidence/v0.4.4/local-safety-fourth')
    config=Config(data_dir=str(private.root/'host'),backend='disabled',native_observation_enabled=False,
        localpilot_task_timeout_seconds=110,low_power_policy='always',dnd=True)
    config_file=private.file('config.json');private.write('config.json',json.dumps(asdict(config),indent=2))
    _,_,tokens=provision(ROOT/'companion/.data/daily-trial/private-service')
    import os
    os.environ.update(tokens)
    report={'evidence_kind':'REAL_COMPANION_LOCALPILOT_CACHED_QWEN35B_NATIVE_CONTROL',
        'cloud_requests':0,'downloads':0,'question':'Reply with only the number 12 for six plus six.', 'snapshots':[]}
    try:
        cli.start(config,str(config_file))
        prepared=cli.client(config,{'command':'ask','text':report['question']})
        report['prepared']=prepared
        if prepared.get('status')!='inference_prepared':raise RuntimeError('No controllable local inference prepared')
        if prepared['control']['required_confirmations']:raise RuntimeError('Real run requires a user resource confirmation; not auto-accepted')
        report['ui']=launch_ui(config)
        deadline=time.monotonic()+150;last=None
        while time.monotonic()<deadline:
            value=cli.client(config,{'command':'ui_snapshot'},timeout=10)
            control=value.get('inference_control',{})
            report['snapshots'].append({'control':control,'system_resources':value.get('system_resources')})
            if control.get('phase')!=last:
                last=control.get('phase');print(json.dumps({'phase':last,'task_id':control.get('task_id') or None}),flush=True)
            if control.get('phase') in {'finished','blocked','stopped','stop_unconfirmed'}:
                report['final']=control;break
            time.sleep(1)
        else:raise RuntimeError('Bounded local task did not settle')
        final=report['final'];status=final.get('last_status',{})
        report['runtime_pass']=(status.get('status')=='completed' and status.get('quiescent') is True and
            '12' in status.get('agent_response','') and status.get('model_resource',{}).get('model_process_alive') is False)
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc);report['runtime_pass']=False
        print(json.dumps({'error':report['error']}),flush=True)
    finally:
        cli.stop(config)
        output.write('report.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'runtime_pass':report.get('runtime_pass'),'evidence':str(output.root)}),flush=True)


if __name__=='__main__':main()
