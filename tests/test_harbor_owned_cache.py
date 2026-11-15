"""Cleanup reaches a subprocess fixture only; it never touches a Docker daemon."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from scripts.harbor_owned_cache import OwnedDockerCachePlugin


class OwnedCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.host='unix:///private/tmp/owned-eval-fixture/docker.sock'
        for key,value in {'PATH':str(self.root)+os.pathsep+os.environ['PATH'],'DOCKER_HOST':self.host}.items():
            previous=os.environ.get(key)
            os.environ[key]=value
            self.addCleanup(self.restore,key,previous)
        self.state=self.root/'state.json'
        self.state.write_text(json.dumps({'id':'fixture-daemon','active':'','prune_exit':0}))
        self.calls=self.root/'calls.jsonl'
        script=self.root/'docker'
        script.write_text('#!'+sys.executable+'\nimport json,sys,time\nfrom pathlib import Path\n'
            'root=Path(__file__).parent\nstate=json.loads((root/"state.json").read_text())\n'
            'args=sys.argv[1:]\nwith (root/"calls.jsonl").open("a") as out: out.write(json.dumps(args)+"\\n")\n'
            'if state.get("hang"): print("partial fixture output",flush=True); time.sleep(30)\n'
            'if "info" in args: print(state["id"])\n'
            'elif "ps" in args: print(state["active"])\n'
            'else: print("fixture prune result"); sys.exit(state["prune_exit"])\n')
        script.chmod(0o755)
        self.plan={'scope':'only newly created dedicated evaluation VM','docker_host':self.host,'daemon_id':'fixture-daemon',
                   'no_system_prune_or_volume_deletion':True,'proposed_operations':[
                       ['docker','image','prune','--all','--force'],['docker','builder','prune','--all','--force']]}
        self.plugin=self.build()
        self.plugin.log=self.root/'receipts.jsonl'

    @staticmethod
    def restore(key,value):
        if value is None:
            os.environ.pop(key,None)
        else:
            os.environ[key]=value

    def build(self):
        path=self.root/'plan.json'
        path.write_text(json.dumps(self.plan))
        return OwnedDockerCachePlugin(plan_path=path,plan_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def configure(self,**change):
        value=json.loads(self.state.read_text())
        self.state.write_text(json.dumps({**value,**change}))

    def receipt(self):
        return json.loads(self.plugin.log.read_text().splitlines()[-1])

    def test_dedicated_idle_daemon_runs_only_exact_image_and_builder_operations(self):
        self.plugin.cleanup('fixture-task')
        row=self.receipt()
        self.assertEqual(row['status'],'PASS')
        self.assertEqual([value['command'] for value in row['operations']],self.plan['proposed_operations'])
        calls=[json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertTrue(all(call[:2]==['--host',self.host] for call in calls))
        self.assertFalse(any('system' in call or 'volume' in call for call in calls))

    def test_recreated_daemon_at_same_socket_is_never_pruned(self):
        self.configure(id='different-daemon')
        self.plugin.cleanup('fixture-task')
        self.assertEqual(self.receipt()['status'],'SKIPPED_DAEMON_MISMATCH_OR_UNKNOWN')
        self.assertEqual(len(self.calls.read_text().splitlines()),1)

    def test_active_container_blocks_cleanup_and_retains_probe(self):
        self.configure(active='fixture-container')
        self.plugin.cleanup('fixture-task')
        row=self.receipt()
        self.assertEqual(row['status'],'SKIPPED_ACTIVE_OR_UNKNOWN')
        self.assertEqual(row['active_containers'],['fixture-container'])
        self.assertEqual(row['operations'],[])

    def test_failed_first_operation_is_logged_and_stops_following_prune(self):
        self.configure(prune_exit=7)
        self.plugin.cleanup('fixture-task')
        row=self.receipt()
        self.assertEqual(row['status'],'FAIL')
        self.assertEqual(len(row['operations']),1)
        self.assertEqual(row['operations'][0]['exit_code'],7)
        self.assertIn('fixture prune result',row['operations'][0]['stdout'])

    def test_probe_timeout_retains_partial_stdout_and_error_receipt(self):
        self.configure(hang=True)
        # This deadline includes starting Python and reaching the first print.
        self.plugin.probe_timeout=2
        self.plugin.cleanup('fixture-task')
        row=self.receipt()
        self.assertEqual(row['status'],'ERROR')
        self.assertEqual(row['exception_type'],'TimeoutExpired')
        self.assertIn('partial fixture output',row['stdout'])

    def test_unbound_or_changed_plan_is_rejected_before_probe(self):
        self.plan.pop('daemon_id')
        with self.assertRaisesRegex(ValueError,'approved dedicated VM'):
            self.build()
        self.assertFalse(self.calls.exists())


if __name__=='__main__':
    unittest.main()
