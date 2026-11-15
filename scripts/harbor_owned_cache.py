"""Harbor END hook for an explicitly approved, dedicated Docker VM cache."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


class OwnedDockerCachePlugin:
    def __init__(self, *, plan_path, plan_sha256):
        raw = Path(plan_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != plan_sha256:
            raise ValueError('Docker cache cleanup plan changed after freezing')
        plan = json.loads(raw)
        operations = [['docker','image','prune','--all','--force'],
                      ['docker','builder','prune','--all','--force']]
        if (plan['scope'] != 'only newly created dedicated evaluation VM'
                or plan['proposed_operations'] != operations
                or not plan['no_system_prune_or_volume_deletion']
                or not plan['docker_host'].startswith('unix:///private/tmp/')
                or os.environ.get('DOCKER_HOST') != plan['docker_host']):
            raise ValueError('Cleanup requires the approved dedicated VM and exact operations')
        self.host = plan['docker_host']
        self.operations = operations
        self.plan_sha256 = plan_sha256

    async def on_job_start(self, job):
        if job.config.n_concurrent_trials != 1:
            raise ValueError('Between-trial Docker cleanup requires one concurrent trial')
        self.log = job.job_dir/'owned-docker-cache.jsonl'
        job.on_trial_ended(self.after_trial)

    async def on_job_end(self, job_result):
        pass

    async def after_trial(self, event):
        # Harbor emits END after stopping the task environment and saving its
        # result. The single trial slot stays held until this hook returns.
        await asyncio.to_thread(self.cleanup, event.trial_name)

    def cleanup(self, trial_name):
        row = {'trial':trial_name, 'at':datetime.now(timezone.utc).isoformat(),
               'plan_sha256':self.plan_sha256, 'docker_host':self.host, 'operations':[]}
        active = subprocess.run(['docker','--host',self.host,'ps','--quiet'],
            capture_output=True, text=True, timeout=30)
        if active.returncode or active.stdout.strip():
            row.update(status='SKIPPED_ACTIVE_OR_UNKNOWN', exit_code=active.returncode,
                       active_containers=active.stdout.splitlines(), error=active.stderr)
        else:
            for operation in self.operations:
                result = subprocess.run(['docker','--host',self.host,*operation[1:]],
                    capture_output=True, text=True, timeout=120)
                row['operations'].append({'command':operation, 'exit_code':result.returncode,
                    'stdout':result.stdout, 'stderr':result.stderr})
            row['status'] = 'PASS' if all(r['exit_code']==0 for r in row['operations']) else 'FAIL'
        with self.log.open('a') as stream:
            stream.write(json.dumps(row)+'\n')
