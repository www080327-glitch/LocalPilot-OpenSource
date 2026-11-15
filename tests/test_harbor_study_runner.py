"""Read real files/processes; protocol fixtures never represent benchmark scores."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from scripts.harbor_preflight import _docker, _guest_disk, _requirements, preflight
from scripts.harbor_study_runner import changed_evidence, continue_process, inspect_existing, reject_live_launcher
from scripts.public_agent_eval import read_json
from tests import test_public_agent_eval as fixtures


class StudyResumeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PublicAgentEvaluationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.populate()
        self.job=self.fixture.study['jobs'][0]
        self.directory=self.fixture.study_dir
        for path in self.fixture.paths.values():
            (path.parent/'config.json').write_text(json.dumps(read_json(path)['config']))

    def inspect(self):
        return inspect_existing(self.directory,self.fixture.study,self.job)

    def test_terminal_error_is_preserved_and_never_selected_for_retry(self):
        path=self.fixture.paths['localpilot',1,'alpha']
        raw=read_json(path)
        raw['exception_info']={'exception_type':'CancelledError'}
        path.write_text(json.dumps(raw))
        missing=self.fixture.paths['localpilot',1,'beta'].parent
        shutil.rmtree(missing)
        original=path.read_bytes()
        result=self.inspect()
        self.assertEqual(result['status'],'RESUMABLE')
        self.assertEqual(result['completed_trials'],1)
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(changed_evidence(self.directory,result['preserved_files']),[])

    def test_unsettled_trial_blocks_instead_of_deleting_directory(self):
        path=self.fixture.paths['localpilot',1,'beta']
        path.unlink()
        raw=path.parent/'unsettled.log'
        raw.write_text('original uncertain effect')
        with self.assertRaisesRegex(ValueError,'must not be replayed'):
            self.inspect()
        self.assertEqual(raw.read_text(),'original uncertain effect')

    def test_changed_prior_evidence_is_detected(self):
        result=self.inspect()
        path=self.fixture.paths['localpilot',1,'alpha']
        path.write_text(path.read_text()+'\n')
        self.assertEqual(changed_evidence(self.directory,result['preserved_files']),[path.relative_to(self.directory).as_posix()])

    def test_duplicate_or_incomplete_result_blocks_resume(self):
        path=self.fixture.paths['localpilot',1,'beta']
        raw=read_json(path)
        raw['finished_at']=None
        path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError,'no terminal result'):
            self.inspect()
        raw['task_name']='alpha'
        path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError,'duplicated'):
            self.inspect()

    def test_preflight_cli_writes_failures_without_starting_a_job(self):
        script=Path(__file__).resolve().parents[1]/'scripts'/'public_agent_eval.py'
        output=self.fixture.root/'preflight.json'
        command=[sys.executable,str(script),'preflight','--study',str(self.directory),'--arm','localpilot',
                 '--repeat','1','--repository',str(self.fixture.repository),
                 '--harbor-repository',str(self.fixture.repository),
                 '--docker-host','unix:///private/tmp/does-not-exist-eval-fixture.sock','--output',str(output)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,2,result.stderr)
        report=read_json(output)
        self.assertFalse(report['ready'])
        self.assertEqual(next(row for row in report['checks'] if row['name']=='sources')['status'],'FAIL')
        self.assertEqual(list((self.directory/'launches').iterdir()),[])

    @unittest.skipUnless(hasattr(signal,'SIGSTOP'),'POSIX stop/continue contract')
    def test_continue_exact_stopped_process_without_starting_another(self):
        import psutil
        command=[sys.executable,'-c','import os,signal,time; os.kill(os.getpid(),signal.SIGSTOP); time.sleep(30)',
                 '--config',str(self.directory/'configs'/f"{self.job['name']}.json")]
        process=subprocess.Popen(command,cwd=self.fixture.root)
        try:
            deadline=time.monotonic()+3
            while psutil.Process(process.pid).status()!=psutil.STATUS_STOPPED and time.monotonic()<deadline:
                time.sleep(0.01)
            with self.assertRaisesRegex(ValueError,'Existing Harbor process'):
                reject_live_launcher(command,self.fixture.root)
            with self.assertRaisesRegex(ValueError,'not the original'):
                continue_process(process.pid,command+['wrong'],self.fixture.root)
            report=continue_process(process.pid,command,self.fixture.root)
            self.assertEqual(report['replayed_trials'],0)
            self.assertEqual(report['processes'][0]['pid'],process.pid)
            self.assertNotEqual(psutil.Process(process.pid).status(),psutil.STATUS_STOPPED)
        finally:
            os.kill(process.pid,signal.SIGCONT)
            process.terminate()
            process.wait(timeout=3)

    @unittest.skipUnless(os.environ.get('LOCALPILOT_HARBOR_CONTRACT')=='1','Pinned Harbor schema environment')
    def test_official_resume_schema_keeps_cancelled_results(self):
        from scripts.harbor_run_contract import inspect
        path=self.fixture.paths['localpilot',1,'alpha']
        raw=read_json(path)
        raw['exception_info']={'exception_type':'CancelledError','exception_message':'fixture',
            'exception_traceback':'fixture','occurred_at':raw['finished_at']}
        path.write_text(json.dumps(raw))
        result=inspect(self.directory/'configs'/f"{self.job['name']}.json",
                       self.directory/'runs'/self.job['name'],self.fixture.repository)
        self.assertTrue(result['schema_valid'])
        self.assertEqual(len(result['resources']),2)
        self.assertEqual(read_json(path)['exception_info']['exception_type'],'CancelledError')


class ResourcePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.host='unix:///private/tmp/eval-fixture/docker.sock'
        self.old_path=os.environ['PATH']
        os.environ['PATH']=str(self.root)+os.pathsep+self.old_path
        self.addCleanup(os.environ.__setitem__,'PATH',self.old_path)
        docker=self.root/'docker'
        docker.write_text('#!'+sys.executable+'\nimport json\nprint(json.dumps({"ID":"fixture-daemon","NCPU":4,"MemTotal":10737418240,"Architecture":"aarch64"}))\n')
        docker.chmod(0o755)

    def evidence(self, **changes):
        path=self.root/'guest-disk.json'
        path.write_text(json.dumps({'docker_host':self.host,'daemon_id':'fixture-daemon',
            'observed_at':datetime.now(timezone.utc).isoformat(),'guest_available_bytes':12*1024**3,
            'command':'fixture guest df -B1 /var/lib/docker',**changes}))
        return path

    def test_real_probe_cli_output_checks_vm_memory_before_run(self):
        result=_docker(self.host,{'cpus':4,'memory_bytes':10*1024**3,'accelerator_required':False})
        self.assertEqual(result['ID'],'fixture-daemon')
        with self.assertRaisesRegex(ValueError,'below required'):
            _docker(self.host,{'cpus':4,'memory_bytes':11*1024**3,'accelerator_required':False})

    def test_guest_free_space_must_belong_to_fresh_matching_daemon(self):
        docker=_docker(self.host,None)
        result=_guest_disk(self.evidence(),self.host,docker,8*1024**3)
        self.assertEqual(result['guest_available_bytes'],12*1024**3)
        for change in ({'daemon_id':'different'}, {'guest_available_bytes':1},
                       {'observed_at':(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                _guest_disk(self.evidence(**change),self.host,docker,8*1024**3)

    def test_docker_default_context_and_accelerator_are_not_assumed(self):
        with self.assertRaisesRegex(ValueError,'Explicit local Docker socket'):
            _docker(None,None)
        with self.assertRaisesRegex(ValueError,'GPU/TPU'):
            _docker(self.host,{'cpus':1,'memory_bytes':1,'accelerator_required':True})

    def test_requirements_use_peak_task_and_registered_memory_reserve(self):
        study={'specification':{'execution':{'n_concurrent_trials':2},'arms':[{'agent':{'kwargs':{'model_budget':{'min_available_bytes':10}}}}]}}
        resources=[{'cpus':2,'memory_mb':100,'storage_mb':100,'gpus':0,'tpu':False},
                   {'cpus':4,'memory_mb':200,'storage_mb':8000,'gpus':0,'tpu':False}]
        result=_requirements(study,resources)
        self.assertEqual(result['cpus'],8)
        self.assertEqual(result['memory_bytes'],400*1024**2)
        self.assertEqual(result['guest_free_bytes'],16000*1024**2)
        self.assertEqual(result['host_available_bytes'],10)

    @unittest.skipUnless(os.environ.get('LOCALPILOT_HARBOR_CONTRACT')=='1','Pinned Harbor schema environment')
    def test_preflight_uses_actual_official_schema_subprocess_and_readonly_docker_probe(self):
        import inspect
        from harbor.models.job.config import JobConfig
        fixture=fixtures.PublicAgentEvaluationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        harbor=Path(inspect.getfile(JobConfig)).resolve().parents[4]
        result=preflight(fixture.study_dir,fixture.study,fixture.study['jobs'][0],harbor,
                         fixture.repository,Path(__file__).resolve().parents[1],sys.executable,
                         self.host,self.evidence())
        checks={row['name']:row for row in result['checks']}
        self.assertEqual(checks['official_harbor_schema']['status'],'PASS',checks)
        self.assertEqual(checks['docker_identity_and_capacity']['status'],'PASS',checks)
        self.assertEqual(checks['guest_disk']['status'],'PASS',checks)
        self.assertEqual(len(checks['official_harbor_schema']['evidence']['resources']),2)


if __name__=='__main__':
    unittest.main()
