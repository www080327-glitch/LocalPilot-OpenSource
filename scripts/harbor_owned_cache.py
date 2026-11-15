"""Harbor END hook for an explicitly approved, dedicated Docker VM cache."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


class OwnedDockerCachePlugin:
    probe_timeout = 30
    cleanup_timeout = 120

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
                or not isinstance(plan.get('daemon_id'),str) or not plan['daemon_id']
                or os.environ.get('DOCKER_HOST') != plan['docker_host']):
            raise ValueError('Cleanup requires the approved dedicated VM and exact operations')
        self.host = plan['docker_host']
        self.daemon_id = plan['daemon_id']
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
        try:
            identity = self._docker(['info','--format','{{.ID}}'],self.probe_timeout)
            if identity.returncode or identity.stdout.strip()!=self.daemon_id:
                row.update(status='SKIPPED_DAEMON_MISMATCH_OR_UNKNOWN',exit_code=identity.returncode,
                           observed_daemon_id=identity.stdout.strip(),error=identity.stderr)
                return
            active = self._docker(['ps','--quiet'],self.probe_timeout)
            if active.returncode or active.stdout.strip():
                row.update(status='SKIPPED_ACTIVE_OR_UNKNOWN', exit_code=active.returncode,
                           active_containers=active.stdout.splitlines(), error=active.stderr)
                return
            for operation in self.operations:
                result = self._docker(operation[1:],self.cleanup_timeout)
                row['operations'].append({'command':operation, 'exit_code':result.returncode,
                    'stdout':result.stdout, 'stderr':result.stderr})
                if result.returncode:
                    break
            row['status'] = 'PASS' if all(r['exit_code']==0 for r in row['operations']) else 'FAIL'
        except (OSError,subprocess.SubprocessError) as exc:
            row.update(status='ERROR',exception_type=type(exc).__name__,error=str(exc))
            if isinstance(exc,subprocess.TimeoutExpired):
                row.update(failed_command=exc.cmd,
                           stdout=(exc.stdout or b'').decode(errors='replace'),
                           stderr=(exc.stderr or b'').decode(errors='replace'))
        finally:
            row['finished_at'] = datetime.now(timezone.utc).isoformat()
            with self.log.open('a') as stream:
                stream.write(json.dumps(row)+'\n')

    def _docker(self, arguments, timeout):
        return subprocess.run(['docker','--host',self.host,*arguments],capture_output=True,text=True,timeout=timeout)
