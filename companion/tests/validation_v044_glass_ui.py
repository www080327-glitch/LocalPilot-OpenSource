"""Real native menu/popover + authenticated Task API, SCRIPTED inference only."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from companion.runtime.daily_trial import ROOT,SERVICE_SOURCE
sys.path.insert(0,str(SERVICE_SOURCE))
from companion.tests.test_v044_service import ServiceContractTests
from tests.test_runtime_api import Backend, answer
from agent.backends import BackendCapabilities,BackendChunk
from companion.config import Config,PrivateData
from companion import cli
from companion.ui.build import launch_ui


class HeldBackend(Backend):
    capabilities=BackendCapabilities(supports_tool_calling=True,supports_streaming=True)
    def __init__(self):super().__init__();self.release=threading.Event()
    def stream(self,messages,**kwargs):
        self.requests.append({'scripted':True});yield BackendChunk('text','合成界面测试')
        self.release.wait(40)
        yield BackendChunk('response',response=answer('合成界面测试结束'))


def main():
    name='glass-ui-'+uuid.uuid4().hex[:8]
    root=PrivateData(ROOT/'companion/.data'/name);output=PrivateData(ROOT/'companion/evidence/v0.4.4'/name)
    fixture=ServiceContractTests(methodName='test_authenticated_health_checks_subject_and_persistence');fixture.setUp()
    backend=HeldBackend();fixture.backend=backend
    fixture.server.catalog['localpilot'].update(reasoning_only=True,prompt_profile='minimal_0',local_model_lifecycle={'release_after_task':True,'control_surface_required':True})
    c=replace(fixture.config,data_dir=str(root.root/'host'),localpilot_expected_local_model='script-provider',
        localpilot_analysis_route='localpilot',localpilot_task_timeout_seconds=120,low_power_policy='always')
    filename=root.file('config.json');root.write(filename.name,json.dumps(asdict(c),indent=2))
    os.environ["COMPANION_UI_DIAGNOSTICS"]="1"
    report={'model_evidence':'MOCK_ONLY','ui_evidence':'REAL_NATIVE_APPKIT_MACOS27','snapshots':[]}
    try:
        cli.start(c,str(filename));report['prepared']=cli.client(c,{'command':'ask','text':'Explain a synthetic public UI test'})
        report['ui']=launch_ui(c);started=time.monotonic()
        print(json.dumps({'native_ui_started':report['ui']['pid'],'path':str(root.root),'evidence':str(output.root)}),flush=True)
        for i in range(45):
            snapshot=cli.client(c,{'command':'ui_snapshot'})
            control=snapshot.get('inference_control',{})
            report['snapshots'].append({'at_seconds':time.monotonic()-started,'control':control})
            if i==3:
                import psutil
                try:
                    process=psutil.Process(report['ui']['pid']); print(json.dumps({'ui_process_status':process.status()}),flush=True)
                except psutil.Error:print('ui_process_exited_early',flush=True)
            if i==20:
                report['continued_after_auto_collapse']=control.get('phase')=='running'
                print(json.dumps({'continued_after_auto_collapse':report['continued_after_auto_collapse']}),flush=True)
            if control.get('phase') in {'stopping','draining','finished','stopped','blocked'}:
                backend.release.set();print('explicit_stop_or_finish',flush=True);time.sleep(2);break
            time.sleep(1)
        backend.release.set();time.sleep(2)
        report['final']=cli.client(c,{'command':'ui_snapshot'}).get('inference_control')
    finally:
        backend.release.set();cli.stop(c);fixture.tearDown()
        output.write('report.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
