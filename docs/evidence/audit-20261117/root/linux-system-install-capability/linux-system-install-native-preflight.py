from pathlib import Path
from datetime import datetime, timezone
import json
import os
import subprocess

output = Path('/workspace/scratch/c0f3ec78c621/validation/audit-20261117/linux-system-install-native-preflight.json')
required = ['local-pilot-test', 'python3', 'xdg-utils', 'zenity', 'bubblewrap', 'python3.13', 'libayatana-appindicator3-1', 'libwebkit2gtk-4.1-0', 'libgtk-3-0']
record = {'observed_utc': datetime.now(timezone.utc).isoformat(), 'surface': 'Existing native Terminal ordinary shell', 'effective_uid': os.geteuid(), 'system_changes': False, 'commands': []}
commands = [['id'], ['bash', '-c', 'command -v sudo']]
for command in commands:
    result = subprocess.run(command, text=True, capture_output=True)
    record['commands'].append({'command': command, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
sudo = record['commands'][-1]['stdout'].strip()
if sudo:
    command = [sudo, '-n', '-l']
    result = subprocess.run(command, text=True, capture_output=True)
    record['commands'].append({'command': command, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
command = ['dpkg-query', '-W', '-f=${binary:Package}\t${db:Status-Status}\t${Version}\n', *required]
result = subprocess.run(command, text=True, capture_output=True)
record['commands'].append({'command': command, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
command = ['dpkg-query', '-W', '-f=${binary:Package}\t${db:Status-Status}\t${Version}\t${Provides}\n']
result = subprocess.run(command, text=True, capture_output=True)
providers = []
for line in result.stdout.splitlines():
    fields = line.split('\t')
    if len(fields) == 4 and fields[1] == 'installed':
        provided = {item.strip().split(' ', 1)[0] for item in fields[3].split(',')}
        matched = sorted(provided.intersection(required))
        if matched:
            providers.append({'package': fields[0], 'version': fields[2], 'provides_required': matched})
record['installed_dependency_providers'] = providers
record['provider_query_returncode'] = result.returncode
record['provider_query_stderr'] = result.stderr
with output.open('x') as stream:
    json.dump(record, stream, indent=2)
    stream.write('\n')
print(json.dumps({'receipt': str(output), 'effective_uid': record['effective_uid'], 'sudo_path': sudo or None, 'system_changes': False}))
