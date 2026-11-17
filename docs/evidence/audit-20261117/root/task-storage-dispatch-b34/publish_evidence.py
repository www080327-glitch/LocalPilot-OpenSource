"""Prepare byte-preserving public evidence archives from an explicit allowlist.

No network or repository writes. The supplied config declares every required
file, including each engineering acceptance-original/final-project member.
Missing declared evidence or a known credential match aborts the entire export.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile


BASE = Path(__file__).resolve().parent
REQUIRED_GROUPS = {
    'regressions', 'scheduling', 'superagent', 'storage', 'packaging-original',
    'packaging-final-core', 'engineering-r9', 'engineering-r10', 'engineering-r11',
}
TEXT_SUFFIXES = {'.json', '.jsonl', '.log', '.txt', '.md', '.py', '.csv', '.toml',
                 '.yaml', '.yml', '.ini', '.cfg', '.diff', '.patch', '.sha256'}
FORBIDDEN_PARTS = {'core-private', 'private', 'workspace', 'node_modules', '__pycache__',
                   '.git', '.cache', '.venv', 'venv', 'runtime', 'build-environment', 'wheels'}
EXCLUSION_RULES = [
    'Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.',
    'Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.',
    'Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.',
    'Required files are never silently omitted. Undeclared files and directories are not traversed.',
    'Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--secret-file', action='append', type=Path,
                        help='Private key file for exact scanning; may be repeated. Values are never printed.')
    args = parser.parse_args()
    config_bytes = args.config.read_bytes()
    groups = plan(json.loads(config_bytes))
    output = args.output.resolve()
    if output in {BASE, BASE.parent} or not output.is_relative_to(BASE.parent) or output.exists():
        raise ValueError('Choose a new output directory beneath validation')
    secret_paths = args.secret_file or [BASE.parent.parent / 'private/openai-api-key']
    secrets = private_keys(secret_paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.public-evidence-', dir=output.parent) as temporary:
        stage = Path(temporary)
        exported = [archive_group(stage, group, secrets) for group in groups]
        manifest = {
            'schema_version': 1, 'kind': 'PUBLIC_EVIDENCE_BYTE_PRESERVING_EXPORT',
            'config_sha256': sha(config_bytes), 'script_sha256': sha(Path(__file__).read_bytes()),
            'known_credential_files_scanned': len(secrets), 'credential_matches': 0,
            'raw_input_bytes_preserved': True, 'exclusion_rules': EXCLUSION_RULES,
            'groups': exported,
        }
        write_json(stage / 'MANIFEST.json', manifest)
        rows = ['# LocalPilot 本轮公开证据', '',
                '原始输入字节直接归档；失败、阻断和未运行状态以各组原始结果为准。', '',
                '| 证据组 | 说明 | 原始文件数 | 归档 | 清单 |',
                '|---|---|---:|---|---|']
        for group in exported:
            rows.append(f"| [{group['id']}]({group['summary']}) | {group['description']} | {group['member_count']} | [{group['archive']}]({group['archive']}) | [{group['manifest']}]({group['manifest']}) |")
        rows += ['', '## 排除规则', '', *['- ' + item for item in EXCLUSION_RULES], '']
        (stage / 'SUMMARY.md').write_text('\n'.join(rows), encoding='utf-8')
        (stage / 'SHA256SUMS').write_text(''.join(group['archive_sha256'] + '  ' + group['archive'] + '\n' for group in exported))
        stage.rename(output)
    print(json.dumps({'status': 'PACKAGED_NOT_PUBLISHED', 'groups': len(exported),
                      'output': str(output), 'credential_matches': 0}))


def plan(config):
    if not isinstance(config, dict) or config.get('schema_version') != 1 or not isinstance(config.get('groups'), list):
        raise ValueError('Expected schema_version 1 and an explicit groups list')
    groups, ids, missing = [], set(), []
    for entry in config['groups']:
        if not isinstance(entry, dict):
            raise ValueError('Each evidence group must be an object')
        name, description = entry.get('id'), entry.get('description')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]+', name) or name in ids:
            raise ValueError('Evidence group IDs must be unique lowercase names')
        if not isinstance(description, str) or not description or '\n' in description or '|' in description:
            raise ValueError('Each group requires a one-line description without table delimiters')
        files = entry.get('files')
        if not isinstance(files, list) or any(not isinstance(item, str) for item in files) or entry.get('trees'):
            raise ValueError('files must contain explicit relative paths; directory expansion is not supported')
        expected = entry.get('expected_sha256', {})
        if (not isinstance(expected, dict) or set(expected) - set(files)
                or any(not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) for digest in expected.values())):
            raise ValueError('Expected source hashes must refer to declared files')
        ids.add(name)
        selected = {}
        for relative in files:
            path = input_path(relative)
            reason = exclusion(relative)
            if reason:
                raise ValueError(f'Declared required input is not public-eligible: {relative} ({reason})')
            if not path.is_file():
                missing.append(relative)
            else:
                selected[relative] = path
        if not selected:
            missing.append(name + '/<evidence>')
        groups.append({'id': name, 'description': description, 'files': selected, 'expected_sha256': expected})
    if ids != REQUIRED_GROUPS:
        raise ValueError('The config must explicitly declare all nine required evidence groups')
    if missing:
        raise FileNotFoundError('Missing declared required evidence: ' + ', '.join(sorted(set(missing))))
    return sorted(groups, key=lambda group: group['id'])


def input_path(relative):
    value = PurePosixPath(relative)
    if value.is_absolute() or '..' in value.parts or not value.parts or str(value) != relative:
        raise ValueError('Evidence inputs must be normalized paths relative to this validation run')
    path = BASE / relative
    if path.is_symlink() or not path.resolve().is_relative_to(BASE):
        raise ValueError('Linked or external evidence inputs are not allowed: ' + relative)
    return path


def exclusion(relative):
    path = PurePosixPath(relative)
    if set(path.parts) & FORBIDDEN_PARTS:
        return 'private/runtime/workspace/cache directory'
    name = path.name.lower()
    if ('.sqlite' in name or name.endswith(('.db', '.db-wal', '.db-shm', '.key', '.pem'))
            or name.startswith('.env') or name.endswith('.env')
            or name in {'env', 'token', 'token.json', 'tokens.json', 'credentials.json'}
            or 'api-key' in name or 'credentials' in name):
        return 'database, environment or credential file'
    if path.suffix.lower() not in TEXT_SUFFIXES and name != 'sha256sums':
        return 'file type outside public evidence allowlist'
    return None


def private_keys(paths):
    keys = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError('A required private credential scan file is unavailable')
        value = path.read_bytes().strip()
        if not value:
            raise ValueError('A private credential scan file is empty')
        keys.append(value)
    return keys


def archive_group(stage, group, secrets):
    name = group['id']
    target = stage / (name + '.tar.gz')
    members = []
    with target.open('wb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                for relative, path in sorted(group['files'].items()):
                    data = path.read_bytes()
                    if any(key in data for key in secrets):
                        raise ValueError('Known credential match in public candidate: ' + relative)
                    digest = sha(data)
                    if relative in group['expected_sha256'] and digest != group['expected_sha256'][relative]:
                        raise ValueError('Source differs from the audited allowlist: ' + relative)
                    info = tarfile.TarInfo(relative)
                    info.size, info.mode, info.mtime = len(data), 0o644, 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    archive.addfile(info, io.BytesIO(data))
                    members.append({'path': relative, 'original_sha256': digest, 'bytes': len(data)})
    with tarfile.open(target, 'r:gz') as archive:
        for member in members:
            public = archive.extractfile(member['path']).read()
            member['public_sha256'] = sha(public)
            if member['public_sha256'] != member['original_sha256'] or len(public) != member['bytes']:
                raise ValueError('Public archive differs from original input: ' + member['path'])
    archive_digest = sha(target.read_bytes())
    result = {'id': name, 'description': group['description'], 'archive': target.name,
              'archive_sha256': archive_digest, 'archive_bytes': target.stat().st_size,
              'manifest': name + '.MANIFEST.json', 'summary': name + '.SUMMARY.md',
              'member_count': len(members), 'audited_expected_hashes': len(group['expected_sha256'])}
    write_json(stage / result['manifest'], result | {'members': members, 'exclusion_rules': EXCLUSION_RULES})
    lines = ['# ' + name, '', group['description'], '',
             f"- [原始证据归档]({target.name})：{len(members)} 个文件，{target.stat().st_size} 字节。",
             f"- [逐文件 SHA-256 清单]({result['manifest']})。",
             '- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。',
             '- 归档 SHA-256：`' + archive_digest + '`。',
             '- 归档采用固定时间、固定权限和排序，保持可复现。', '',
             '## 文件', '', '| 路径 | 字节 | SHA-256 |', '|---|---:|---|']
    lines += ['| ' + row['path'] + ' | ' + str(row['bytes']) + ' | `' + row['public_sha256'] + '` |' for row in members]
    lines += ['', '## 排除规则', '', *['- ' + item for item in EXCLUSION_RULES], '']
    (stage / result['summary']).write_text('\n'.join(lines), encoding='utf-8')
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
