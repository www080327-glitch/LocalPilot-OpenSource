import json
from pathlib import Path
import subprocess
import sys
import time

job_path = Path(sys.argv[1]).resolve()
job = json.loads(job_path.read_text())
started = time.time()
with Path(job['log']).open('w') as log:
    process = subprocess.Popen(job['command'], cwd=job['cwd'], stdout=log,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    print(json.dumps({'job': job_path.name, 'started_unix': started}), flush=True)
    while True:
        try:
            returncode = process.wait(timeout=30)
            break
        except subprocess.TimeoutExpired:
            progress = {'job': job_path.name, 'elapsed_seconds': time.time() - started}
            heartbeat = Path(job.get('heartbeat', '/nonexistent'))
            if heartbeat.is_file():
                lines = heartbeat.read_text().splitlines()
                progress['heartbeats'] = len(lines)
                progress['last_heartbeat'] = json.loads(lines[-1]) if lines else None
            print(json.dumps(progress), flush=True)
Path(job['exit_receipt']).write_text(json.dumps({
    'started_unix': started, 'finished_unix': time.time(),
    'returncode': returncode,
}, indent=2) + '\n')
print(json.dumps({'job': job_path.name, 'returncode': returncode}), flush=True)
