from pathlib import Path
import ast
import datetime
import gzip
import hashlib
import json
import shutil
import sqlite3
import subprocess

SCRATCH = Path('/workspace/scratch/c0f3ec78c621')
REPO = Path('/workspace/scratch/2a488f6eabf5/LocalPilot-polish-final-20261116')
SOURCE = SCRATCH / 'validation/audit-20261117/final-source-b31'
RUN = SCRATCH / 'validation/package-b31-b8-b32-LtvhM6'
NATIVE = RUN / 'native-smoke'
AUDIT = SCRATCH / 'validation/audit-20261117'
OUT = REPO / 'desktop/docs/evidence/audit-20261117-desktop/final-package-rc14'
COMMIT = 'c5439659a579b2ee9e74fd53e6d3232fe12fb855'
TREE = 'd0b0b33b036587ef0f0a802ca728419e9a444587'
DEB_SHA = '66aed474856ffa958ec07d383dd8f31840bbbdabbd0613e229ce342f9b78ce61'
ELF_SHA = '75ffa8be30e8a7c73c4cc7806c29cd65d6d9e115bb78e07e5bf097c09dee864c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    assert not OUT.exists(), 'New independent evidence directory required'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip() == COMMIT
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=SOURCE, text=True).strip() == TREE
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, text=True).strip()
    delivery = Path((RUN / 'delivery-directory.txt').read_text().strip())
    deb = delivery / 'LocalPilot-Test-5.0.1-rc.14-linux-x86_64.deb'
    assert sha(deb) == DEB_SHA and deb.stat().st_size == 114637332
    assert sha(NATIVE / 'extracted/usr/bin/localpilot-desktop-test') == ELF_SHA
    before = json.loads((RUN / 'verify-resources-against-original-source.log').read_text())
    after = json.loads((RUN / 'verify-resources-after-build.log').read_text())
    assert before == after and after['passed']
    assert sum(x['source_files'] for x in after['verified_code'].values()) == 286
    assert len(after['wheel_hashes']) == 40
    health = json.loads((NATIVE / 'service-capabilities.json').read_text())
    assert health['health']['version'] == health['module_versions']['localpilot-agent-service'] == '5.0.0b31'
    assert health['task_count'] == health['health']['active_task_count'] == 0
    for profile in ['k', 'l']:
        stopped = json.loads((NATIVE / f'native-rc14-{profile}-stop.json').read_text())
        assert stopped['status'] == 'STOPPED' and stopped['owned_remaining'] == []
    OUT.mkdir()
    for path in sorted(NATIVE.iterdir()):
        if path.is_file():
            if path.suffix == '.log':
                (OUT / (path.name + '.gz')).write_bytes(gzip.compress(path.read_bytes(), mtime=0))
            else:
                shutil.copy2(path, OUT / path.name)
    for source, target in [
        (RUN / 'SOURCE_SNAPSHOT.json', 'source-snapshot.json'),
        (RUN / 'VERIFIED_MODULES.json', 'verified-modules.json'),
        (RUN / 'candidate-versions.json', 'candidate-versions.json'),
        (RUN / 'verify-resources-against-original-source.log', 'verified-source-before-build.json'),
        (RUN / 'verify-resources-after-build.log', 'verified-source-after-build.json'),
        (delivery / 'RESULTS.json', 'package-results.json'),
        (delivery / 'SHA256SUMS', 'SHA256SUMS'),
        (delivery / 'build-config.json', 'build-config.json'),
        (SCRATCH / 'prepare-audit-rc14-localpilot-package.sh', 'build-recipe.sh'),
        (AUDIT / 'run_rc14_build_native.sh', 'build-native-launcher.sh'),
        (AUDIT / 'build-rc14-native-job.json', 'build-native-job.json'),
        (AUDIT / 'build-rc14-native-exit.json', 'build-native-exit.json'),
        (AUDIT / 'run_qualification_job.py', 'build-native-supervisor.py'),
        (SOURCE / 'localpilot_service/__init__.py', 'frozen-service-version.py'),
        (Path('/workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/webkit-minimal-overlay-r9/launch-owned-webview-minimal.sh'), 'launch-owned-webview-minimal.sh'),
    ]:
        shutil.copy2(source, OUT / target)
    for path in [RUN / 'build-linux-test.log', RUN / 'prepare-resources.log',
                 *sorted(RUN.glob('wheel-*.log')), AUDIT / 'build-rc14-native.log']:
        (OUT / (path.name + '.gz')).write_bytes(gzip.compress(path.read_bytes(), mtime=0))
    root_k = SCRATCH / 'native-rc14-k'
    root_l = SCRATCH / 'native-rc14-l'
    for label, root in [('k', root_k), ('l', root_l)]:
        shutil.copy2(root / 'test-owner.json', OUT / ('test-owner-' + label + '.json'))
    (OUT / 'core-service.log.gz').write_bytes(gzip.compress((root_k / 'client/product-v5/service.log').read_bytes(), mtime=0))
    no_model = {
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model_or_task_submission_performed': False, 'model_download_performed': False,
        'api_key_entered': False, 'account_connected': False,
        'live_service_task_count': health['task_count'],
        'live_service_active_task_count': health['health']['active_task_count'],
        'profiles': {},
        'scope': 'Only fresh GUI profiles K and L. Separate engineering, grading and b28 two-hour jobs are excluded. No data or credentials from those jobs were read.',
    }
    for label, root, config, databases in [
        ('k', root_k, 'client/product-v5/companion.json', {
            'client/product-v5/data/runtime.sqlite3': ['checkpoints', 'journal'],
            'client/product-v5/companion-data/memory.sqlite3': ['memories', 'training_examples', 'observation_events'],
        }),
        ('l', root_l, 'client/companion-home/companion.json', {
            'client/companion-home/companion-data/memory.sqlite3': ['memories', 'training_examples', 'observation_events'],
        }),
    ]:
        settings = json.loads((root / config).read_text())
        item = {
            'root': str(root),
            'companion_config': {k: settings[k] for k in ['backend', 'watch_dirs', 'native_observation_enabled', 'notifications', 'proactive_level', 'localpilot_auto_local', 'allow_automatic_cloud']},
            'database_counts': {},
        }
        for relative, tables in databases.items():
            with sqlite3.connect((root / relative).as_uri() + '?mode=ro', uri=True) as connection:
                item['database_counts'][relative] = {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in tables}
        assert item['companion_config']['backend'] == 'disabled'
        assert all(count == 0 for counts in item['database_counts'].values() for count in counts.values())
        if label == 'l':
            item['core_database'] = 'NOT_CREATED: pet-only Companion profile; no Core count is invented'
            item['animation_probe_attempts'] = 1
            item['draft_typed_then_cleared_without_send'] = True
        no_model['profiles'][label] = item
    write('native-no-model-requests.json', no_model)
    constant = next(ast.literal_eval(n.value) for n in ast.parse((SOURCE / 'localpilot_service/__init__.py').read_text()).body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in n.targets))
    assert constant == '5.0.0b31'
    write('runtime-version-match.json', {
        'source_commit': COMMIT, 'source_tree': TREE, 'frozen_source_dirty': False,
        'frozen_service_version': constant, 'frozen_version_source_sha256': sha(SOURCE / 'localpilot_service/__init__.py'),
        'installed_distribution_metadata_version': health['module_versions']['localpilot-agent-service'],
        'actual_service_health_version': health['health']['version'], 'native_version_gate': 'PASS',
        'first_setup': 'Core ready; setup completed; main GUI visibly reports Core 5.0.0b31',
    })
    prior = OUT.parent / 'final-package-rc13'
    prior_manifest = json.loads((prior / 'MANIFEST.json').read_text())
    checks = {name: {'bytes_match': (prior / name).stat().st_size == info['bytes'], 'sha256_match': sha(prior / name) == info['sha256']} for name, info in prior_manifest['files'].items()}
    assert all(c['bytes_match'] and c['sha256_match'] for c in checks.values())
    write('previous-rc13-evidence-integrity.json', {
        'previous_manifest_sha256': sha(prior / 'MANIFEST.json'), 'verified_payload_files': len(checks),
        'all_unchanged': True, 'files': checks,
    })
    write('qualification-scope.json', {
        'source_commit': COMMIT, 'source_tree': TREE, 'build': 'PASS', 'native': 'PASS',
        'animation': 'PASS_SINGLE_SAMPLE', 'system_install': 'NOT_RUN', 'macos': 'NOT_RUN',
        'binary_upload': 'NOT_RUN', 'task_24h': 'OPTION_AND_CAPABILITY_ONLY_NOT_SUBMITTED',
        'gui_model_requests': 0, 'native_profiles': ['k', 'l'], 'frozen_source_unchanged': True,
        'system_limitations': ['read-only helper overlay, no system installation', 'X11 accessibility/session bus unavailable; screenshot-coordinate interaction used', 'read-only Mesa shader-cache warning retained'],
    })
    print(json.dumps({'output': str(OUT), 'payload_files_before_report': len(list(OUT.iterdir())), 'prior_payload_files_unchanged': len(checks), 'core': constant}))


if __name__ == '__main__':
    main()
