"""Read-only checks before a frozen Harbor job; no pulls, loads or pruning."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlparse
from urllib.request import urlopen

from scripts.harbor_budget_audit import comparison_configuration
from scripts.harbor_tokenizer_process import tokenizer_fingerprint
from scripts.public_agent_eval import digest, git, read_json, task_snapshot

RUNTIME_DIRS = ('agent','computer','localpilot_api','localpilot_service','localpilot_plugins',
                'localpilot_channels','scripts')


def runtime_snapshot(repository):
    paths = [path for name in RUNTIME_DIRS for path in (repository/name).rglob('*.py')]
    paths.append(repository/'pyproject.toml')
    files = {path.relative_to(repository).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(paths) if '__pycache__' not in path.parts}
    return {'git_commit':git(repository,'rev-parse','HEAD'), 'files_sha256':digest(files)}


def check_sources(study, harbor_repository, repository, runtime_repository):
    if git(harbor_repository,'rev-parse','HEAD') != study['harbor_commit']:
        raise ValueError('Harbor checkout differs from its frozen commit')
    if git(harbor_repository,'status','--porcelain','--untracked-files=no'):
        raise ValueError('Harbor has tracked modifications')
    if git(repository,'rev-parse','HEAD') != study['benchmark_commit']:
        raise ValueError('Benchmark checkout differs from its frozen commit')
    for task in study['tasks']:
        if task_snapshot(repository,task['path'])['files_sha256'] != task['files_sha256']:
            raise ValueError('Benchmark task files changed: ' + task['path'])
    if git(repository,'status','--porcelain','--untracked-files=all','--',*[t['path'] for t in study['tasks']]):
        raise ValueError('Benchmark task directories contain unregistered changes')
    actual = runtime_snapshot(runtime_repository)
    frozen = study.get('runtime_source')
    if frozen:
        if actual['files_sha256'] != frozen['files_sha256']:
            raise ValueError('Runtime source changed; use its frozen checkout or create a separate study')
    elif study['specification']['purpose'] == 'evaluation':
        candidate = study['specification']['comparison']['candidate']
        revision = next(a['revision'] for a in study['specification']['arms'] if a['id']==candidate)
        if not re.fullmatch('[0-9a-f]{7,40}',revision) or not actual['git_commit'].startswith(revision):
            raise ValueError('Legacy study requires the original frozen candidate Git revision')
        if git(runtime_repository,'status','--porcelain','--untracked-files=all','--',*RUNTIME_DIRS,'pyproject.toml'):
            raise ValueError('Legacy study runtime source must be clean')
    return actual


def preflight(directory, study, job, harbor_repository, repository, runtime_repository, python,
              docker_host=None, resource_evidence=None, live_process=False):
    import psutil
    checks = []

    def check(name, operation):
        try:
            data = operation()
            checks.append({'name':name,'status':'PASS','evidence':data})
            return data
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
            checks.append({'name':name,'status':'FAIL','reason':str(exc)})
            return None

    check('sources',lambda:check_sources(study,harbor_repository,repository,runtime_repository))
    schema = check('official_harbor_schema',lambda:_contract(directory,job,harbor_repository,repository,python,live_process))
    requirements = _requirements(study,schema['resources']) if schema else None
    host = docker_host or os.environ.get('DOCKER_HOST')
    docker = check('docker_identity_and_capacity',lambda:_bound_docker(study,host,requirements))
    if requirements:
        check('host_disk',lambda:_minimum(shutil.disk_usage(directory).free,requirements['host_free_bytes'],'available_bytes'))
        check('host_memory',lambda:_minimum(psutil.virtual_memory().available,requirements['host_available_bytes'],'available_bytes'))
        check('guest_disk',lambda:_guest_disk(resource_evidence,host,docker,requirements['guest_free_bytes']))
    if study['specification']['purpose'] == 'evaluation':
        check('matched_comparison_configuration',lambda:_comparison(study))
        for arm in study['specification']['arms']:
            check('model_and_tokenizer:'+arm['id'],lambda arm=arm:_model(arm,study['specification'].get('model_identity',{}),legacy=not study.get('runtime_source')))
    return {'schema_version':1, 'study_sha256':study['sha256'], 'job':job['name'],
            'observed_at':datetime.now(timezone.utc).isoformat(), 'ready':all(c['status']=='PASS' for c in checks),
            'docker_host':host, 'requirements':requirements, 'checks':checks, 'live_process_continuation':live_process,
            'limit':'Point-in-time preflight; image layer growth and concurrent host use are not reserved. Guest disk is operator-supplied evidence.'}


def _contract(directory, job, harbor_repository, repository, python, live_process=False):
    command = [python,str(Path(__file__).with_name('harbor_run_contract.py')),
               '--harbor-repository',str(harbor_repository),'--repository',str(repository),
               '--config',str(directory/'configs'/f"{job['name']}.json"),
               '--job-dir',str(directory/'runs'/job['name'])]
    if live_process:
        command.append('--live-process')
    result = subprocess.run(command,capture_output=True,text=True,timeout=60)
    if result.returncode:
        raise ValueError('Official schema check failed: ' + result.stderr[-4000:])
    return json.loads(result.stdout)


def _requirements(study, resources):
    spec = study['specification']
    concurrency = spec['execution']['n_concurrent_trials']
    budgets = [a['agent'].get('kwargs',{}).get('model_budget') or {} for a in spec['arms']]
    storage = max((r['storage_mb'] or 0 for r in resources),default=0)*1024**2*concurrency
    return {'cpus':max((r['cpus'] or 0 for r in resources),default=0)*concurrency,
            'memory_bytes':max((r['memory_mb'] or 0 for r in resources),default=0)*1024**2*concurrency,
            'accelerator_required':any(r['gpus'] or r['tpu'] for r in resources),
            'host_free_bytes':max(storage,5*1024**3)+5*1024**3,
            'guest_free_bytes':max(storage,5*1024**3),
            'host_available_bytes':max((b.get('min_available_bytes',8*1024**3) for b in budgets),default=8*1024**3)}


def _docker(host, requirements):
    if not isinstance(host,str) or not host.startswith('unix:///'):
        raise ValueError('Explicit local Docker socket required; no implicit/default Docker context')
    result = subprocess.run(['docker','--host',host,'info','--format','{{json .}}'],capture_output=True,text=True,timeout=15)
    if result.returncode:
        raise ValueError('Docker info failed: ' + result.stderr)
    value = json.loads(result.stdout)
    if not value.get('ID'):
        raise ValueError('Docker daemon identity is unavailable')
    if requirements:
        _minimum(value.get('NCPU'),requirements['cpus'],'cpus')
        _minimum(value.get('MemTotal'),requirements['memory_bytes'],'memory_bytes')
        if requirements['accelerator_required']:
            raise ValueError('This Docker preflight does not qualify GPU/TPU task requirements')
    return {key:value.get(key) for key in ('ID','NCPU','MemTotal','Architecture','OperatingSystem','DockerRootDir')}


def _bound_docker(study, host, requirements):
    cleanup = study['specification'].get('owned_docker_cache_cleanup')
    if cleanup:
        raw = Path(cleanup['plan_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=cleanup['plan_sha256']:
            raise ValueError('Frozen cache cleanup plan changed')
        plan = json.loads(raw)
        if plan.get('docker_host')!=host:
            raise ValueError('Docker preflight host differs from the frozen dedicated cache plan')
        result = _docker(host,requirements)
        if plan.get('daemon_id') and result['ID']!=plan['daemon_id']:
            raise ValueError('Dedicated Docker daemon changed after its plan was frozen')
        return result
    return _docker(host,requirements)


def _minimum(actual, minimum, label):
    if type(actual) not in (int,float) or not math.isfinite(actual) or actual < minimum:
        raise ValueError(f'{label}={actual} is below required {minimum}')
    return {label:actual,'minimum':minimum}


def _guest_disk(path, host, docker, minimum):
    if path is None or docker is None:
        raise ValueError('Fresh guest df evidence bound to this Docker daemon is required')
    evidence = read_json(path)
    if evidence.get('docker_host') != host or evidence.get('daemon_id') != docker['ID']:
        raise ValueError('Guest disk evidence belongs to a different Docker daemon')
    at = datetime.fromisoformat(evidence.get('observed_at','').replace('Z','+00:00'))
    if at.tzinfo is None or not -60 <= (datetime.now(timezone.utc)-at).total_seconds() <= 300:
        raise ValueError('Guest disk evidence must be timezone-qualified and at most five minutes old')
    if not isinstance(evidence.get('command'),str) or not evidence['command']:
        raise ValueError('Record the actual guest df command used to measure available bytes')
    return {**_minimum(evidence.get('guest_available_bytes'),minimum,'guest_available_bytes'),
            'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'observation':evidence}


def _comparison(study):
    result = comparison_configuration(study['specification'])
    blocking = result['reasons']
    if not study.get('runtime_source'):
        blocking = [reason for reason in blocking if reason != 'Missing frozen model revision, quantization, or tokenizer identity']
        result['legacy_limit'] = 'May continue its original protocol; missing identity or budget evidence still prevents a qualified comparison'
    if blocking:
        raise ValueError('; '.join(blocking))
    return result


def _model(arm, identity, legacy=False):
    options = arm['agent'].get('kwargs',{})
    endpoint = options.get('endpoint','')
    url = urlparse(endpoint)
    if url.scheme not in ('http','https') or url.hostname not in ('127.0.0.1','localhost','::1') or url.username or url.password or url.query or url.fragment:
        raise ValueError('Measured preflight requires an explicit credential-free loopback model endpoint')
    budget = options.get('model_budget',{})
    if not Path(budget.get('tokenizer_python','')).is_file():
        raise ValueError('Tokenizer interpreter is unavailable')
    fingerprint = tokenizer_fingerprint(budget.get('tokenizer_path',''))
    if fingerprint != identity.get('tokenizer_sha256') and not (legacy and not identity.get('tokenizer_sha256')):
        raise ValueError('Tokenizer/template fingerprint differs from the frozen model identity')
    with urlopen(endpoint.rstrip('/')+'/models',timeout=10) as response:
        data = json.load(response)
    models = [entry['id'] for entry in data.get('data',[]) if isinstance(entry,dict) and isinstance(entry.get('id'),str)]
    if arm['agent']['model_name'] not in models:
        raise ValueError('Frozen model is absent from the endpoint model listing')
    return {'configured_model':arm['agent']['model_name'],'listed_models':models,'tokenizer_sha256':fingerprint,
            'limit':'A model listing does not prove weight identity, loaded state or inference success'}
