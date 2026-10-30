"""Packaging contracts: real loopback/process transport, scripted model only."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError

from agent.backends import Message
from agent.persistence import backend_identity, PersistenceError
from agent.stabilization import evaluate_verification
from localpilot_service.backend_contract import ServiceOpenAIBackend, generation_options
from localpilot_service.backup import copy_database
from localpilot_service.deployment import build
from localpilot_service.sdk import Client
from localpilot_api.service import TaskRequest
from localpilot_service.verification import configured_verifier
from localpilot_service.model_manager import HTTPModelManager
from tests.test_local_http_backend import MockServer, completion, sse
from tests.test_runtime_api import call
from unittest.mock import patch


class ServiceContractsTests(unittest.TestCase):
    def test_deployed_stream_usage_reaches_provider_and_checkpoint_identity(self):
        model=MockServer()
        try:
            model.add(sse({"model":"mock-local","choices":[{"index":0,"delta":{"content":"USAGE-FIXTURE"},"finish_reason":"stop"}]},
                          {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}), content_type="text/event-stream")
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);workspace=root/"workspace";workspace.mkdir()
                config={"schema_version":1,"port":0,"data_dir":str(root/"data"),"clients":[{"subject":"test","token_env":"LP_STREAM_USAGE_FIXTURE"}],
                    "routes":{"localpilot":{"workspace":str(workspace),"backend":{"kind":"local-openai","base_url":model.base_url,"model":"mock-local","include_stream_usage":True},"cloud_egress":"LOCAL_ONLY"}}}
                path=root/"service.json";path.write_text(json.dumps(config));path.chmod(0o600)
                with patch.dict(os.environ,{"LP_STREAM_USAGE_FIXTURE":"u"*32}):server=build(path)
                try:
                    task=server.service.create_task(TaskRequest(input="Return the marker"))
                    done=server.service.wait(task["id"])
                    self.assertEqual(done["status"],"completed")
                    self.assertEqual(done["result"]["model_calls"][0]["input_tokens"],4)
                    self.assertEqual(done["result"]["model_calls"][0]["output_tokens"],2)
                    self.assertEqual(model.requests[0]["stream_options"],{"include_usage":True})
                finally:server.service.shutdown();server.server_close();server.access.close()
                config["routes"]["localpilot"]["backend"]["include_stream_usage"]="false"
                path.write_text(json.dumps(config))
                with patch.dict(os.environ,{"LP_STREAM_USAGE_FIXTURE":"u"*32}):
                    with self.assertRaises(ValueError):build(path)
            a=ServiceOpenAIBackend(base_url=model.base_url,model="mock-local",include_stream_usage=True)
            b=ServiceOpenAIBackend(base_url=model.base_url,model="mock-local",include_stream_usage=False)
            self.assertNotEqual(backend_identity(a),backend_identity(b))
        finally:model.close()

    def test_manager_http_adapter_uses_protected_fixed_endpoint(self):
        server=MockServer()
        try:
            manager=HTTPModelManager(server.base_url.removesuffix("/v1"),token="manager-fixture-token")
            manager.list_models()
            server.add({"id":"job-fixture","status":"queued"})
            self.assertEqual(manager.ensure("registered",grant_id="host-grant",idempotency_key="fixed")["id"],"job-fixture")
            self.assertEqual(server.headers[-1],("/model-manager/v1/jobs","Bearer manager-fixture-token"))
            self.assertEqual(server.requests[-1],{"model_id":"registered","grant_id":"host-grant","operation":"ensure"})
            with self.assertRaises(ValueError):HTTPModelManager("http://remote.example",token="test")
        finally:server.close()

    def test_service_to_scripted_openai_model_api_and_real_connection_failure(self):
        model=MockServer()
        try:
            model.add(completion(calls=[call("read_file",{"path":"fact.txt"},"read").to_dict()]))
            model.add(completion("MODEL-API-FIXTURE"))
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);workspace=root/"workspace";workspace.mkdir();(workspace/"fact.txt").write_text("MODEL-API-FIXTURE")
                config={"schema_version":1,"port":0,"data_dir":str(root/"data"),"clients":[{"subject":"python","token_env":"LP_MODEL_FIXTURE_TOKEN"}],
                    "routes":{"localpilot":{"workspace":str(workspace),"backend":{"kind":"local-openai","base_url":model.base_url,"model":"mock-local","timeout":.2,"capabilities":{"tool_calling":True,"streaming":False}},"cloud_egress":"LOCAL_ONLY","capabilities":{"read":True,"write":False,"execute":False,"read_only":True}}}}
                path=root/"service.json";path.write_text(json.dumps(config));path.chmod(0o600)
                with patch.dict(os.environ,{"LP_MODEL_FIXTURE_TOKEN":"f"*32}):server=build(path)
                thread=threading.Thread(target=server.serve_forever,kwargs={"poll_interval":.02},daemon=True);thread.start()
                try:
                    client=Client("http://127.0.0.1:"+str(server.server_port),token="f"*32)
                    task=client.submit("Read fact.txt",idempotency_key="model-api")
                    done=server.service.wait(task["id"])
                    self.assertEqual(done["status"],"completed");self.assertEqual(done["tools"][0]["payload"]["result"],"MODEL-API-FIXTURE")
                    model.close();model=None
                    bad=client.submit("Read again",idempotency_key="closed-model-api")
                    failed=server.service.wait(bad["id"])
                    self.assertEqual(failed["status"],"failed")
                    self.assertFalse(client.status(bad["id"])["service"]["route_decision"]["backend_fallback"])
                finally:
                    server.shutdown();thread.join();server.service.shutdown();server.server_close();server.access.close()
        finally:
            if model:model.close()

    def test_generation_schema_and_restore_fingerprint(self):
        backend=ServiceOpenAIBackend(base_url="http://127.0.0.1:9/v1", model="host-model", generation_parameters={"temperature":.2,"seed":3})
        payload=backend._payload([Message("system","host"),Message("user","hi")],[],128)
        self.assertEqual(payload["temperature"],.2);self.assertEqual(payload["seed"],3)
        other=ServiceOpenAIBackend(base_url="http://127.0.0.1:9/v1", model="host-model", generation_parameters={"temperature":.8})
        self.assertNotEqual(backend_identity(backend),backend_identity(other))
        for value in [{"model":"arbitrary"},{"temperature":False},{"top_p":float("nan")},{"stop":[5]}]:
            with self.assertRaises(ValueError):generation_options(value)

    def test_host_verification_rejects_changed_resource_and_wrong_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"a.txt").write_text("expected")
            spec={"id":"fixture-contract","files":{"a.txt":hashlib.sha256(b"expected").hexdigest()},"required_text":"expected"}
            verifier=configured_verifier(root,spec)
            from types import SimpleNamespace
            self.assertEqual(evaluate_verification(root,verifier(root,SimpleNamespace(text="expected")))[0],"passed")
            self.assertEqual(evaluate_verification(root,verifier(root,SimpleNamespace(text="wrong")))[0],"failed")
            (root/"a.txt").write_text("changed")
            self.assertEqual(evaluate_verification(root,verifier(root,SimpleNamespace(text="expected")))[0],"failed")
            spec["files"]={"../outside":hashlib.sha256(b"x").hexdigest()}
            with self.assertRaises(ValueError):configured_verifier(root,spec)

    def test_backup_is_sqlite_snapshot_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/"source.db"
            conn=sqlite3.connect(source);conn.execute("CREATE TABLE proof(x)");conn.execute("INSERT INTO proof VALUES(42)");conn.commit();source.chmod(0o600)
            target=root/"backup.db";copy_database(source,target)
            other=sqlite3.connect(target);self.assertEqual(other.execute("SELECT x FROM proof").fetchone()[0],42);other.close()
            with self.assertRaises(FileExistsError):copy_database(source,target)
            link=root/"link.db";link.symlink_to(source)
            with self.assertRaises(ValueError):copy_database(link,root/"bad.db")
            conn.close()

    def test_formal_deployment_entrypoint_and_health(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);workspace=root/"workspace";workspace.mkdir()
            config={"schema_version":1,"port":0,"data_dir":str(root/"data"),"clients":[{"subject":"test","token_env":"LP_CONTRACT_TEST_TOKEN"}],
                "routes":{"localpilot":{"workspace":str(workspace),"backend":{"kind":"unavailable","model":"not-deployed"},"cloud_egress":"LOCAL_ONLY"}}}
            path=root/"service.json";path.write_text(json.dumps(config));path.chmod(0o600)
            env={**os.environ,"LP_CONTRACT_TEST_TOKEN":"t"*32}
            result=subprocess.run([sys.executable,"-m","localpilot_service","--config",str(path),"--check"],capture_output=True,text=True,env=env,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(result.stdout)["valid"])
            with patch.dict(os.environ,env):server=build(path)
            thread=threading.Thread(target=server.serve_forever,kwargs={"poll_interval":.02},daemon=True);thread.start()
            try:
                client=Client("http://127.0.0.1:"+str(server.server_port),token="t"*32)
                self.assertEqual(client.request("/healthz")["model_health"],"NOT_PROBED")
                self.assertEqual(client.request("/openapi.json")["openapi"],"3.1.0")
                with self.assertRaises(HTTPError) as unavailable:
                    client.request("/localpilot/v1/sessions", {})
                self.assertEqual(unavailable.exception.code,409);unavailable.exception.close()
                with self.assertRaises(HTTPError) as caught:client.submit("hi",idempotency_key="not-deployed")
                self.assertEqual(caught.exception.code,503);caught.exception.close()
            finally:
                server.shutdown();thread.join();server.service.suspend();server.server_close();server.access.close()
            path.chmod(0o644)
            with self.assertRaises(ValueError):build(path)
            path.chmod(0o600)
            config["routes"]["localpilot"]["capabilities"] = {"execute":"false"}
            path.write_text(json.dumps(config))
            with patch.dict(os.environ,env):
                with self.assertRaises(ValueError):build(path)

    def test_openapi_schema_validates_real_task_evidence(self):
        try:import jsonschema
        except ImportError:self.skipTest("Optional JSON Schema validator unavailable")
        root=Path(__file__).resolve().parents[1]
        spec=json.loads((root/"localpilot_service/openapi.json").read_text())
        jsonschema.Draft202012Validator.check_schema(spec["components"]["schemas"]["Task"])
        fixture=root/"docs/evidence/agent-service-20261013/real-first/python-task.json"
        if fixture.exists():jsonschema.validate(json.loads(fixture.read_text()),spec["components"]["schemas"]["Task"])


if __name__=="__main__":unittest.main()
