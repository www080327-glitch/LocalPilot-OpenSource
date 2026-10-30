"""Read-only local Vision transport. Model tools never receive filesystem paths."""
from pathlib import Path
from .build import BUILD
from .macos import MacOSAXAdapter


class LocalWindowVision:
    def __init__(self, root, *, transport=None):
        self.root=Path(root).resolve()
        self.transport=transport or MacOSAXAdapter([str(self.root)],binary=BUILD/'windowvision',timeout=8)
        if transport is None:
            if self.transport.request(op='status').get('vision_protocol')!=1:
                self.transport.close();raise RuntimeError('Build the local window vision helper')

    def locate(self, image, sha256, query):
        return self.transport.request(op='ocr',image=str(image),sha256=sha256,query=query)

    def compare(self, first, second):
        return self.transport.request(op='diff',image=first['path'],sha256=first['sha256'],
            other_image=second['path'],other_sha256=second['sha256'])

    def close(self):
        self.transport.close()
