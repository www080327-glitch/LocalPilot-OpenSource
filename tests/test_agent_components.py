import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deepseek import DeepSeekBackend
from agent.registry import create_default_registry
from agent.schemas import TOOL_SCHEMAS
from agent.tools import file_info, list_directory, read_file, search_text


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "notes.txt").write_text("hello", encoding="utf-8")
        (self.root / "folder").mkdir()
        (self.root / "folder" / "inside.txt").write_text("inside", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_file_and_list_directory(self):
        self.assertEqual(read_file(self.root, "notes.txt"), "hello")
        self.assertEqual(list_directory(self.root), ["folder", "notes.txt"])
        self.assertEqual(list_directory(self.root, "folder"), ["inside.txt"])

    def test_rejects_paths_outside_workspace(self):
        with self.assertRaises(ValueError):
            read_file(self.root, "../outside.txt")
        with self.assertRaises(ValueError):
            list_directory(self.root, str(self.root.parent))

    def test_rejects_symlink_that_escapes_workspace(self):
        outside = self.root.parent / "localpilot-outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "outside-link.txt"
        try:
            link.symlink_to(outside)
            with self.assertRaises(ValueError):
                read_file(self.root, "outside-link.txt")
        finally:
            outside.unlink(missing_ok=True)

    def test_search_text_returns_bounded_line_matches(self):
        (self.root / "folder" / "other.py").write_text("def FIND_ME():\n    return 1\n", encoding="utf-8")
        matches = search_text(self.root, "find_me", file_pattern="*.py", case_sensitive=False)
        self.assertEqual(matches, [{"path": "folder/other.py", "line": 1, "text": "def FIND_ME():"}])
        self.assertEqual(search_text(self.root, "find_me", file_pattern="*.txt"), [])
        (self.root / "second.py").write_text("FIND_ME again\n", encoding="utf-8")
        self.assertEqual(len(search_text(self.root, "FIND_ME", max_results=1)), 1)

    def test_search_text_skips_ignored_directories_and_rejects_escape(self):
        ignored = self.root / ".venv"
        ignored.mkdir()
        (ignored / "secret.txt").write_text("hiddenmarker", encoding="utf-8")
        outside = self.root.parent / "search-outside.txt"
        outside.write_text("outside_marker", encoding="utf-8")
        link = self.root / "escape.txt"
        try:
            link.symlink_to(outside)
            self.assertEqual(search_text(self.root, "hiddenmarker"), [])
            self.assertEqual(search_text(self.root, "outside_marker"), [])
            self.assertEqual(search_text(self.root, "hiddenmarker", path=".venv"), [])
        finally:
            outside.unlink(missing_ok=True)

    def test_file_info_reports_file_and_directory_metadata(self):
        self.assertEqual(file_info(self.root, "notes.txt"), {
            "path": "notes.txt", "type": "file", "size_bytes": 5
        })
        self.assertEqual(file_info(self.root, "folder"), {
            "path": "folder", "type": "directory", "size_bytes": None
        })


class RegistryTests(unittest.TestCase):
    def test_default_registry_calls_tools_and_exposes_schemas(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "a.txt").write_text("A", encoding="utf-8")
            registry = create_default_registry(root)
            self.assertEqual(registry.call("read_file", {"path": "a.txt"}), "A")
            self.assertEqual([s["function"]["name"] for s in registry.schemas()], [
                "read_file", "list_directory", "search_text", "file_info", "execute", "apply_patch"
            ])
            self.assertEqual(registry.call("search_text", {"query": "A"})[0]["path"], "a.txt")
            self.assertEqual(registry.call("file_info", {"path": "a.txt"})["size_bytes"], 1)

    def test_schemas_use_function_calling_shape(self):
        self.assertEqual([schema["type"] for schema in TOOL_SCHEMAS], ["function"] * 6)
        self.assertEqual(TOOL_SCHEMAS[0]["function"]["parameters"]["required"], ["path"])


class DeepSeekBackendTests(unittest.TestCase):
    def test_reads_api_key_from_environment_and_sends_tool_schemas(self):
        response_data = b'{"choices": []}'

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return response_data

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            backend = DeepSeekBackend()
        with patch("agent.deepseek.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            result = backend.chat([{"role": "user", "content": "hi"}], tools=TOOL_SCHEMAS)

        request = mocked_urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(body["tools"], TOOL_SCHEMAS)
        self.assertEqual(result, {"choices": []})

    def test_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                DeepSeekBackend()


if __name__ == "__main__":
    unittest.main()
