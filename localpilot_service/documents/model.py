"""Document Representation v2 and host resource ceilings."""
from dataclasses import dataclass, asdict
import hashlib
import json

VERSION = '2.0'
PARSER_REVISION = '2.0.1'


@dataclass(frozen=True)
class Budgets:
    batch_bytes: int = 2 * 1024**3
    storage_bytes: int = 8 * 1024**3
    free_disk_bytes: int = 512 * 1024**2
    expanded_bytes: int = 256 * 1024**2
    member_bytes: int = 32 * 1024**2
    archive_entries: int = 20000
    compression_ratio: int = 200
    nodes: int = 250000
    node_chars: int = 2000
    text_bytes: int = 128 * 1024**2
    pixels: int = 32_000_000
    image_bytes: int = 24 * 1024**2
    worker_memory_bytes: int = 512 * 1024**2
    worker_seconds: int = 120
    import_seconds: int = 120
    output_bytes: int = 256 * 1024**2
    preview_bytes: int = 512 * 1024
    search_seconds: int = 3
    search_scan_bytes: int = 4 * 1024**2

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in asdict(self).values()):
            raise ValueError('Budgets must be positive host integers')

    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def node(kind, text='', *, anchor=None, **properties):
    """All content is untrusted; anchors describe the parser's observed location."""
    return {'kind': kind, 'text': text, 'anchor': anchor or {},
            'properties': properties, 'trust': 'untrusted_document_data'}
