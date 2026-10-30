"""Resume a pinned installer; only a complete checksum may become installable."""
import hashlib
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen


def fetch(url, destination, size, sha256, opener=urlopen):
    destination = Path(destination)
    partial = destination.with_name(destination.name + '.partial')
    for path in (destination, partial):
        if path.is_symlink():
            raise ValueError('Unsafe installer cache path')
    def verified(path):
        with path.open('rb') as stream:
            return path.stat().st_size == size and hashlib.file_digest(stream, 'sha256').hexdigest() == sha256
    if destination.exists():
        if not verified(destination):
            raise ValueError('安装包校验失败，原文件保留；请在 Finder 中移到废纸篓后重试')
        return {'resumed_bytes': 0, 'verified': True, 'cached': True}
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > size:
        raise ValueError('下载文件超过预期大小，已保留；请检查下载缓存')
    if offset != size:
        request = Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
        try:
            with opener(request, timeout=60) as source:
                status = source.status
                if offset and status == 206:
                    content_range = source.headers.get('Content-Range', '')
                    if not re.fullmatch(rf'bytes {offset}-[0-9]+/{size}', content_range):
                        raise ValueError('下载续传范围不匹配，未修改原文件')
                elif status == 200:
                    # Server ignores Range: restart this known partial, never append duplicate bytes.
                    offset = 0
                else:
                    raise ValueError('下载服务暂不支持续传，请稍后重试')
                fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW |
                             (os.O_APPEND if offset else os.O_TRUNC), 0o600)
                with os.fdopen(fd, 'wb') as output:
                    count = offset
                    while block := source.read(1024 * 1024):
                        count += len(block)
                        if count > size:
                            raise ValueError('下载文件超过预期大小')
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
        except (OSError, TimeoutError) as error:
            raise ValueError('下载中断，已保留进度。恢复网络后点击重试') from None
    if not verified(partial):
        if partial.stat().st_size==size:
            import uuid
            partial.rename(partial.with_name(partial.name+'.failed-'+uuid.uuid4().hex))
            raise ValueError('安装包校验失败，已隔离原文件。点击重试可重新下载')
        raise ValueError('安装包不完整，未安装；下载进度已保留，点击重试可继续')
    os.replace(partial, destination)
    return {'resumed_bytes': offset, 'verified': True, 'cached': False}
