from dataclasses import asdict
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from zipfile import ZipFile

from companion.config import Config, PrivateData
from companion.memory import MemoryStore, LexicalRetriever
from companion.observers import ReadScope
from companion.observers.documents import extract
from companion.escalation.provider import EscalationRequest, OpenAICompatibleProvider, validate_endpoint
from companion.triggers import NoticePolicy
from companion.runtime.service import Companion
from companion.runtime.launchd import plist, manage
from companion.tests.fixtures import make_documents, MARKER


class CompanionTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1]/".data"
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.docs = self.root / "documents"
        self.docs.mkdir()
        self.filename = self.root/"config.json"
        self.config_raw = {"low_power_policy":"off", "localpilot_endpoint":"", "data_dir":str(self.root/"state"), "watch_dirs":[str(self.docs)], "backend":"disabled", "quiet_start_hour":0, "quiet_end_hour":0}
        self.filename.write_text(json.dumps(self.config_raw))
        self.config = Config.load(self.filename)
        private = PrivateData(self.config.data_dir)
        self.store = MemoryStore(private.file("test.sqlite3"))
        self.scope = ReadScope(self.config)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_independent_imports(self):
        import ast
        for file in Path(__file__).resolve().parents[1].rglob("*.py"):
            if any(part.startswith(".") or part in {"evidence", "build", "dist", "__pycache__", "tests"} for part in file.parts):
                continue
            tree = ast.parse(file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith(("agent", "computer")))

    def test_formats_and_structure(self):
        files = make_documents(self.docs)
        expected = {".txt":"XINGHE", ".md":"10月8", ".docx":"小林", ".pptx":"文档检索", ".xlsx":"120", ".pdf":"October 8"}
        for file in files:
            before = file.read_bytes()
            content, _ = self.scope.read(file)
            doc = extract(content, file.suffix)
            self.assertIn(expected[file.suffix], doc.text)
            self.assertEqual(file.read_bytes(), before)
            self.assertTrue(doc.structure)
        self.assertIn("formula=SUM(B2:B3)", extract((self.docs/"星河项目/budget.xlsx").read_bytes(), ".xlsx").text)

    def test_bounded_extraction(self):
        doc = extract(b"x" * 1000, ".txt", 100)
        self.assertEqual(len(doc.text), 100)
        self.assertTrue(doc.truncated)

    def test_xml_entity_refused(self):
        b = BytesIO()
        with ZipFile(b, "w") as z:
            z.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY p SYSTEM "file:///etc/passwd">]><x/>')
        with self.assertRaises(ValueError):
            extract(b.getvalue(), ".docx")

    def test_zip_bomb_refused(self):
        b = BytesIO()
        with ZipFile(b, "w") as z:
            for i in range(3001):
                z.writestr(str(i), "")
        with self.assertRaises(ValueError):
            extract(b.getvalue(), ".docx")

    def test_symlink_and_outside_refused(self):
        outside = self.root/"secret.txt"
        outside.write_text("secret")
        link = self.docs/"link.txt"
        link.symlink_to(outside)
        for file in (outside, link):
            with self.assertRaises(PermissionError):
                self.scope.read(file)

    def test_sensitive_and_excluded_skipped(self):
        secret = self.docs/".ssh"
        secret.mkdir()
        (secret/"key.txt").write_text("private")
        excluded = self.docs/"excluded"
        excluded.mkdir()
        (excluded/"x.txt").write_text("private")
        self.config.exclude_dirs = (str(excluded),)
        scope = ReadScope(self.config)
        self.assertEqual(list(scope.scan()), [])

    def test_source_descriptor_readonly(self):
        file = self.docs/"readonly.txt"
        file.write_text("safe")
        opened = []
        original = os.open
        def record_open(name, flags, *args, **kwargs):
            opened.append((name, flags))
            return original(name, flags, *args, **kwargs)
        with patch("os.open", record_open):
            self.scope.read(file)
        flags = [v for k,v in opened if k == file.name][0]
        self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)

    def test_oversize_refused(self):
        self.config.max_file_bytes = 4
        file = self.docs/"too-large.txt"
        file.write_text("12345")
        with self.assertRaises(ValueError):
            self.scope.read(file)

    def test_config_rejects_writable_overlap(self):
        for value in (str(self.docs), str(self.docs/"own-state"), str(self.root), str(self.root/"unused/../documents/state")):
            self.filename.write_text(json.dumps(self.config_raw | {"data_dir":value}))
            with self.assertRaises(ValueError):
                Config.load(self.filename)

    def test_existing_user_directory_is_not_claimed_as_own_data(self):
        directory = self.root/"personal"
        directory.mkdir()
        file = directory/"notes.txt"
        file.write_text("user file")
        before = directory.stat().st_mode
        with self.assertRaises(ValueError):
            PrivateData(directory)
        self.assertEqual(directory.stat().st_mode, before)
        self.assertEqual(file.read_text(), "user file")

    def test_config_rejects_home_watch(self):
        self.filename.write_text(json.dumps(self.config_raw | {"watch_dirs":[str(Path.home())]}))
        with self.assertRaises(ValueError):
            Config.load(self.filename)

    def test_private_write_confined(self):
        private = PrivateData(self.config.data_dir)
        for name in ("../user.txt", "/tmp/user.txt"):
            with self.assertRaises(ValueError):
                private.write(name, "changed")
        self.assertEqual(private.root.stat().st_mode & 0o777, 0o700)

    def test_persistence_provenance_and_retrieval(self):
        self.store.add("user_fact", "我负责星河项目", "explicit_user_statement")
        self.store.add("reflection", "也许用户需要展示帮助", "companion", confidence=0.3, epistemic="reflection")
        filename = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        self.store.close()
        self.store = MemoryStore(filename)
        rows = LexicalRetriever(self.store).retrieve("星河项目")
        self.assertEqual(rows[0]["epistemic"], "factual")
        self.assertEqual(len(self.store.records()), 2)

    def test_reflection_never_fact(self):
        with self.assertRaises(ValueError):
            self.store.add("reflection", "guess", "model")

    def test_retrieval_budget(self):
        for i in range(10):
            self.store.add("document", "项目" * 3000, "fixture", "/allowed/doc.md")
        rows = LexicalRetriever(self.store).retrieve("项目", limit=3, max_chars=500)
        self.assertLessEqual(len(rows), 3)
        self.assertLessEqual(sum(len(str(r)) for r in rows), 500)

    def test_dnd_dedup_cooldown_daily_limit(self):
        p = NoticePolicy(self.config, self.store)
        t = datetime(2026,10,2,12).timestamp()
        self.assertTrue(p.allowed("greeting", "same", t))
        p.record("greeting", "same", "hello", now=t)
        self.assertFalse(p.allowed("greeting", "same", t+86400))
        self.assertFalse(p.allowed("help", "new", t+1))
        self.store.set("dnd", True)
        self.assertFalse(p.allowed("help", "later", t+86400))

    def test_ignored_notice_backoff(self):
        p = NoticePolicy(self.config, self.store)
        t = datetime(2026,10,2,12).timestamp()
        nid = p.record("project_help", "a", "hello", now=t)
        p.respond(nid, "ignore")
        self.assertFalse(p.allowed("other", "b", t+self.config.cooldown_seconds*1.5))
        self.assertEqual(self.store.get("ignore_streak"), 1)

    def test_quiet_overnight(self):
        self.config.quiet_start_hour, self.config.quiet_end_hour = 22, 8
        p = NoticePolicy(self.config, self.store)
        self.assertTrue(p.quiet(datetime(2026,10,2,23).timestamp()))
        self.assertTrue(p.quiet(datetime(2026,10,2,7).timestamp()))
        self.assertFalse(p.quiet(datetime(2026,10,2,12).timestamp()))

    def test_daily_limit(self):
        p = NoticePolicy(self.config, self.store)
        t = datetime(2026,10,2,12).timestamp()
        for i in range(self.config.max_notices_per_day):
            p.record("kind"+str(i), str(i), "hello", now=t-i*100)
        self.assertFalse(p.allowed("fresh", "fresh", t+10000))

    def test_endpoint_absent_safe(self):
        request = EscalationRequest("help", "manual", "complex", [], [], [], {"local_only":True}, "no action")
        result = OpenAICompatibleProvider(self.config).submit(request, approved=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["request"]["user_request"], "help")

    def test_endpoint_security(self):
        for url in ("https://example.com/v1", "http://localhost/v1", "http://127.0.0.1/v1?key=x", "http://a:b@127.0.0.1/v1", "http://127.0.0.1/v1#x"):
            with self.assertRaises(ValueError):
                validate_endpoint(url)
        self.assertEqual(validate_endpoint("http://127.0.0.1:8000/v1"), "http://127.0.0.1:8000/v1")

    def test_endpoint_explicit_approval(self):
        self.config.agent_endpoint = "http://127.0.0.1:8000/v1"
        self.config.agent_model = "test"
        request = EscalationRequest("help", "manual", "complex", [], [], [], {}, "none")
        self.assertEqual(OpenAICompatibleProvider(self.config).submit(request)["status"], "approval_required")

    def test_no_mutation_commands(self):
        instance = Companion(self.config)
        try:
            for cmd in ("write_file", "delete_file", "shell", "gui", "execute"):
                with self.assertRaises(ValueError):
                    instance.command({"command":cmd, "path":str(self.docs/"x.txt")})
        finally:
            instance.channel.server.server_close()
            instance.store.close()
            instance.lock.close()

    def test_index_dedup_delete_and_provenance(self):
        files = make_documents(self.docs)
        instance = Companion(self.config)
        try:
            before = {str(f):f.read_bytes() for f in files}
            instance.scan()
            count = len(instance.store.records())
            instance.scan()
            self.assertEqual(len(instance.store.records()), count)
            self.assertEqual(len(instance.store.records(kinds=["document"])), 6)
            self.assertTrue(all(r["epistemic"] == "factual" for r in instance.store.records(kinds=["document"])))
            self.assertTrue(all(f.read_bytes() == before[str(f)] for f in files))
            file = files[0]
            file.unlink()
            instance.process_file(str(file), "deleted")
            self.assertEqual(len(instance.store.records(kinds=["document"])), 5)
        finally:
            instance.channel.server.server_close()
            instance.store.close()
            instance.lock.close()

    def test_launchd_requires_confirmation_and_no_keepalive(self):
        private = PrivateData(self.config.data_dir)
        data = plist(self.filename, private.root)
        self.assertFalse(data["KeepAlive"])
        self.assertEqual(manage("install", self.filename, private)["status"], "confirmation_required")

    def test_model_disabled_explicit(self):
        from companion.model import ModelManager
        model = ModelManager(self.config)
        self.assertEqual(model.complete([{"role":"user","content":"hi"}])["status"], "unavailable")
        self.assertIsNone(model.child)

    def instance(self):
        obj = Companion(self.config)
        self.addCleanup(obj.lock.close)
        self.addCleanup(obj.store.close)
        self.addCleanup(obj.channel.server.server_close)
        return obj

    def test_background_filter_precedes_model(self):
        import time
        obj = self.instance()
        obj.model = Mock()
        obj.model.complete.return_value = {"status":"ok", "text":'{"notify":true,"confidence":0.9,"understood":true}'}
        now = time.time()
        obj.events.extend({"kind":"modified","project":"p","timestamp":now-i*10} for i in range(5))
        obj.store.set("dnd", True)
        obj.consider_help("p")
        obj.model.complete.assert_not_called()
        obj.store.set("dnd", False)
        obj.consider_help("p")
        obj.consider_help("p")
        self.assertEqual(obj.model.complete.call_count, 1)
        self.assertEqual(obj.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 1)

    def test_invalid_decision_stays_quiet_and_is_rate_limited(self):
        import time
        obj = self.instance()
        obj.model = Mock()
        obj.model.complete.return_value = {"status":"ok", "text":"I guess you need help!"}
        now = time.time()
        obj.events.extend({"kind":"modified","project":"p","timestamp":now-i*10} for i in range(5))
        obj.consider_help("p")
        obj.consider_help("p")
        self.assertEqual(obj.model.complete.call_count, 1)
        self.assertEqual(obj.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 0)
        self.assertTrue(obj.store.get("candidate_times"))

    def test_bad_model_greeting_uses_safe_fallback(self):
        obj = self.instance()
        self.config.model_path = "/fixture/model"
        obj.model = Mock()
        obj.model.complete.return_value = {"status":"ok", "text":"需要确认吗？"}
        obj.greet("startup")
        row = obj.store.db.execute("SELECT message FROM notices").fetchone()
        self.assertIn("你好", row[0])
        self.assertNotIn("确认", row[0])

    def test_formatted_model_limit_escalates_without_execute(self):
        obj = self.instance()
        obj.model = Mock()
        obj.model.complete.return_value = {"status":"truncated", "text":"**NEEDS_AGENT**\nLong explanation"}
        result = obj.ask("给出一个很困难的问题的答案。")
        self.assertEqual(result["status"], "escalation")
        self.assertEqual(result["escalation"]["status"], "unavailable")

    def test_memory_clear_pauses_reindex(self):
        make_documents(self.docs)
        obj = self.instance()
        obj.scan()
        obj.command({"command":"clear", "confirmation":"DELETE_COMPANION_MEMORY"})
        obj.scan()
        self.assertEqual(obj.store.records(), [])
        self.assertTrue(obj.store.get("indexing_paused"))
        obj.command({"command":"index"})
        self.assertEqual(len(obj.store.records(kinds=["document"])), 6)

    def test_revoked_scope_purges_document_sources(self):
        make_documents(self.docs)
        obj = self.instance()
        obj.scan()
        self.assertTrue(obj.store.records())
        self.config.exclude_dirs = (str(self.docs),)
        obj.scope = ReadScope(self.config)
        obj.scan()
        self.assertEqual(obj.store.records(), [])

    def test_search_finds_beyond_summary(self):
        self.store.add("document", "前面的摘要", "fixture", "/docs/a.md", metadata={"index_text":"x"*1500+"截止日期10月8日"})
        rows = LexicalRetriever(self.store).retrieve("截止日期")
        self.assertIn("10月8日", rows[0]["summary"])

    def test_model_metrics_survive_restart(self):
        from companion.model import ModelManager
        first = ModelManager(self.config, self.store)
        unavailable=first.complete([{"role":"user", "content":"hi"}])
        self.assertFalse(unavailable["model_called"])
        self.assertEqual(first.stats()["model_calls_last_hour"],0)
        adapter=Mock();adapter.complete.return_value={"status":"ok","text":"hi"}
        adapter.complete_structured=None
        first.adapter=adapter
        first.complete([{"role":"user", "content":"hi"}])
        second = ModelManager(self.config, self.store)
        self.assertEqual(second.stats()["model_calls_last_hour"], 1)

    def test_http_rejects_unauthenticated_and_browser_origin(self):
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from companion.channels import LocalChannel
        obj = LocalChannel(0, "secret", lambda *_: self.fail("Unauthorized command queued"))
        obj.start()
        try:
            url = f"http://127.0.0.1:{obj.port}/command"
            for headers in ({}, {"Authorization":"Bearer secret", "Origin":"https://untrusted.example"}):
                with self.assertRaises(HTTPError) as exc:
                    urlopen(Request(url, data=b'{"command":"status"}',headers=headers), timeout=5)
                self.assertEqual(exc.exception.code, 403)
                exc.exception.close()
        finally:
            obj.stop()

    def test_replaceable_model_adapter(self):
        from companion.model import ModelManager
        adapter = Mock()
        adapter.complete.return_value = {"status":"ok", "text":"adapter reply"}
        model = ModelManager(self.config, adapter=adapter)
        self.assertEqual(model.complete([{"role":"user", "content":"hi"}])["text"], "adapter reply")
        model.unload()
        adapter.unload.assert_called_once()

    def test_remote_permission_is_explicit_bool(self):
        self.filename.write_text(json.dumps(self.config_raw | {"agent_allow_remote":"false"}))
        with self.assertRaises(ValueError):
            Config.load(self.filename)

    def test_retrieval_rechecks_scope_even_after_scan_failure(self):
        obj = self.instance()
        obj.store.add("document", "private revoked project", "document_extractor", str(self.docs/"old.md"))
        self.config.exclude_dirs = (str(self.docs),)
        obj.scope = ReadScope(self.config)
        self.assertEqual(obj.retrieve("private revoked project"), [])

    def test_openai_transport_and_incomplete_refusal(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread
        from companion.escalation.provider import request_chat
        replies = [
            {"choices":[{"finish_reason":"stop","message":{"content":"local reply"}}],"model":"fixture"},
            {"choices":[{"finish_reason":"length","message":{"content":"partial"}}]},
            {"choices":[{"finish_reason":"stop","message":{"content":"tools","tool_calls":[{}]}}]}
        ]
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                data = json.dumps(replies.pop(0)).encode()
                self.send_response(200)
                self.send_header("Content-Length",str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        server = HTTPServer(("127.0.0.1",0), Handler)
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}/v1"
            self.assertEqual(request_chat(endpoint,"fixture",[{"role":"user","content":"hi"}])["text"], "local reply")
            for _ in range(2):
                with self.assertRaises(ValueError):
                    request_chat(endpoint,"fixture",[{"role":"user","content":"hi"}])
            self.assertTrue(all(not r["stream"] and "tools" not in r for r in seen))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_old_user_fact_is_searchable_beyond_recent_window(self):
        old_id = self.store.add("preference", "喜欢jadegreen颜色", "explicit_user_statement", timestamp=1)
        # New, unrelated event history must not evict an older matching fact.
        import uuid
        rows = [(uuid.uuid4().hex,"computer_event",100+i,"fixture","","unrelated event",1,"factual","{}") for i in range(2001)]
        self.store.db.executemany("INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?)", rows)
        self.store.db.commit()
        result = LexicalRetriever(self.store).retrieve("jadegreen")
        self.assertEqual(result[0]["id"], old_id)

    def test_simple_greeting_does_not_wake_model(self):
        obj = self.instance()
        obj.model = Mock()
        result = obj.ask("你好！")
        self.assertIn("你好", result["text"])
        self.assertEqual(result["model"]["status"], "not_called")
        obj.model.complete.assert_not_called()

    def test_boolean_confidence_cannot_enable_notification(self):
        import time
        obj = self.instance()
        obj.model = Mock()
        obj.model.complete.return_value = {"status":"ok", "text":'{"notify":true,"confidence":true,"understood":true}'}
        now = time.time()
        obj.events.extend({"kind":"modified","project":"p","timestamp":now-i*10} for i in range(5))
        obj.consider_help("p")
        self.assertEqual(obj.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
