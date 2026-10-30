"""Optional, pinned Node runtime. No PATH/Homebrew dependency or redirects."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tarfile
import uuid
import ssl
import sys
from urllib.error import URLError, HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from .channel_paths import private_directory, private_file, private_json
from .channels import save

VERSION = '22.23.4'
SOURCE = 'https://nodejs.org/dist/v' + VERSION + '/'
ARCHIVES = {
    'arm64': ('node-v22.23.4-darwin-arm64.tar.gz', 'c9e1dbc748b33ed2d14f42445191ecaf14c56259c7a9a26d0042c49ec2b66428'),
    'x86_64': ('node-v22.23.4-darwin-x64.tar.gz', 'efcc2b0db6f94bf53eddb038fe2b370277a042bd29e4f19b8f8e23598795b819'),
}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def installed(home):
    root = home / 'channel-node'
    if not root.exists() or not (root / 'installation.json').exists():
        return None
    private_directory(root)
    record = private_json(root / 'installation.json')
    binary = private_file(root / 'node')
    if record.get('version') != VERSION or digest(binary) != record.get('binary_sha256'):
        raise ValueError('CHANNEL_NODE_INTEGRITY_FAILED')
    return binary

def install(home):
    from .channels import locked
    root = private_directory(home / 'channel-node', create=True)
    with locked(root):
        return _install(home)

def _install(home):
    if platform.system() != 'Darwin' or platform.machine() not in ARCHIVES:
        raise ValueError('CHANNEL_NODE_PLATFORM_NOT_SUPPORTED')
    existing = installed(home)
    if existing:
        return {'status': 'installed', 'version': VERSION, 'downloaded': False}
    root = private_directory(home / 'channel-node', create=True)
    name, checksum = ARCHIVES[platform.machine()]
    partial = private_file(root / (name + '.part'), create=True)
    cancel = root / 'cancel'
    cancel.unlink(missing_ok=True)
    if shutil.disk_usage(root).free < 512 * 1024 ** 2:
        raise ValueError('CHANNEL_NODE_INSUFFICIENT_DISK')
    # A partial transfer is only a cache. Nothing executes before the full pin matches.
    bundled = Path(sys.executable).resolve().parents[2] / 'channel-runtime' / name
    used_bundled = bundled.is_file() and digest(bundled) == checksum
    if used_bundled:
        shutil.copyfile(bundled, partial)
        partial.chmod(0o600)
    offset = partial.stat().st_size
    # A complete verified cache survives a crash before extraction; no Range request is needed.
    if partial.stat().st_size == 0 or digest(partial) != checksum:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        request = Request(SOURCE + name, headers={'Range': 'bytes=' + str(offset) + '-'} if offset else {})
        try:
            with opener.open(request, timeout=20) as response:
                resumed = offset and response.status == 206 and response.headers.get('Content-Range', '').startswith('bytes ' + str(offset) + '-')
                with partial.open('ab' if resumed else 'wb') as output:
                    while True:
                        if cancel.exists():
                            return {'status': 'cancelled', 'partial_preserved': True}
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        if output.tell() > 100 * 1024 ** 2:
                            raise ValueError('CHANNEL_NODE_DOWNLOAD_SIZE_REJECTED')
                    output.flush()
                    os.fsync(output.fileno())
        except HTTPError as error:
            code=error.code;error.close()
            raise ValueError('CHANNEL_NODE_HTTP_' + str(code)) from None
        except URLError as error:
            if isinstance(error.reason,ssl.SSLCertVerificationError):
                raise ValueError('CHANNEL_NODE_TLS_VERIFICATION_FAILED') from None
            raise ValueError('CHANNEL_NODE_DOWNLOAD_INTERRUPTED_RETRY_SAFE') from None
        except (OSError, TimeoutError):
            raise ValueError('CHANNEL_NODE_DOWNLOAD_INTERRUPTED_RETRY_SAFE') from None
    if digest(partial) != checksum:
        os.replace(partial, root / (name + '.invalid-' + uuid.uuid4().hex))
        raise ValueError('CHANNEL_NODE_ARCHIVE_CHECKSUM_FAILED')
    prefix = name.removesuffix('.tar.gz') + '/'
    # Do not extract paths, links, npm, scripts, or arbitrary archive members.
    with tarfile.open(partial, 'r:gz') as archive:
        for member_name, target_name, maximum in [('bin/node', 'node', 160 * 1024 ** 2), ('LICENSE', 'LICENSE', 1024 ** 2)]:
            member = archive.getmember(prefix + member_name)
            if not member.isfile() or member.size > maximum:
                raise ValueError('CHANNEL_NODE_ARCHIVE_LAYOUT_REJECTED')
            target = private_file(root / (target_name + '.' + uuid.uuid4().hex + '.new'))
            with archive.extractfile(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
                output.flush(); os.fsync(output.fileno())
            target.chmod(0o700 if target_name == 'node' else 0o600)
            os.replace(target, root / target_name)
    save(root / 'installation.json', {'version': VERSION, 'source': SOURCE + name,
        'archive_sha256': checksum, 'binary_sha256': digest(root / 'node'),
        'source_verification': 'HTTPS and pinned official SHASUMS256; release signature NOT_VERIFIED'})
    return {'status': 'installed', 'version': VERSION, 'downloaded': not used_bundled, 'bundled_runtime': used_bundled}
