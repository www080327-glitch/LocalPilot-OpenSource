"""Read-only schema checks executed inside the pinned Harbor interpreter."""
import argparse
import json
from pathlib import Path
import sys


def inspect(config_path, job_dir, task_root, live_process=False):
    from harbor.models.job.config import JobConfig
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.config import TrialConfig
    from harbor.models.trial.result import TrialResult

    config = JobConfig.model_validate_json(config_path.read_text())
    if job_dir.exists():
        previous = JobConfig.model_validate_json((job_dir/'config.json').read_text())
        previous.jobs_dir = config.jobs_dir
        if previous != config:
            raise ValueError('Saved Harbor job config differs from the frozen config')
        for directory in ([] if live_process else job_dir.iterdir()):
            if not directory.is_dir():
                continue
            trial = TrialResult.model_validate_json((directory/'result.json').read_text())
            saved = TrialConfig.model_validate_json((directory/'config.json').read_text())
            if saved != trial.config:
                raise ValueError('Saved trial config differs from its result: ' + directory.name)
    resources = []
    for task in config.tasks:
        definition = TaskConfig.model_validate_toml((task_root/task.path/'task.toml').read_text())
        env = definition.environment
        resources.append({'path':str(task.path), 'cpus':env.cpus, 'memory_mb':env.memory_mb,
                          'storage_mb':env.storage_mb, 'gpus':env.gpus, 'tpu':bool(env.tpu)})
    return {'resources':resources, 'schema_valid':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harbor-repository',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--job-dir',type=Path,required=True)
    parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--live-process',action='store_true')
    args = parser.parse_args()
    sys.path.insert(0,str(args.harbor_repository/'src'))
    print(json.dumps(inspect(args.config,args.job_dir,args.repository,args.live_process)))


if __name__ == '__main__':
    main()
