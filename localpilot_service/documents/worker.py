"""One-shot parser process. Output is bounded NDJSON, with no source paths."""
import json
import sys
import resource
import time
from dataclasses import asdict
from .model import Budgets
from .parsers import parse


def main():
    path, name, budget = sys.argv[1:]
    b = Budgets(**json.loads(budget))
    resource.setrlimit(resource.RLIMIT_CPU, (b.worker_seconds, b.worker_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (b.output_bytes, b.output_bytes))
    count = total = 0
    started=time.monotonic()
    try:
        for record in parse(path, name, b):
            value = record['text']
            for offset in range(0, max(len(value), 1), b.node_chars):
                item = {**record, 'text': value[offset:offset + b.node_chars]}
                if len(value) > b.node_chars:
                    item['anchor'] = {**record['anchor'], 'text_offset': offset}
                total += len(item['text'].encode())
                count += 1
                if count > b.nodes or total > b.text_bytes:
                    raise ValueError('document_node_or_text_budget')
                print(json.dumps({'node': item}, ensure_ascii=False), flush=True)
        print(json.dumps({'end': True, 'nodes': count, 'text_bytes': total, 'parser_seconds':time.monotonic()-started}), flush=True)
    except Exception as e:
        # Third-party exception messages may contain absolute paths or raw text.
        reason = str(e) if type(e).__module__ == 'localpilot_service.documents.parsers' else type(e).__name__
        print(json.dumps({'error': type(e).__name__, 'reason': reason[:160]}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
