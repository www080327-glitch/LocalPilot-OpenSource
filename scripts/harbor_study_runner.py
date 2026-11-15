"""Continue frozen jobs without deleting, replaying or replacing an attempt."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
from uuid import uuid4

from scripts.harbor_preflight import preflight
from scripts.public_agent_eval import (TERMINAL_STATUSES, matching_fields, normalize_trial,
                                      read_json, read_study, write_json)


def select_job(study, arm, repeat):
    matches = [j for j in study['jobs'] if j['arm']==arm and j['repeat']==repeat]
    if len(matches)!=1:
        raise ValueError('Arm/repeat is not part of this frozen study')
    return matches[0]


def inspect_existing(directory, study, job):
    job_dir = directory/'runs'/job['name']
    if not job_dir.exists():
        return {'status':'NEW','completed_trials':0,'preserved_files':{}}
    matching_fields(read_json(directory/'configs'/f"{job['name']}.json"),read_json(job_dir/'config.json'),'job.config')
    tasks = {task['name']:task for task in study['tasks']}
    seen, ids, files = set(), set(), {}
    for trial_dir in sorted(p for p in job_dir.iterdir() if p.is_dir()):
        result_path = trial_dir/'result.json'
        if not result_path.is_file() or not (trial_dir/'config.json').is_file():
            raise ValueError('Unsettled trial must not be replayed or deleted: ' + trial_dir.name + '; continue its original process or retain it as unresolved')
        raw = read_json(result_path)
        name = raw.get('task_name')
        if name not in tasks or name in seen or raw.get('id') in ids:
            raise ValueError('Unexpected or duplicated prior attempt: ' + trial_dir.name)
        row = normalize_trial(raw,study,job,tasks[name])
        if row['status'] not in TERMINAL_STATUSES:
            raise ValueError('Prior attempt has no terminal result: ' + trial_dir.name)
        seen.add(name)
        ids.add(raw['id'])
        for path in trial_dir.rglob('*'):
            if path.is_file():
                files[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'status':'COMPLETE' if len(seen)==len(tasks) else 'RESUMABLE',
            'completed_trials':len(seen),'preserved_files':files}


def run_job(directory, arm, repeat, harbor_repository, python, *, repository,
            runtime_repository=None, docker_host=None, resource_evidence=None, resume=False,
            continue_pid=None):
    directory = directory.resolve(strict=True)
    study = read_study(directory)
    job = select_job(study,arm,repeat)
    prior = inspect_existing(directory,study,job) if continue_pid is None else None
    if prior and prior['status']=='COMPLETE':
        print(json.dumps({'job':job['name'],'status':'ALREADY_COMPLETE','replayed_trials':0}))
        return 0
    if prior and prior['status']!='NEW' and not resume:
        raise ValueError('Job already exists; use resume after reviewing its preserved attempts')
    runtime_repository = (runtime_repository or Path(__file__).resolve().parents[1]).resolve(strict=True)
    harbor_repository, repository = harbor_repository.resolve(strict=True), repository.resolve(strict=True)
    report = preflight(directory,study,job,harbor_repository,repository,runtime_repository,python,
                       docker_host,resource_evidence,live_process=continue_pid is not None)
    attempt = job['name']+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid4().hex[:8]
    prefix = directory/'launches'/attempt
    write_json(prefix.with_suffix('.preflight.json'),report)
    if not report['ready']:
        raise ValueError('Preflight blocked this launch; see ' + str(prefix.with_suffix('.preflight.json')))
    command = harbor_command(directory,study,job,harbor_repository,python)
    if continue_pid is not None:
        receipt = continue_process(continue_pid,command,runtime_repository,report['docker_host'])
        write_json(prefix.with_suffix('.continued.json'),{'study_sha256':study['sha256'],**receipt})
        return 0
    reject_live_launcher(command,runtime_repository)
    if prior['status']!='NEW':
        snapshot = prefix.with_suffix('.prior-job')
        snapshot.mkdir()
        for path in (directory/'runs'/job['name']).iterdir():
            if path.is_file():
                shutil.copy2(path,snapshot/path.name)
    receipt = {'study_sha256':study['sha256'],'job':job['name'],'started_at':datetime.now(timezone.utc).isoformat(),
               'command':command,'runtime_repository':str(runtime_repository),'prior':prior,
               'resume_semantics':'Original run/config; retain every terminal outcome, including errors and cancellations'}
    write_json(prefix.with_suffix('.launch.json'),receipt)
    environment = dict(os.environ,DOCKER_HOST=report['docker_host'])
    if study['specification']['purpose']=='evaluation':
        # Terminus2 imports LiteLLM even though this adapter replaces its model
        # transport; the bundled price table avoids an unrelated startup fetch.
        environment['LITELLM_LOCAL_MODEL_COST_MAP']='True'
    with prefix.with_suffix('.log').open('x') as stream:
        process = subprocess.Popen(command,cwd=runtime_repository,env=environment,stdout=stream,stderr=subprocess.STDOUT)
        write_json(prefix.with_suffix('.process.json'),{'pid':process.pid,'started_at':datetime.now(timezone.utc).isoformat()})
        try:
            code = process.wait()
        except BaseException as exc:
            write_json(prefix.with_suffix('.interrupted.json'),{'exception_type':type(exc).__name__,
                'pid':process.pid,'exit_code':process.poll(),'at':datetime.now(timezone.utc).isoformat(),
                'note':'Inspect the original process and raw attempts before any continuation'})
            raise
    changed = changed_evidence(directory,prior['preserved_files'])
    write_json(prefix.with_suffix('.exit.json'),{'exit_code':code,'finished_at':datetime.now(timezone.utc).isoformat(),
                                               'prior_evidence_changed':changed})
    if changed:
        raise ValueError('Previously settled evidence changed; comparison is invalid: '+', '.join(changed))
    print(json.dumps({'job':job['name'],'exit_code':code,'note':'Exit status is not a benchmark score; run audit'}))
    return code


def harbor_command(directory, study, job, harbor_repository, python):
    entry = 'import sys; sys.path.insert(0, sys.argv.pop(1)); from harbor.cli.main import app; app()'
    command = [python,'-c',entry,str(harbor_repository/'src'),'run','--config',
               str(directory/'configs'/f"{job['name']}.json")]
    cleanup = study['specification'].get('owned_docker_cache_cleanup')
    if cleanup:
        command.extend(['--plugin','scripts.harbor_owned_cache:OwnedDockerCachePlugin',
                        '--plugin-kwarg','plan_path='+cleanup['plan_path'],
                        '--plugin-kwarg','plan_sha256='+cleanup['plan_sha256']])
    return command


def changed_evidence(directory, files):
    return [name for name,expected in files.items()
            if not (directory/name).is_file() or hashlib.sha256((directory/name).read_bytes()).hexdigest()!=expected]


def reject_live_launcher(command, cwd):
    import psutil
    for process in psutil.process_iter(['pid','cmdline','cwd']):
        if process.info['cmdline'] and '--config' in process.info['cmdline']:
            if process.info['cmdline'][1:]==command[1:] and process.info['cwd']==str(cwd):
                raise ValueError(f"Existing Harbor process {process.pid}; do not launch the same job twice")


def continue_process(pid, command, cwd, docker_host=None):
    import psutil
    process = psutil.Process(pid)
    if process.uids().real!=os.getuid() or process.cmdline()[1:]!=command[1:] or Path(process.cwd())!=cwd:
        raise ValueError('PID is not the original user-owned Harbor process for this exact frozen command/runtime')
    if docker_host is not None and process.environ().get('DOCKER_HOST')!=docker_host:
        raise ValueError('Original process Docker daemon differs from the inspected daemon')
    if process.status()!=psutil.STATUS_STOPPED:
        raise ValueError('Original Harbor process is not stopped; no signal was sent')
    targets = [process,*process.children(recursive=True)]
    stopped = [p for p in targets if p.status()==psutil.STATUS_STOPPED]
    receipt = {'status':'CONTINUED_ORIGINAL_PROCESS','at':datetime.now(timezone.utc).isoformat(),
               'processes':[{'pid':p.pid,'created_at':p.create_time()} for p in stopped],
               'replayed_trials':0,'limit':'Continues the existing attempt; completion must still be audited'}
    for item in reversed(stopped):
        item.send_signal(signal.SIGCONT)
    return receipt
