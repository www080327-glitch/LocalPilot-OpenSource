"""Offline transport controls and isolated real HTTP / scripted Runtime integration."""
from dataclasses import replace
from email.message import Message
from io import BytesIO
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from companion.escalation.localpilot import (LocalPilotProvider, MockLocalPilotProvider,
    TransportFailure, endpoint_origin, prepare_context, result_memory, task_view)
from companion.escalation.provider import EscalationRequest


def config(**kwargs):
    return SimpleNamespace(localpilot_endpoint="http://127.0.0.1:18765/v1",
                           localpilot_route="localpilot", localpilot_api_key_env="COMPANION_TEST_API_KEY",
                           localpilot_host_local_only=True, **kwargs)


def request(text="Read the approved source and explain it", local_only=True):
    return EscalationRequest(text, "manual", "complex", [
        {"id": "fact1", "type": "document", "text": "Source fact", "source_reference": "/approved/report.txt",
         "epistemic": "factual", "provenance": {"file_hash": "abc", "version_id": "version1"}},
        {"id": "guess1", "text": "Model guess", "epistemic": "inferred"}],
        ["/approved/report.txt"], [], {"local_only": local_only, "requires_user_approval": True}, "Prepared only")


def task(status="completed", quiet=True, text="done"):
    return {"id": "resp_test", "session_id": "sess_test", "object": "localpilot.task", "status": status,
            "quiescent": quiet, "result": {"text": text, "verification_status": "not_run"},
            "required_action": {"id": "approval1", "type": "approval"} if status == "requires_approval" else None,
            "last_event_id": 3}


