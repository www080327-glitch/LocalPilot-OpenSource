import hashlib
from pathlib import Path
import tempfile
import unittest
from localpilot_suite.model_integrity import check_files

class IntegrityTests(unittest.TestCase):
    def test_hashes_weights_and_git_blob_configuration_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);weight=b'controlled test weight bytes';config=b'{}'
            (root/'model.safetensors').write_bytes(weight);(root/'config.json').write_bytes(config)
            info={'siblings':[{'rfilename':'model.safetensors','lfs':{'sha256':hashlib.sha256(weight).hexdigest()}},{'rfilename':'config.json','blobId':hashlib.sha1(b'blob 2\0'+config).hexdigest()}]}
            self.assertEqual(len(check_files(root,info)['files']),2)
            (root/'model.safetensors').write_bytes(b'changed')
            with self.assertRaises(ValueError):check_files(root,info)
    def test_repository_filename_cannot_escape_model_directory(self):
        with self.assertRaises(ValueError):check_files(Path('/unused'),{'siblings':[{'rfilename':'../secret.bin'}]})
