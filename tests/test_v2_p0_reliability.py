"""P0 causal verification and parent/child accounting: scripted models/AX, real files/API."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets, SessionState
from computer.runtime import ComputerRuntime
from localpilot_api.service import TaskService, TaskRequest, SETTLED
from tests.test_runtime_api import Backend, answer, call
from tests.test_computer_runtime import APP, MemoryAX, condition


def write(messages, value="new", id="write"):
    tree = json.loads(next(m.content for m in reversed(messages) if m.role == "tool"))["result"]
    return answer(None, call("set_value", {"app": APP, "element": "input", "observation": tree["observation"],
        "value": value, "postcondition": condition(value=value)}, id))


def create(name):
    return answer(None, call("apply_patch", {"changes": [{"operation": "create", "path": name, "content": "saved"}]}, name))


class P0ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions = []
        self.services = []

    def tearDown(self):
        for service in self.services:
            service.shutdown()
        for session in self.sessions:
            session.close()
        self.tmp.cleanup()

    def session(self, backend, computer=None, mode="full-permission", **kwargs):
        session = AgentSession(create_default_registry(self.root, permission_mode=mode), backend=backend,
            policy="cloud-only", computer_runtime=computer, retry_policy=RetryPolicy(max_attempts=1),
            budgets=SessionBudgets(max_steps=18, max_tool_calls=18, max_token_units=1048576,
                max_worker_steps=8, max_worker_tool_calls=8, max_worker_token_units=262144), **kwargs)
        self.sessions.append(session)
        return session

    def service(self, backend, computer=None, mode="full-permission"):
        service = TaskService({"localpilot": lambda callback: self.session(backend, computer, mode, event_callback=callback)})
        self.services.append(service)
        return service

    def settle(self, service, id):
        with service.condition:
            ok = service.condition.wait_for(lambda: service.tasks[id].status in SETTLED and not service.tasks[id].executing, 5)
        self.assertTrue(ok, service.task_snapshot(id))
        return service.task_snapshot(id)

    def action(self, service, task, action="approve"):
        service.act(task["id"], action, task["required_action"]["id"])
        return self.settle(service, task["id"])

    def restoration(self, reuse=True, repair=False, tamper=None):
        ax = MemoryAX()
        computer = ComputerRuntime(ax, allowed_apps=[APP], verification_timeout=0)
        def noop(messages):
            ax.fault = "noop"
            return answer(None, call("inspect_tree", {"app": APP}, "observe-restore"))
        def verify(messages):
            if repair:
                ax.nodes[0]["value"] = "old"  # Explicit human repair, no agent replay.
            return answer(None, call("verify", {"app": APP, "postcondition": condition(value="old")}, "attest" if reuse else "fresh"))
        backend = Backend(answer(None, call("verify", {"app": APP, "postcondition": condition(value="old")}, "attest")),
            answer(None, call("inspect_tree", {"app": APP}, "observe-new")), lambda m: write(m, "new", "set-new"),
            noop, lambda m: write(m, "old", "restore-old"), verify, answer("Restoration complete"))
        service = self.service(backend, computer)
        paused = self.settle(service, service.create_task(TaskRequest("restore old"))["id"])
        self.assertEqual(paused["status"], "requires_human")
        s = self.sessions[-1]
        original = s._record_call
        def record(tool, payload):
            original(tool, payload)
            if tool.name == "verify" and tool.id == "fresh" and tamper:
                tamper(s.tool_history[-1])
        with patch.object(s, "_record_call", side_effect=record):
            done = self.action(service, paused, "resume")
        self.assertEqual(ax.sent, 2)
        return done, ax, computer

    def test_a01_old_id_cannot_attest_after_failed_restore_and_resume(self):
        done, ax, _ = self.restoration()
        self.assertEqual(ax.nodes[0]["value"], "new")
        self.assertEqual(done["status"], "requires_human")
        verify = [r for r in done["tools"] if r["name"] == "verify"]
        self.assertFalse(verify[-1]["payload"]["ok"])
        self.assertEqual(verify[-1]["payload"]["error"]["type"], "stale_computer_call_id")
        self.assertTrue(self.sessions[-1]._computer_pending_actions()[0])

    def test_a01_fresh_id_still_fails_when_world_is_wrong(self):
        done, _, _ = self.restoration(reuse=False)
        self.assertEqual(done["status"], "requires_human")
        self.assertFalse([r for r in done["tools"] if r["name"] == "verify"][-1]["payload"]["result"]["verified"])
        pending = self.sessions[-1]._computer_pending_actions()[0][0]
        self.assertTrue(pending["prior_action_sent"])
        self.assertEqual(pending["desired_value"], "old")

    def test_a01_fresh_verify_after_human_repair_resolves_without_replay(self):
        done, ax, _ = self.restoration(reuse=False, repair=True)
        self.assertEqual(done["status"], "completed")
        self.assertEqual(ax.nodes[0]["value"], "old")
        self.assertFalse(self.sessions[-1]._computer_pending_actions()[0])

    def test_a01_mutation_same_id_stays_cached(self):
        ax = MemoryAX()
        computer = ComputerRuntime(ax, allowed_apps=[APP], verification_timeout=0)
        mutation = []
        def initial(messages):
            response = write(messages)
            mutation.append(response)
            return response
        backend = Backend(answer(None, call("inspect_tree", {"app": APP}, "read")), initial,
            lambda m: mutation[0], answer("done"))
        s = self.session(backend, computer)
        self.assertEqual(s.run_turn("write").status, "completed")
        self.assertEqual(ax.sent, 1)
        self.assertTrue(s.tool_history[-1]["receipt_reused"])

    def test_a01_read_id_requires_new_observation(self):
        ax = MemoryAX()
        computer = ComputerRuntime(ax, allowed_apps=[APP])
        read = answer(None, call("inspect_tree", {"app": APP}, "read"))
        s = self.session(Backend(read, read, answer("done")), computer)
        s.run_turn("read")
        self.assertEqual(computer.counts["observations"], 1)
        self.assertEqual(s.tool_history[-1]["payload"]["error"]["type"], "stale_computer_call_id")

    def gui_child(self, unknown=False, recovery=False):
        ax = MemoryAX(); ax.fault = "noop"
        computer = ComputerRuntime(ax, allowed_apps=[APP], verification_timeout=0)
        def recover(messages):
            if recovery:
                ax.nodes[0]["value"] = "new"
                return answer(None, call("verify", {"app": APP, "postcondition": condition()}, "parent-verify"))
            return answer("Task completed")
        backend = Backend(answer(None, call("delegate", {"task": "set input", "backend_preference": "cloud", "read_only": False}, "delegate")),
            answer(None, call("inspect_tree", {"app": APP}, "child-read")), write, recover, answer("verified"))
        service = self.service(backend, computer)
        t = self.settle(service, service.create_task(TaskRequest("set input"))["id"])
        if unknown:
            def fault(*args, **kwargs):
                computer.state = __import__("computer.runtime", fromlist=["ControlState"]).ControlState.RESYNC
                computer.pause_requested.set()
                return {"status": "error", "error": "action_outcome_unknown", "action_sent": None,
                    "action_may_have_applied": True, "verified": None, "postcondition": condition(), "app": APP}
            with patch.object(computer, "act", side_effect=fault):
                t = self.action(service, t)
        else:
            t = self.action(service, t)
        self.assertEqual(t["status"], "requires_human")
        self.assertTrue([r for r in t["tools"] if r["name"] == "set_value" and r.get("worker_id")])
        self.assertTrue(self.sessions[-1]._computer_pending_actions()[0])
        done = self.action(service, t, "resume")
        return done, ax

    def test_a02_child_pause_obligation_survives_resume_and_final_text(self):
        done, ax = self.gui_child()
        self.assertEqual(done["status"], "requires_human")
        self.assertEqual(ax.sent, 1)
        self.assertEqual(ax.nodes[0]["value"], "old")

    def test_a02_child_unknown_cannot_complete(self):
        done, _ = self.gui_child(unknown=True)
        self.assertEqual(done["status"], "requires_human")
        r = next(r for r in done["tools"] if r["name"] == "set_value")
        self.assertEqual(r["side_effect_status"], "unknown")

    def test_a02_parent_fresh_verification_resolves_child_intent(self):
        done, ax = self.gui_child(recovery=True)
        self.assertEqual(done["status"], "completed")
        self.assertEqual(ax.sent, 1)
        self.assertFalse(self.sessions[-1]._computer_pending_actions()[0])
        self.assertEqual(done["subagents"][0]["obligation_status"], "resolved")
        self.assertFalse(done["subagents"][0]["unfinished_calls"])

    def waiting_files(self, via_api=True):
        backend = Backend(answer(None, call("delegate", {"task": "create both", "backend_preference": "cloud", "read_only": False}, "delegate")),
            create("first.txt"), create("second.txt"), answer("child done"), answer("parent done"))
        if via_api:
            service = self.service(backend, mode="approve-mutations")
            t = self.settle(service, service.create_task(TaskRequest("create both"))["id"])
            t = self.action(service, t); t = self.action(service, t)
            return service, t, backend
        s = self.session(backend, mode="approve-mutations")
        s.run_turn("create both"); s.approve(); s.approve()
        return s, backend

    def assert_files_accounted(self, s, backend):
        self.assertTrue((self.root / "first.txt").exists())
        self.assertFalse((self.root / "second.txt").exists())
        applied = [r for r in s.tool_history if r["name"] == "apply_patch" and r["payload"].get("ok")]
        self.assertEqual(len(applied), 1)
        self.assertTrue(applied[0].get("worker_id"))
        self.assertEqual(len(s._usage), 3)
        self.assertEqual(len(backend.requests), 3)

    def test_a02_approval_boundary_charges_child_incrementally(self):
        service, t, backend = self.waiting_files()
        s = self.sessions[-1]
        self.assert_files_accounted(s, backend)
        self.assertEqual(len(t["result"]["model_calls"]), 3)
        self.assertEqual(len([r for r in t["tools"] if r["payload"].get("ok") and r["name"] == "apply_patch"]), 1)

    def test_a02_cancel_closes_child_keeps_receipts_usage_and_pending(self):
        service, t, backend = self.waiting_files()
        s = self.sessions[-1]; child = s.pending_approval["child"]
        service.cancel(t["id"]); done = self.settle(service, t["id"])
        self.assertEqual(done["status"], "cancelled")
        self.assert_files_accounted(s, backend)
        self.assertEqual(len(done["result"]["model_calls"]), 3)
        self.assertTrue(done["tools"])
        self.assertEqual(child.state, SessionState.SESSION_FINISHED)
        self.assertIsNone(child.pending_approval)
        self.assertTrue(s.subagents[0]["unfinished_calls"])
        before = (len(s.tool_history), len(s._usage), s._token_units)
        s.close(); s.close()
        self.assertEqual(before, (len(s.tool_history), len(s._usage), s._token_units))

    def test_a02_close_waiting_child_keeps_ledger_exactly_once(self):
        s, backend = self.waiting_files(via_api=False)
        child = s.pending_approval["child"]
        s.close()
        self.assert_files_accounted(s, backend)
        self.assertEqual(child.state, SessionState.SESSION_FINISHED)
        self.assertIsNone(child.pending_approval)
        before = (len(s.tool_history), s._token_units, len(s._usage), s._attempts)
        s.close()
        self.assertEqual(before, (len(s.tool_history), s._token_units, len(s._usage), s._attempts))

    def test_a02_error_finish_closes_child_keeps_applied_receipt(self):
        s, backend = self.waiting_files(via_api=False)
        child = s.pending_approval["child"]
        self.assertEqual(s._finish("host fault", "error").status, "error")
        self.assert_files_accounted(s, backend)
        self.assertEqual(child.state, SessionState.SESSION_FINISHED)
        self.assertIsNone(s.pending_approval)

    def test_a02_child_error_after_side_effect_preserves_receipts_usage(self):
        backend = Backend(answer(None, call("delegate", {"task": "create then error", "backend_preference": "cloud", "read_only": False}, "delegate")),
            create("first.txt"), RuntimeError("injected worker failure"), answer("parent claims completion"))
        service = self.service(backend)
        t = self.settle(service, service.create_task(TaskRequest("work"))["id"])
        done = self.action(service, t)
        self.assertEqual(done["status"], "incomplete")
        self.assertEqual(len([r for r in done["tools"] if r["name"] == "apply_patch" and r["payload"].get("ok")]), 1)
        self.assertEqual(done["result"]["runtime_metrics"]["model_attempts"], 4)
        self.assertEqual(done["result"]["runtime_metrics"]["failed_attempts"], 1)
        self.assertEqual(self.sessions[-1].subagents[0]["status"], "error")

    def test_a02_success_and_rejection_account_once(self):
        for reject in (False, True):
            with self.subTest(reject=reject):
                backend = Backend(answer(None, call("delegate", {"task": "create", "backend_preference": "cloud", "read_only": False}, "delegate")),
                    create("reject.txt" if reject else "success.txt"), answer("child done"), answer("parent done"))
                s = self.session(backend, mode="approve-mutations")
                s.run_turn("work"); s.approve()
                result = s.reject() if reject else s.approve()
                self.assertEqual(result.status, "completed")
                self.assertEqual(len(s._usage), 4)
                self.assertEqual(len(s.tool_history), 2)
                before = (s._token_units, s._attempts, len(s._usage))
                s.close()
                self.assertEqual(before, (s._token_units, s._attempts, len(s._usage)))
                self.assertEqual((self.root / ("reject.txt" if reject else "success.txt")).exists(), not reject)

    def test_a02_handoff_waiting_child_preserves_unfinished_file_work(self):
        s, backend = self.waiting_files(via_api=False)
        child = s.pending_approval["child"]
        s.computer = ComputerRuntime(MemoryAX(), allowed_apps=[APP])
        s.take_over_computer()
        result = s.resume_computer()
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(child.state, SessionState.SESSION_FINISHED)
        self.assertTrue(s.subagents[0]["unfinished_calls"])
        self.assertEqual(len([r for r in s.tool_history if r["name"] == "apply_patch" and r["payload"].get("ok")]), 1)
        self.assertFalse((self.root / "second.txt").exists())

    def test_a01_missing_or_corrupt_provenance_cannot_resolve_real_obligation(self):
        def remove(r):
            r.pop("computer_evidence", None)
        def old_generation(r):
            r["computer_evidence"]["observation_generation"] = 1
        def old_resync(r):
            r["computer_evidence"]["resync_generation"] = 0
        def old_time(r):
            r["computer_evidence"]["observed_at"] = 0
        def unknown_time(r):
            r["computer_evidence"]["observed_at"] = float("nan")
        def wrong_identity(r):
            r["computer_evidence"]["source_call_id"] = "attest"
        def replay(r):
            r["receipt_reused"] = True
        for fault in (remove, old_generation, old_resync, old_time, unknown_time, wrong_identity, replay):
            with self.subTest(fault=fault.__name__):
                done, _, _ = self.restoration(reuse=False, repair=True, tamper=fault)
                self.assertEqual(done["status"], "requires_human")
                self.assertTrue(self.sessions[-1]._computer_pending_actions()[0])

    def test_a01_replayed_successful_mutation_cannot_resolve_later_failure(self):
        ax = MemoryAX(); computer = ComputerRuntime(ax, allowed_apps=[APP], verification_timeout=0)
        saved = []
        def first(messages):
            r = write(messages, "new", "first-write"); saved.append(r); return r
        def observe_noop(messages):
            ax.nodes[0]["value"] = "old"; ax.fault = "noop"
            return answer(None, call("inspect_tree", {"app": APP}, "second-read"))
        backend = Backend(answer(None, call("inspect_tree", {"app": APP}, "first-read")), first,
            observe_noop, lambda m: write(m, "new", "failed-write"), lambda m: saved[0], answer("done"))
        service = self.service(backend, computer)
        t = self.settle(service, service.create_task(TaskRequest("set new"))["id"])
        done = self.action(service, t, "resume")
        self.assertEqual(done["status"], "requires_human")
        self.assertEqual(ax.sent, 2)
        self.assertEqual(ax.nodes[0]["value"], "old")

    def test_a01_new_id_cannot_relabel_old_verify_payload_as_new_observation(self):
        ax = MemoryAX(); computer = ComputerRuntime(ax, allowed_apps=[APP], verification_timeout=0)
        old = computer.verify(APP, condition(value="old"))
        ax.fault = "noop"
        backend = Backend(answer(None, call("inspect_tree", {"app": APP}, "read")), write,
            answer(None, call("verify", {"app": APP, "postcondition": condition()}, "new-id")), answer("done"))
        service = self.service(backend, computer)
        t = self.settle(service, service.create_task(TaskRequest("set new"))["id"])
        with patch.object(computer, "verify", return_value={**old, "verified": True}):
            done = self.action(service, t, "resume")
        self.assertEqual(done["status"], "requires_human")
        self.assertNotIn("computer_evidence", done["tools"][-1])
        self.assertEqual(ax.sent, 1)

    def test_a02_timeout_approval_uses_same_retirement(self):
        service, t, backend = self.waiting_files()
        child = self.sessions[-1].pending_approval["child"]
        service.cancel(t["id"], "timed_out")
        done = self.settle(service, t["id"])
        self.assertEqual(done["status"], "timed_out")
        self.assert_files_accounted(self.sessions[-1], backend)
        self.assertEqual(child.state, SessionState.SESSION_FINISHED)
        self.assertEqual(done["subagents"][0]["status"], "timed_out")
        self.assertIsNone(done["subagents"][0]["approval"])
        self.assertTrue(done["subagents"][0]["unfinished_calls"])

    def test_a02_unexpected_child_approval_error_archives_before_api_failure(self):
        service, t, backend = self.waiting_files()
        s = self.sessions[-1]; child = s.pending_approval["child"]
        with patch.object(child, "approve", side_effect=RuntimeError("approval fault")):
            done = self.action(service, t)
        self.assertEqual(done["status"], "failed")
        self.assert_files_accounted(s, backend)
        self.assertEqual(done["subagents"][0]["status"], "error")
        self.assertEqual(len(done["result"]["model_calls"]), 3)
        self.assertEqual(child.state, SessionState.SESSION_FINISHED)
        self.assertTrue(done["subagents"][0]["unfinished_calls"])

    def test_a02_cancel_during_inflight_child_write_keeps_effect_once(self):
        entered, release = threading.Event(), threading.Event()
        ax = MemoryAX(); computer = ComputerRuntime(ax, allowed_apps=[APP], verification_timeout=0)
        action = ax.action
        def blocked(*args, **kwargs):
            result = action(*args, **kwargs)
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test barrier timeout")
            return result
        ax.action = blocked
        backend = Backend(answer(None, call("delegate", {"task": "set new", "backend_preference": "cloud", "read_only": False}, "delegate")),
            answer(None, call("inspect_tree", {"app": APP}, "read")), write, answer("must not run"))
        service = self.service(backend, computer)
        t = self.settle(service, service.create_task(TaskRequest("set new"))["id"])
        service.act(t["id"], "approve", t["required_action"]["id"])
        try:
            self.assertTrue(entered.wait(3))
            service.cancel(t["id"])
        finally:
            release.set()
        done = self.settle(service, t["id"])
        self.assertEqual(done["status"], "cancelled")
        self.assertEqual(ax.sent, 1)
        self.assertEqual(ax.nodes[0]["value"], "new")
        receipts = [r for r in done["tools"] if r["name"] == "set_value"]
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["side_effect_completed"])
        self.assertEqual(len(done["result"]["model_calls"]), 3)
        self.assertEqual(len(backend.requests), 3)

    def test_a02_child_ids_are_scoped_and_old_task_snapshot_is_immutable(self):
        backend = Backend(answer(None, call("delegate", {"task": "read", "backend_preference": "cloud"}, "same")),
            answer(None, call("read_file", {"path": "note.txt"}, "same")), answer("child"), answer("parent"), answer("next"))
        (self.root / "note.txt").write_text("fact")
        service = self.service(backend)
        t = self.settle(service, service.create_task(TaskRequest("read"))["id"])
        done = self.action(service, t)
        self.assertEqual(done["status"], "completed")
        ids = [r["receipt_id"] for r in done["tools"]]
        self.assertEqual(len(ids), len(set(ids)))
        frozen = deepcopy(done)
        next_task = service.create_task(TaskRequest("next", session_id=done["session_id"]))
        self.settle(service, next_task["id"])
        self.assertEqual(service.task_snapshot(done["id"]), frozen)

    def test_a01_pre_dispatch_observation_cannot_attest_mutation(self):
        ax = MemoryAX(); computer = ComputerRuntime(ax, allowed_apps=[APP], verification_timeout=0)
        backend = Backend(answer(None, call("inspect_tree", {"app": APP}, "read")), write, answer("done"))
        def stale_success(*args, **kwargs):
            current = computer.observations[APP]
            return {"status": "ok", "verified": True, "action_sent": True, "observation": current["token"]}
        service = self.service(backend, computer)
        with patch.object(computer, "act", side_effect=stale_success):
            done = self.settle(service, service.create_task(TaskRequest("set new"))["id"])
        self.assertEqual(done["status"], "requires_human")
        self.assertEqual(ax.nodes[0]["value"], "old")

    def test_a02_child_paused_before_any_action_stays_unfinished(self):
        computer = ComputerRuntime(MemoryAX(), allowed_apps=[APP], verification_timeout=0)
        backend = Backend(answer(None, call("delegate", {"task": "work", "backend_preference": "cloud"}, "delegate")),
            answer("parent says done"))
        service = self.service(backend, computer)
        original = AgentSession.run_turn
        def pause_child(session, task):
            if session.depth:
                computer.take_over()
            return original(session, task)
        t = self.settle(service, service.create_task(TaskRequest("work"))["id"])
        with patch.object(AgentSession, "run_turn", pause_child):
            t = self.action(service, t)
        self.assertEqual(t["status"], "requires_human")
        done = self.action(service, t, "resume")
        self.assertEqual(done["status"], "incomplete")
        self.assertEqual(done["subagents"][0]["obligation_status"], "unresolved")
        self.assertEqual(len(backend.requests), 2)

    def test_a02_http_responses_and_sse_expose_terminal_child_ledger(self):
        from localpilot_api.server import APIServer
        from localpilot_api.client import Client
        service, t, backend = self.waiting_files()
        server = APIServer(("127.0.0.1", 0), service, api_key="test", control_token="host")
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        client = Client(f"http://127.0.0.1:{server.server_port}", api_key="test", control_token="host", timeout=5)
        try:
            client.request(f'/v1/responses/{t["id"]}/cancel', {})
            self.settle(service, t["id"])
            response = client.request(f'/v1/responses/{t["id"]}')
            extension = response["localpilot"]
            self.assertEqual(extension["status"], "cancelled")
            self.assertEqual(response["usage"]["total_tokens"], 30)
            self.assertEqual(extension["subagents"][0]["obligation_status"], "unresolved")
            self.assertTrue(extension["subagents"][0]["unfinished_calls"])
            self.assertEqual(len([r for r in extension["tools"] if r["name"] == "apply_patch" and r["payload"].get("ok")]), 1)
            frames = list(client.stream(f'/localpilot/v1/tasks/{t["id"]}/events'))
            final = [f["data"]["data"] for f in frames if f["data"].get("type") == "task.status"][-1]
            self.assertEqual(final["subagents"], extension["subagents"])
            self.assert_files_accounted(self.sessions[-1], backend)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