class Response(BytesIO):
    def __init__(self, value, content_type="application/json"):
        super().__init__(value if isinstance(value, bytes) else json.dumps(value).encode())
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class AdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.provider = LocalPilotProvider(config())
        self.env = patch.dict(os.environ, {"COMPANION_TEST_API_KEY": "test-only-key"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_origin_local_and_https_remote_rules(self):
        self.assertEqual(endpoint_origin("http://127.0.0.1:8765/v1"), ("http://127.0.0.1:8765", True))
        self.assertEqual(endpoint_origin("http://[::1]:8765"), ("http://[::1]:8765", True))
        for endpoint in ("http://localhost:8765", "http://example.com", "http://user:pass@127.0.0.1",
                         "http://127.0.0.1/path", "http://127.0.0.1?token=secret", "https://example.com"):
            with self.assertRaises(ValueError):
                endpoint_origin(endpoint)
        self.assertEqual(endpoint_origin("https://example.com/v1", True), ("https://example.com", False))

    def test_configured_discovery_does_not_claim_model_health(self):
        self.provider.opener = Mock()
        self.provider.opener.open.return_value = Response({"data": [{"id": "localpilot"}]})
        result = self.provider.health()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["backend_execution"], "unknown")
        self.assertEqual(self.provider.opener.open.call_args.args[0].full_url, "http://127.0.0.1:18765/v1/models")

    def test_explicit_task_approval_does_not_call_network(self):
        self.provider.opener = Mock()
        for grant in (False, None, 1, "true", {"approved": True}):
            result = self.provider.submit(request(), approved=grant)
            self.assertEqual(result["status"], "approval_required")
            self.assertEqual(result["task_execution"], "not_started")
        self.provider.opener.open.assert_not_called()

    def test_remote_each_call_needs_current_cloud_grant_and_privacy_scope(self):
        remote_config = config(localpilot_allow_remote=True)
        remote_config.localpilot_endpoint = "https://example.com/v1"
        remote_config.localpilot_host_local_only = False
        remote_config.localpilot_allow_cloud = True
        provider = LocalPilotProvider(remote_config)
        provider.opener = Mock()
        self.assertEqual(provider.health()["error"]["code"], "cloud_approval_required")
        self.assertEqual(provider.submit(request(), approved=True, cloud_approved=True)["error"]["code"], "local_only_context")
        self.assertEqual(provider.submit(request(local_only=False), approved=True)["status"], "approval_required")
        provider.opener.open.assert_not_called()
        provider.opener.open.return_value = Response(task())
        self.assertEqual(provider.submit(request(local_only=False), approved=True, cloud_approved=True)["status"], "completed")
        self.assertEqual(provider.status("resp_test")["error"]["code"], "cloud_approval_required")

    def test_loopback_host_processing_policy_requires_trusted_declaration(self):
        unknown = config()
        unknown.localpilot_host_local_only = False
        provider = LocalPilotProvider(unknown)
        provider.opener = Mock()
        for cloud in (False, True):
            result = provider.submit(request(), approved=True, cloud_approved=cloud)
            self.assertEqual(result["error"]["code"], "host_policy_unknown")
            self.assertEqual(result["phase"], "not_submitted")
        self.assertEqual(provider.submit(request(local_only=False), approved=True, cloud_approved=True)["error"]["code"], "cloud_disabled")
        provider.allow_cloud = True
        self.assertEqual(provider.submit(request(local_only=False), approved=True)["error"]["code"], "cloud_approval_required")
        provider.opener.open.assert_not_called()
        provider.opener.open.return_value = Response(task())
        self.assertEqual(provider.submit(request(local_only=False), approved=True, cloud_approved=True)["status"], "completed")

    def test_no_host_control_key_and_tool_approval_is_refused(self):
        self.provider.opener = Mock()
        self.provider.opener.open.return_value = Response(task("requires_approval"))
        with patch.dict(os.environ, {"LOCALPILOT_API_CONTROL_TOKEN": "must-not-leak"}):
            view = self.provider.submit(request(), approved=True, submission_id="reviewed-one")
            req = self.provider.opener.open.call_args.args[0]
            self.assertNotIn("X-localpilot-control-token", req.headers)
            self.assertNotIn(b"must-not-leak", req.data)
            self.assertEqual(view["phase"], "awaiting_host")
            count = self.provider.opener.open.call_count
            self.assertEqual(self.provider.approve(view["task_id"], approved=True)["status"], "host_control_required")
            self.assertEqual(self.provider.opener.open.call_count, count)

    def test_timeout_and_5xx_submission_are_unknown_without_retry(self):
        for failure in (TransportFailure("transport_timeout"), TransportFailure("server_error", 500),
                        TransportFailure("invalid_task_contract")):
            with patch.object(self.provider, "_request", side_effect=failure) as send:
                result = self.provider.submit(request(), approved=True, submission_id="reviewed-unknown")
                self.assertEqual(result["status"], "submission_unknown")
                self.assertEqual(result["task_execution"], "unknown")
                self.assertEqual(result["submission_id"], "reviewed-unknown")
                self.assertFalse(result["automatic_retry"])
                send.assert_called_once()

    def test_short_http_body_is_unknown_and_invalid_json_is_rejected(self):
        response = Response(task())
        response.read = Mock(side_effect=IncompleteRead(b"partial", 100))
        self.provider.opener = Mock()
        self.provider.opener.open.return_value = response
        result = self.provider.submit(request(), approved=True, submission_id="reviewed-short-body")
        self.assertEqual(result["status"], "submission_unknown")
        self.assertEqual(result["error"]["code"], "incomplete_response")
        self.provider.opener.open.assert_called_once()
        self.provider.opener.open.return_value = Response(b'{"number":NaN}')
        result = self.provider.status("resp_test")
        self.assertEqual(result["error"]["code"], "invalid_response")

    def test_missing_key_no_submission_and_exception_details_not_exposed(self):
        with patch.dict(os.environ, {}, clear=True):
            result = self.provider.submit(request(), approved=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["task_execution"], "not_started")

    def test_context_provenance_inference_bounds_and_secret_filter(self):
        source = request()
        source.relevant_memories += [
            {"id": "secret", "sensitivity": "secret", "text": "do-not-export"},
            {"id": "redact", "text": "api_key=abcdef password=unsafe", "metadata": {"access_token": "unsafe", "window_title": "public"}},
            {"id": "large", "text": "x" * 9000}]
        context, digest = prepare_context(source, 1200)
        encoded = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("do-not-export", encoded)
        self.assertNotIn("abcdef", encoded)
        self.assertNotIn("unsafe", encoded)
        self.assertEqual(context["source_context"]["memories"][0]["provenance"]["version_id"], "version1")
        self.assertEqual(context["source_context"]["memories"][1]["epistemic"], "inferred")
        self.assertLessEqual(len(json.dumps(context["source_context"], ensure_ascii=False)), 1200)
        self.assertGreater(context["source_context"]["omitted_records"], 0)
        changed = replace(source, user_request="Different user request")
        self.assertNotEqual(prepare_context(changed, 1200)[1], digest)

    def test_local_private_observation_remote_filter_and_chinese_redaction(self):
        source = request("请解释文档。密码：不能外传 令牌=禁止发送")
        source.relevant_memories.append({"id": "native1", "sensitivity": "private", "timestamp": 42,
                                        "dedupe_key": "dedupe1", "observation_id": "obs1", "evidence": {"title": "工作文档"}})
        local, _ = prepare_context(source, allow_private=True)
        remote, _ = prepare_context(source)
        self.assertEqual(local["source_context"]["memories"][-1]["observation_id"], "obs1")
        self.assertEqual(local["source_context"]["memories"][-1]["timestamp"], 42)
        self.assertNotIn("native1", json.dumps(remote, ensure_ascii=False))
        self.assertNotIn("不能外传", json.dumps(local, ensure_ascii=False))
        self.assertNotIn("禁止发送", json.dumps(local, ensure_ascii=False))

    def test_actual_state_outweighs_success_sentence(self):
        for status in ("requires_approval", "requires_human", "incomplete", "failed", "cancelled", "timed_out"):
            view = task_view(task(status, text="I successfully completed every task"))
            self.assertNotEqual(view["task_execution"], "completed")
            if status in {"requires_approval", "requires_human"}:
                self.assertIsNone(result_memory(view))
        self.assertNotEqual(task_view(task("completed", quiet=False))["task_execution"], "completed")
        record = result_memory(task_view(task()))
        self.assertEqual(record["source_reference"], "localpilot:task:resp_test")
        self.assertEqual(record["epistemic"], "reported")
        self.assertEqual(record["metadata"]["verification_status"], "not_run")

    def test_identifiers_and_cursors_cannot_inject_route(self):
        for value in ("../sessions", "resp/id", "resp?x=1", "", None):
            with self.assertRaises(ValueError):
                self.provider.status(value)
        for value in (-1, True, "2"):
            with self.assertRaises(ValueError):
                list(self.provider.stream("resp_test", value))

    def test_sse_cursor_reconnect_and_incomplete_frames(self):
        event = {"task_id": "resp_test", "sequence": 3, "type": "task.status", "data": task()}
        wire = ("id: 3\nevent: task.status\ndata: " + json.dumps(event) + "\n\n").encode()
        self.provider.opener = Mock()
        self.provider.opener.open.return_value = Response(wire, "text/event-stream")
        result = list(self.provider.stream("resp_test", after=2))
        self.assertEqual(result[0]["last_event_id"], 3)
        self.assertEqual(result[0]["task_status"]["task_execution"], "completed")
        req = self.provider.opener.open.call_args.args[0]
        self.assertEqual(req.headers["Last-event-id"], "2")
        self.provider.opener.open.return_value = Response(wire[:-1], "text/event-stream")
        result = list(self.provider.stream("resp_test", after=2))
        self.assertEqual(result[-1]["error"]["code"], "truncated_stream_frame")
        self.assertEqual(result[-1]["task_execution"], "unknown")

    def test_stream_total_event_and_byte_budgets_detach_only(self):
        wire = b": heartbeat\n\n" * 10
        self.provider.opener = Mock()
        self.provider.opener.open.return_value = Response(wire, "text/event-stream")
        result = list(self.provider.stream("resp_test", max_events=2))
        self.assertEqual(result[-1]["status"], "stream_budget_reached")
        self.assertFalse(result[-1]["task_cancelled"])
        self.assertEqual(result[-1]["last_event_id"], 0)
        self.provider.opener.open.return_value = Response(wire, "text/event-stream")
        result = list(self.provider.stream("resp_test", max_bytes=10))
        self.assertEqual(result[-1]["status"], "stream_budget_reached")
        for value in (0, 16, float("inf")):
            with self.assertRaises(ValueError):
                list(self.provider.stream("resp_test", max_seconds=value))

    def test_stream_status_snapshot_must_belong_to_requested_task(self):
        other=task(); other["id"]="resp_other"
        event={"task_id":"resp_test","sequence":1,"type":"task.status","data":other}
        wire=("id: 1\nevent: task.status\ndata: "+json.dumps(event)+"\n\n").encode()
        self.provider.opener=Mock()
        self.provider.opener.open.return_value=Response(wire,"text/event-stream")
        frames=list(self.provider.stream("resp_test"))
        self.assertEqual(frames[-1]["error"]["code"],"invalid_stream_event")
        self.assertNotIn("task_status",frames[-1])
        self.assertEqual(frames[-1]["last_event_id"],0)

    def test_recovery_inspects_without_automatic_replay(self):
        recovered = task("requires_human")
        recovered["recovery"] = {"class": "UNKNOWN_BLOCKED", "automatic_tool_replay": False}
        self.provider.opener = Mock()
        self.provider.opener.open.return_value = Response(recovered)
        result = self.provider.recover("resp_test")
        self.assertFalse(result["automatic_resume"])
        self.assertEqual(result["recovery"]["class"], "UNKNOWN_BLOCKED")
        self.assertEqual(self.provider.opener.open.call_args.args[0].method, "GET")

    def test_mock_results_remain_mock_and_idempotent(self):
        provider = MockLocalPilotProvider(["requires_approval", "completed"])
        waiting = provider.submit(request(), approved=True, submission_id="once")
        repeated = provider.submit(request(), approved=True, submission_id="once")
        self.assertEqual(waiting["task_id"], repeated["task_id"])
        self.assertNotEqual(waiting["task_execution"], "completed")
        self.assertEqual(provider.approve(waiting["task_id"])["status"], "host_control_required")
        cancelled = provider.cancel(waiting["task_id"], approved=True)
        self.assertEqual(cancelled["status"], "cancelled")
        done = provider.submit(request(), approved=True)
        self.assertEqual(result_memory(done)["metadata"]["evidence_level"], "MOCK_ONLY")


REAL_API_SCRIPT = r'''
import json, os, sys, tempfile, threading, time
from pathlib import Path
from types import SimpleNamespace
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
sys.path.insert(1, sys.argv[2])
from agent.backends import BackendCapabilities, BackendChunk, BackendResponse, Message, ModelInfo, ToolCall
from agent.registry import create_default_registry
from agent.policy import DataPolicy
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_api.server import APIServer
from localpilot_api.service import TaskService
from companion.escalation.localpilot import LocalPilotProvider, result_memory
from companion.escalation.provider import EscalationRequest

class Backend:
    is_local = True
    capabilities = BackendCapabilities(supports_tool_calling=True, supports_streaming=True)
    model_info = ModelInfo('companion-scripted', 'scripted', 131072)
    def __init__(self, mode='normal'):
        self.mode, self.requests = mode, []
        self.release, self.started = threading.Event(), threading.Event()
    def health_check(self):
        return True
    def stream(self, messages, **kwargs):
        self.requests.append([m.to_dict() for m in messages])
        self.started.set()
        if self.mode == 'blocked':
            self.release.wait(2)
        if self.mode == 'write':
            call = ToolCall('write_test', 'apply_patch', json.dumps({'changes':[{'path':'blocked.txt','operation':'create','content':'not allowed'}]}))
            answer = BackendResponse(Message('assistant', 'I completed it', [call]), None, 'scripted', 'tool_calls')
        elif self.mode == 'length':
            answer = BackendResponse(Message('assistant', 'I completed it'), None, 'scripted', 'length')
        else:
            yield BackendChunk('text', 'hello ')
            yield BackendChunk('text', 'source')
            answer = BackendResponse(Message('assistant', 'hello source'), {'prompt_tokens':9,'completion_tokens':2}, 'scripted', 'stop')
        yield BackendChunk('response', response=answer)
    def request(self, messages, **kwargs):
        return list(self.stream(messages, **kwargs))[-1].response

with tempfile.TemporaryDirectory(prefix='companion-v04-real-api-') as tmp:
    root = Path(tmp); workspace = root/'workspace'; workspace.mkdir()
    mode, backends = ['normal'], []
    def factory(callback):
        backend = Backend(mode[0]); backends.append(backend)
        return AgentSession(create_default_registry(workspace, permission_mode='approve-mutations', data_policy=DataPolicy(local_only=True)), backend=backend,
            policy='local-only', data_policy=DataPolicy(local_only=True), event_callback=callback, budgets=SessionBudgets(max_steps=8), retry_policy=RetryPolicy(max_attempts=1))
    def start(service):
        server = APIServer(('127.0.0.1', 0), service, api_key='test-key', control_token='unused-host-key')
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':0.02}, daemon=True); thread.start()
        cfg = SimpleNamespace(localpilot_endpoint='http://127.0.0.1:'+str(server.server_port), localpilot_route='localpilot',
            localpilot_api_key_env='COMPANION_REAL_TEST_KEY', localpilot_timeout_seconds=3, localpilot_task_timeout_seconds=3,
            localpilot_host_local_only=True)
        return server, thread, LocalPilotProvider(cfg)
    def stop(service, server, thread, suspended=False):
        if not suspended: service.shutdown(timeout=5)
        server.shutdown(); server.server_close(); thread.join(2)
    os.environ['COMPANION_REAL_TEST_KEY'] = 'test-key'
    request = EscalationRequest('Explain my approved source', 'manual', 'complex',
        [{'id':'source1','text':'source fact','epistemic':'factual','provenance':{'version_id':'version1','file_hash':'abc'}}], [], [], {'local_only':True}, 'prepared')
    report = {'evidence_level':'TESTED', 'transport':'real ephemeral loopback HTTP/SSE', 'model_execution':'MOCK_ONLY', 'computer_control':'NOT_RUN', 'checks':[]}
    def check(name, condition):
        assert condition, name
        report['checks'].append(name)
    service = TaskService({'localpilot':factory})
    server, thread, provider = start(service)
    try:
        check('configured-route-discovery', provider.health()['status']=='available')
        sid = provider.create_session()['session_id']
        check('session-create-restore', provider.restore_session(sid)['status']=='ready')
        submitted = provider.submit(request, approved=True, session_id=sid, submission_id='reviewed-real-one')
        tid = submitted['task_id']; service.wait(tid)
        view = provider.status(tid)
        check('real-task-completion-state', view['status']=='completed' and view['task_execution']=='completed')
        check('provenance-reaches-runtime', 'version1' in json.dumps(backends[0].requests))
        check('result-memory-keeps-task-source', result_memory(view)['source_reference']=='localpilot:task:'+tid)
        frames = list(provider.stream(tid))
        deltas = [f['data']['data']['data']['text'] for f in frames if f.get('data',{}).get('type')=='runtime.event' and f['data']['data']['type']=='TextDelta']
        check('native-sse-text-deltas', ''.join(deltas)=='hello source')
        cursor = frames[-2]['last_event_id']
        resumed = list(provider.stream(tid, cursor))
        check('sse-cursor-reconnect', len(resumed)==1 and resumed[0]['last_event_id']==frames[-1]['last_event_id'])
        repeated = provider.submit(request, approved=True, session_id=sid, submission_id='reviewed-real-one')
        check('explicit-idempotent-retrieval', repeated['task_id']==tid and len(backends)==1)
        changed = EscalationRequest('Different task', 'manual','complex',[],[],[],{'local_only':True},'prepared')
        conflict = provider.submit(changed, approved=True, session_id=sid, submission_id='reviewed-real-one')
        check('idempotency-conflict-no-new-task', conflict['error']['code']=='idempotency_conflict' and len(service.tasks)==1)
        mode[0]='write'
        waiting = provider.submit(request, approved=True, submission_id='reviewed-real-write')
        service.wait(waiting['task_id']); waiting = provider.status(waiting['task_id'])
        check('gateway-approval-preserved', waiting['status']=='requires_approval' and not (workspace/'blocked.txt').exists())
        refused = provider.approve(waiting['task_id'], approved=True)
        check('companion-cannot-tool-approve', refused['status']=='host_control_required' and not (workspace/'blocked.txt').exists())
        provider.cancel(waiting['task_id'], approved=True); service.wait(waiting['task_id'])
        check('approval-cancel-no-write', provider.status(waiting['task_id'])['status']=='cancelled' and not (workspace/'blocked.txt').exists())
        mode[0]='length'
        unfinished = provider.submit(request, approved=True, submission_id='reviewed-real-length')
        service.wait(unfinished['task_id']); unfinished = provider.status(unfinished['task_id'])
        check('final-text-cannot-fake-completion', unfinished['status']=='failed' and unfinished['task_execution']!='completed')
        mode[0]='blocked'
        active = provider.submit(request, approved=True, submission_id='reviewed-real-cancel')
        backends[-1].started.wait(1)
        cancellation = provider.cancel(active['task_id'], approved=True)
        check('cancel-is-request-not-completion', cancellation['status']=='cancelling' and not cancellation['quiescent'])
        backends[-1].release.set(); service.wait(active['task_id'])
        check('cancel-terminal-session-retired', provider.status(active['task_id'])['status']=='cancelled' and provider.restore_session(active['session_id'])['status']=='closed')
        provider.task_timeout = 0.05
        timeout = provider.submit(request, approved=True, submission_id='reviewed-real-timeout')
        time.sleep(0.08); backends[-1].release.set(); service.wait(timeout['task_id'])
        check('real-runtime-deadline', provider.status(timeout['task_id'])['status']=='timed_out')
    finally:
        for backend in backends: backend.release.set()
        stop(service,server,thread)
    # Planned restart preserves yielded approval; adapter recovery only inspects.
    mode[0]='write'; persistent = TaskService({'localpilot':factory}, persistence=root/'runtime.db')
    server,thread,provider=start(persistent)
    waiting=provider.submit(request,approved=True,submission_id='persistent-reviewed')
    persistent.wait(waiting['task_id']); persistent.suspend(); stop(persistent,server,thread,suspended=True)
    recovered=TaskService({'localpilot':factory},persistence=root/'runtime.db')
    server,thread,provider=start(recovered)
    try:
        view=provider.recover(waiting['task_id'])
        check('persistent-approval-recovery-no-replay', view['status']=='requires_approval' and not view['automatic_resume'] and not (workspace/'blocked.txt').exists())
        check('persistent-idempotency-retrieval',provider.submit(request,approved=True,submission_id='persistent-reviewed')['task_id']==waiting['task_id'])
    finally:
        stop(recovered,server,thread)
    report['passed']=len(report['checks'])
    print(json.dumps(report))
'''


class RealRuntimeAdapterTests(unittest.TestCase):
    def test_isolated_actual_localpilot_api(self):
        # A separate process avoids loading this worktree's older inherited agent
        # package. -B preserves the independently developed LocalPilot sources.
        worktree = Path(__file__).resolve().parents[2]
        runtime = Path(os.environ.get("LOCALPILOT_SOURCE", str(worktree if (worktree/'localpilot_service').is_dir() else worktree.parent / "LocalPilot")))
        if not (runtime / "localpilot_api/server.py").is_file():
            self.skipTest("Current LocalPilot Runtime checkout is unavailable")
        completed = subprocess.run([sys.executable, "-B", "-c", REAL_API_SCRIPT, str(runtime), str(worktree)],
                                   capture_output=True, text=True, timeout=45,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        report = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(report["model_execution"], "MOCK_ONLY")
        self.assertEqual(report["passed"], 18)
        self.assertIn("persistent-approval-recovery-no-replay", report["checks"])


if __name__ == "__main__":
    unittest.main()
