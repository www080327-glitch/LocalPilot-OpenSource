"""Remaining reliability faults: scripted models/AX, real files, threads and flock."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent import file_locks
from agent.patches import apply_patch
from agent.registry import create_default_registry
from agent.safety import PermissionGateway
from agent.session import AgentSession, SessionBudgets, SessionState
from agent.retry import RetryPolicy
from computer.runtime import ComputerRuntime
from computer.local_native import LocalNativeBackend
from localpilot_api.service import TaskService, TaskRequest, SETTLED, APIError
from tests.test_runtime_api import Backend, answer, call
from tests.test_computer_runtime import APP, MemoryAX
from tests.test_local_native_backend import NativeTransport, target


def update(name, digest):
    return {"operation": "update", "path": "shared.txt", "old_text": name + "=0",
            "new_text": name + "=1", "expected_sha256": digest}


def process_patch(root, name, digest, barrier, output):
    gateway = PermissionGateway(root, mode="full-permission")
    decide = gateway.decide
    def gated(*args, **kwargs):
        result = decide(*args, **kwargs)
        barrier.wait(5)
        return result
    gateway.decide = gated
    output.put(apply_patch(root, [update(name, digest)], gateway=gateway))


def crash_native_owner(root):
    with patch("computer.local_native.BUILD", Path(root) / "build"):
        transport = NativeTransport(); original = transport.request
        def request(**args):
            if args["op"] == "native_text": os._exit(23)  # OS drops flock without Python cleanup.
            return original(**args)
        transport.request = request
        backend = LocalNativeBackend([APP], enabled=True, targets=[target()], transport=transport)
        backend.inspect_tree(APP)
        backend.action(APP, "input", "type_text", text="A")


class ReliabilityCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.services = []

    def tearDown(self):
        for service in self.services:
            service.shutdown()
        self.tmp.cleanup()

    def service(self, backend, computer=None, **kwargs):
        sessions = []
        def factory(callback):
            session = AgentSession(create_default_registry(self.root, permission_mode="approve-mutations"),
                backend=backend, policy="cloud-only", computer_runtime=computer, event_callback=callback,
                budgets=SessionBudgets(max_steps=12), retry_policy=RetryPolicy(max_attempts=1), **kwargs)
            sessions.append(session)
            return session
        service = TaskService({"localpilot": factory})
        self.services.append(service)
        return service, sessions

    def settle(self, service, id):
        with service.condition:
            ok = service.condition.wait_for(lambda: service.tasks[id].status in SETTLED and not service.tasks[id].executing and not service.tasks[id].control_pending, 8)
        self.assertTrue(ok, service.task_snapshot(id))
        return service.task_snapshot(id)

    def act(self, service, task, action="approve"):
        service.act(task["id"], action, task["required_action"]["id"])
        return self.settle(service, task["id"])


class A03Tests(ReliabilityCase):
    def initial(self):
        path = self.root / "shared.txt"
        path.write_text("a=0\nb=0\n")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_two_approved_sessions_conflict_then_require_new_read_and_approval(self):
        path, digest = self.initial()
        services, tasks, sessions = [], [], []
        for name in ("a", "b"):
            service, owners = self.service(Backend(answer(None, call("apply_patch", {"changes": [update(name, digest)]}, name)), answer("done")))
            services.append(service); sessions.extend(owners)
            tasks.append(self.settle(service, service.create_task(TaskRequest("update " + name))["id"]))
        barrier = threading.Barrier(2)
        contexts = []
        for session in sessions:
            decide = session.registry.gateway.decide
            def gated(*args, _decide=decide, **kwargs):
                result = _decide(*args, **kwargs)
                if result["status"] == "allowed":
                    barrier.wait(5)  # Both preflights and host approvals are genuine.
                return result
            contexts.append(patch.object(session.registry.gateway, "decide", side_effect=gated))
        from contextlib import ExitStack
        with ExitStack() as stack:
            for context in contexts: stack.enter_context(context)
            for service, task in zip(services, tasks):
                service.act(task["id"], "approve", task["required_action"]["id"])
            results = [self.settle(s, t["id"]) for s, t in zip(services, tasks)]
        receipts = [r["tools"][0]["payload"] for r in results]
        self.assertEqual(sum(r["ok"] for r in receipts), 1)
        conflict = next(r for r in receipts if not r["ok"])
        self.assertEqual(conflict["result"]["applied"], [])
        self.assertIn("re-read", conflict["result"]["error"]["message"])
        self.assertIn(path.read_text(), ("a=1\nb=0\n", "a=0\nb=1\n"))
        # A fresh proposal is a separate approval, never an automatic old-patch retry.
        losing = "b" if "a=1" in path.read_text() else "a"
        changes = [update(losing, hashlib.sha256(path.read_bytes()).hexdigest())]
        registry = create_default_registry(self.root, permission_mode="approve-mutations")
        self.assertEqual(registry.call("apply_patch", {"changes": changes})["status"], "approval_required")
        self.assertEqual(registry.call("apply_patch", {"changes": changes}, approved=True)["status"], "ok")
        self.assertEqual(path.read_text(), "a=1\nb=1\n")

    def test_cross_process_writers_cannot_both_commit_same_version(self):
        path, digest = self.initial()
        ctx = multiprocessing.get_context("spawn")
        barrier, output = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=process_patch, args=(str(self.root), name, digest, barrier, output)) for name in ("a", "b")]
        try:
            for process in processes: process.start()
            results = [output.get(timeout=8) for _ in processes]
            for process in processes:
                process.join(8); self.assertEqual(process.exitcode, 0)
            self.assertEqual(sorted(r["status"] for r in results), ["error", "ok"])
            self.assertIn(path.read_text(), ("a=1\nb=0\n", "a=0\nb=1\n"))
        finally:
            for process in processes:
                if process.is_alive(): process.terminate(); process.join(3)
            output.close()

    def test_batch_conflict_does_not_write_earlier_files(self):
        path, digest = self.initial()
        other = self.root / "first.txt"; other.write_text("before")
        gateway = PermissionGateway(self.root, mode="full-permission")
        decide = gateway.decide
        def change_after_preflight(*args, **kwargs):
            result = decide(*args, **kwargs)
            path.write_text("external")
            return result
        with patch.object(gateway, "decide", side_effect=change_after_preflight):
            result = apply_patch(self.root, [{"operation": "update", "path": "first.txt", "old_text": "before", "new_text": "after"}, update("a", digest)], gateway=gateway)
        self.assertEqual(result["applied"], [])
        self.assertEqual(other.read_text(), "before")
        self.assertEqual(path.read_text(), "external")

    def test_write_failure_releases_locks_and_retains_partial_receipts(self):
        path, digest = self.initial()
        with patch("agent.patches.os.replace", side_effect=OSError("injected replace fault")):
            result = apply_patch(self.root, [{"operation": "create", "path": "created.txt", "content": "saved"}, update("a", digest)], gateway=PermissionGateway(self.root, mode="full-permission"))
        self.assertEqual(result["status"], "error")
        self.assertEqual([r["path"] for r in result["applied"]], ["created.txt"])
        self.assertEqual(path.read_text(), "a=0\nb=0\n")
        self.assertFalse(list(self.root.glob(".localpilot-*")))
        self.assertEqual(apply_patch(self.root, [update("a", digest)], gateway=PermissionGateway(self.root, mode="full-permission"))["status"], "ok")

    def test_lock_failure_is_closed_before_any_write(self):
        path, digest = self.initial()
        with patch("agent.file_locks.fcntl.flock", side_effect=OSError("injected lock fault")):
            result = apply_patch(self.root, [update("a", digest)], gateway=PermissionGateway(self.root, mode="full-permission"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["applied"], [])
        self.assertEqual(path.read_text(), "a=0\nb=0\n")

    def test_reversed_batches_finish_without_deadlock(self):
        for name in ("x", "y"): (self.root / name).write_text("0")
        barrier = threading.Barrier(2); results = []
        def writer(names):
            gateway = PermissionGateway(self.root, mode="full-permission"); decide = gateway.decide
            def gate(*args, **kwargs):
                result = decide(*args, **kwargs); barrier.wait(5); return result
            gateway.decide = gate
            results.append(apply_patch(self.root, [{"operation": "update", "path": n, "old_text": "0", "new_text": "1"} for n in names], gateway=gateway))
        threads = [threading.Thread(target=writer, args=(names,)) for names in (("x", "y"), ("y", "x"))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(7); self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(r["status"] for r in results), ["error", "ok"])
        self.assertTrue(all((self.root / n).read_text() == "1" for n in ("x", "y")))


class A04Tests(ReliabilityCase):
    def delayed_takeover(self, cancel=False, fault=False):
        entered, release, checked, handoff = (threading.Event() for _ in range(4))
        def model(messages):
            entered.set(); self.assertTrue(release.wait(5)); return answer("A finished")
        computer = ComputerRuntime(MemoryAX(), allowed_apps=[APP])
        service, sessions = self.service(Backend(model, answer("A resumed"), answer("B finished")), computer)
        task = service.create_task(TaskRequest("A")); self.assertTrue(entered.wait(3))
        runtime = sessions[0]; original = runtime.take_over_computer; result = []
        def delayed():
            checked.set(); self.assertTrue(handoff.wait(5))
            if fault: raise RuntimeError("injected handoff fault")
            return original()
        thread = threading.Thread(target=lambda: result.append(service.takeover(task["id"])))
        try:
            with patch.object(runtime, "take_over_computer", side_effect=delayed):
                thread.start(); self.assertTrue(checked.wait(3))
                if cancel: service.cancel(task["id"])
                release.set()
                with service.condition:
                    self.assertTrue(service.condition.wait_for(lambda: not service.tasks[task["id"]].executing, 5))
                during = service.task_snapshot(task["id"])
                self.assertFalse(during["quiescent"])
                self.assertEqual(service.session_snapshot(task["session_id"])["active_task_id"], task["id"])
                with self.assertRaises(APIError): service.create_task(TaskRequest("B", session_id=task["session_id"]))
                with self.assertRaises(APIError): service.takeover(task["id"])
                if not cancel:
                    with self.assertRaises(APIError): service.act(task["id"], "resume", during["required_action"]["id"])
                self.assertFalse(service.shutdown(timeout=0)["quiescent"] if cancel else False)
                handoff.set(); thread.join(5); self.assertFalse(thread.is_alive())
        finally:
            release.set(); handoff.set(); thread.join(5)
        return service, task, self.settle(service, task["id"]), computer

    def test_delayed_old_takeover_reserves_generation_until_resume(self):
        service, task, paused, computer = self.delayed_takeover()
        self.assertEqual(paused["status"], "requires_human")
        self.assertEqual(self.act(service, paused, "resume")["status"], "completed")
        second = self.settle(service, service.create_task(TaskRequest("B", session_id=task["session_id"]))["id"])
        self.assertEqual(second["status"], "completed")
        self.assertFalse(computer.paused)
        with self.assertRaises(APIError): service.takeover(task["id"])

    def test_takeover_exception_retains_human_barrier_for_same_task(self):
        service, task, paused, _ = self.delayed_takeover(fault=True)
        self.assertEqual(paused["status"], "requires_human")
        self.assertEqual(paused["required_action"]["reason"]["data"]["message"], "injected handoff fault")
        with self.assertRaises(APIError): service.create_task(TaskRequest("B", session_id=task["session_id"]))

    def test_cancel_and_shutdown_wait_for_control_handoff(self):
        service, task, done, _ = self.delayed_takeover(cancel=True)
        self.assertEqual(done["status"], "cancelled")
        self.assertTrue(service.session_snapshot(task["session_id"])["state"] == "closed")
        self.assertTrue(service.shutdown(timeout=2)["quiescent"])

    def test_generation_mismatch_blocks_takeover_and_resume_before_runtime(self):
        computer = ComputerRuntime(MemoryAX(), allowed_apps=[APP])
        service, sessions = self.service(Backend(answer("plan")), computer, plan_mode=True)
        task = self.settle(service, service.create_task(TaskRequest("A"))["id"])
        task = service.takeover(task["id"])
        with service.condition: service.sessions[task["session_id"]].task_generation += 1
        with patch.object(sessions[0], "take_over_computer") as take, patch.object(sessions[0], "resume_computer") as resume:
            with self.assertRaises(APIError): service.takeover(task["id"])
            with self.assertRaises(APIError): service.act(task["id"], "resume", task["required_action"]["id"])
            take.assert_not_called(); resume.assert_not_called()

    def test_repeated_takeover_invalidates_prior_action_id(self):
        computer = ComputerRuntime(MemoryAX(), allowed_apps=[APP])
        service, _ = self.service(Backend(answer("plan")), computer, plan_mode=True)
        task = self.settle(service, service.create_task(TaskRequest("A"))["id"])
        first = service.takeover(task["id"]); second = service.takeover(task["id"])
        self.assertNotEqual(first["required_action"]["id"], second["required_action"]["id"])
        with self.assertRaises(APIError): service.act(task["id"], "resume", first["required_action"]["id"])


class A05Tests(ReliabilityCase):
    def paused_plan(self):
        entered, release = threading.Event(), threading.Event()
        text = "Plan: inspect first, then propose an approved edit."
        def plan(messages):
            entered.set(); self.assertTrue(release.wait(5)); return answer(text)
        ax = MemoryAX(); computer = ComputerRuntime(ax, allowed_apps=[APP])
        backend = Backend(plan, answer(None, call("apply_patch", {"changes": [{"operation": "create", "path": "plan.txt", "content": "saved"}]}, "edit")), answer("done"))
        service, sessions = self.service(backend, computer, plan_mode=True)
        task = service.create_task(TaskRequest("plan an edit"))
        try:
            self.assertTrue(entered.wait(3)); service.takeover(task["id"]); release.set()
            task = self.settle(service, task["id"])
        finally: release.set()
        session = sessions[0]
        self.assertEqual(task["status"], "requires_human")
        self.assertEqual(session.state, SessionState.COMPUTER_PAUSED)
        self.assertEqual(session._computer_resume_state, SessionState.PLAN_AWAITING_APPROVAL)
        self.assertEqual(session.pending_approval["plan"]["text"], text)
        self.assertTrue(session.registry.gateway.plan_read_only)
        return service, session, task, backend, ax

    def test_plan_arriving_during_takeover_resumes_to_same_approval(self):
        service, session, task, backend, _ = self.paused_plan()
        plan = deepcopy(session.pending_approval)
        turn = session.turn_id
        resumed = self.act(service, task, "resume")
        self.assertEqual(resumed["status"], "requires_approval")
        self.assertEqual(session.state, SessionState.PLAN_AWAITING_APPROVAL)
        self.assertEqual(session.pending_approval, plan)
        self.assertEqual(session.turn_id, turn)
        self.assertEqual(len(backend.requests), 1)
        self.assertFalse((self.root / "plan.txt").exists())
        execution = self.act(service, resumed)
        self.assertEqual(execution["status"], "requires_approval")  # Plan approval is not mutation approval.
        self.assertFalse((self.root / "plan.txt").exists())
        self.assertEqual(self.act(service, execution)["status"], "completed")
        self.assertEqual((self.root / "plan.txt").read_text(), "saved")

    def test_resume_read_failure_keeps_plan_paused_until_success(self):
        service, session, task, backend, ax = self.paused_plan()
        plan = deepcopy(session.pending_approval)
        ax.env["locked"] = True
        blocked = self.act(service, task, "resume")
        self.assertEqual(blocked["status"], "requires_human")
        self.assertEqual(session.state, SessionState.COMPUTER_PAUSED)
        self.assertEqual(session.pending_approval, plan)
        self.assertTrue(session.registry.gateway.plan_read_only)
        ax.env["locked"] = False
        resumed = self.act(service, blocked, "resume")
        self.assertEqual(resumed["status"], "requires_approval")
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(session.pending_approval, plan)

    def test_cancel_plan_during_pause_clears_approval_and_cannot_resume(self):
        service, session, task, backend, _ = self.paused_plan()
        service.cancel(task["id"])
        done = self.settle(service, task["id"])
        self.assertEqual(done["status"], "cancelled")
        self.assertIsNone(session.pending_approval)
        self.assertEqual(session.state, SessionState.SESSION_FINISHED)
        self.assertEqual(session.resume_computer()["error"], "session_closed")
        self.assertEqual(len(backend.requests), 1)
        self.assertFalse((self.root / "plan.txt").exists())

    def test_plan_rejection_after_resume_performs_no_edit(self):
        service, session, task, backend, _ = self.paused_plan()
        resumed = self.act(service, task, "resume")
        rejected = self.act(service, resumed, "reject")
        self.assertEqual(session.active_plan["status"], "rejected")
        self.assertEqual(rejected["status"], "incomplete")
        self.assertEqual(len(backend.requests), 1)
        self.assertFalse((self.root / "plan.txt").exists())

    def test_takeover_at_plan_publication_boundary_keeps_both_states(self):
        computer = ComputerRuntime(MemoryAX(), allowed_apps=[APP])
        service, sessions = self.service(Backend(answer("Plan")), computer, plan_mode=True)
        original = service._runtime_event
        def event(session_id, e):
            original(session_id, e)
            if e.type == "PlanGenerated":
                service.takeover(service.sessions[session_id].active_task)
        with patch.object(service, "_runtime_event", side_effect=event):
            task = self.settle(service, service.create_task(TaskRequest("plan"))["id"])
        self.assertEqual(sessions[0].state, SessionState.COMPUTER_PAUSED)
        self.assertEqual(self.act(service, task, "resume")["status"], "requires_approval")


class A06Tests(ReliabilityCase):
    def setUp(self):
        super().setUp()
        self.backends = []
        self.build_patch = patch("computer.local_native.BUILD", self.root / "build")
        self.build_patch.start()

    def tearDown(self):
        for backend in self.backends: backend.close()
        self.build_patch.stop()
        super().tearDown()

    def native(self, transport=None):
        transport = transport or NativeTransport()
        backend = LocalNativeBackend([APP], enabled=True, targets=[target()], transport=transport)
        self.backends.append(backend)
        return backend, transport

    def unknown_owner(self):
        backend, transport = self.native(); transport.cleanup_unknown = True
        backend.inspect_tree(APP)
        receipt = backend.action(APP, "input", "type_text", text="A")
        self.assertEqual(receipt["input_cleanup"]["status"], "error")
        self.assertEqual(transport.sent, 1)
        return backend, transport, receipt

    def test_unknown_quiesce_and_close_cannot_admit_new_owner(self):
        old, transport, receipt = self.unknown_owner()
        second, other = self.native()
        second.inspect_tree(APP)
        self.assertEqual(second.qualify_action("type_text", APP, {"handle": "input"})["reason"], "pid_lease_conflict")
        self.assertEqual(old.quiesce()["cleanup"], "UNKNOWN")
        for closing in (False, True):
            if closing: old.close()
            second.inspect_tree(APP)
            qualification = second.qualify_action("type_text", APP, {"handle": "input"})
            self.assertEqual(qualification["reason"], "input_cleanup_unknown")
            self.assertEqual(qualification["qualification"]["recovery"]["request_id"], receipt["request_id"])
            self.assertFalse(second.action(APP, "input", "type_text", text="B")["action_sent"])
        self.assertEqual(other.sent, 0)
        self.assertEqual(transport.sent, 1)

    def test_new_process_generation_cannot_retire_uncertain_input(self):
        old, _, _ = self.unknown_owner(); old.close()
        new, transport = self.native()
        new.inspect_tree(APP)
        self.assertEqual(new.qualify_action("type_text", APP, {"handle": "input"})["reason"], "input_cleanup_unknown")
        transport.birth = "2.3"
        transport.context_error = True
        new.inspect_tree(APP)
        self.assertNotEqual(new.qualify_action("type_text", APP, {"handle": "input"})["status"], "ok")
        transport.context_error = False
        new.inspect_tree(APP)
        self.assertEqual(new.qualify_action("type_text", APP, {"handle": "input"})["reason"], "input_cleanup_unknown")
        transport.pid += 1
        new.inspect_tree(APP)
        self.assertEqual(new.qualify_action("type_text", APP, {"handle": "input"})["reason"], "input_cleanup_unknown")
        self.assertFalse(new.action(APP, "input", "type_text", text="B")["action_sent"])
        self.assertEqual(transport.sent, 0)
        self.assertEqual(transport.nodes[0]["value"], "old")

    def test_process_death_preserves_quarantine_after_os_releases_flock(self):
        process = multiprocessing.get_context("spawn").Process(target=crash_native_owner, args=(str(self.root),))
        process.start(); process.join(8)
        if process.is_alive(): process.terminate(); process.join(3)
        self.assertEqual(process.exitcode, 23)
        backend, transport = self.native(); backend.inspect_tree(APP)
        self.assertEqual(backend.qualify_action("type_text", APP, {"handle": "input"})["reason"], "input_cleanup_unknown")
        self.assertFalse(backend.action(APP, "input", "type_text", text="B")["action_sent"])
        self.assertEqual(transport.sent, 0)

    def test_corrupt_recovery_state_blocks_even_a_new_generation(self):
        old, _, _ = self.unknown_owner(); old.close()
        path = self.root / "native-leases" / "1234567.lock.state"
        for raw in ("", "{", '{"version":1,"status":"clean"}', "x" * 8193):
            with self.subTest(raw=raw[:40]):
                path.write_text(raw)
                backend, transport = self.native(); transport.birth = "new"
                backend.inspect_tree(APP)
                self.assertEqual(backend.qualify_action("type_text", APP, {"handle": "input"})["reason"], "native_lease_state_unknown")
                self.assertEqual(transport.sent, 0)
                backend.close()

    def test_failed_intent_persistence_sends_no_input(self):
        backend, transport = self.native(); backend.inspect_tree(APP)
        with patch("computer.local_native.os.fsync", side_effect=OSError("injected intent fsync failure")):
            result = backend.action(APP, "input", "type_text", text="A")
        self.assertFalse(result["action_sent"])
        self.assertEqual(result["reason"], "native_lease_persistence_unknown")
        self.assertEqual(transport.sent, 0)
        self.assertFalse(list((self.root / "native-leases").glob(".native-state-*")))

    def test_failed_clean_marker_preserves_known_action_and_quarantines_successor(self):
        backend, transport = self.native(); backend.inspect_tree(APP)
        original = backend._persist_lease
        def persist(stream, identity, status, **facts):
            if status == "clean": raise OSError("injected clean persistence failure")
            return original(stream, identity, status, **facts)
        with patch.object(backend, "_persist_lease", side_effect=persist):
            result = backend.action(APP, "input", "type_text", text="A")
        self.assertTrue(result["action_sent"])
        self.assertEqual(result["input_cleanup"]["status"], "error")
        self.assertEqual(transport.sent, 1)
        backend.close()
        second, other = self.native(); second.inspect_tree(APP)
        self.assertEqual(second.qualify_action("type_text", APP, {"handle": "input"})["reason"], "input_cleanup_unknown")
        self.assertEqual(other.sent, 0)

    def test_clean_atomic_replace_failure_leaves_uncertain_marker(self):
        backend, transport = self.native(); backend.inspect_tree(APP)
        original = os.replace; count = 0
        def replace(src, dst):
            nonlocal count
            count += 1
            if count == 2: raise OSError("injected clean rename failure")
            return original(src, dst)
        with patch("computer.local_native.os.replace", side_effect=replace):
            result = backend.action(APP, "input", "type_text", text="A")
        self.assertTrue(result["action_sent"])
        self.assertEqual(result["input_cleanup"]["cleanup"], "UNKNOWN")
        backend.close()
        second, _ = self.native(); second.inspect_tree(APP)
        self.assertEqual(second.qualify_action("type_text", APP, {"handle": "input"})["reason"], "input_cleanup_unknown")

    def test_clean_handoff_still_admits_owner_without_replay(self):
        backend, transport = self.native(); backend.inspect_tree(APP)
        self.assertEqual(backend.action(APP, "input", "type_text", text="A")["status"], "ok")
        backend.quiesce()
        second, other = self.native(); second.inspect_tree(APP)
        self.assertEqual(second.qualify_action("type_text", APP, {"handle": "input"})["status"], "ok")
        self.assertEqual(other.sent, 0)
        self.assertEqual(transport.sent, 1)

    def test_cleanup_status_ok_without_empty_owned_inputs_cannot_clear_barrier(self):
        for index, cleanup in enumerate(({"status": "ok", "cleanup": "UNKNOWN"},
                                        {"status": "ok", "cleanup": "owned_key_up_POSTED", "keys": [0]})):
            with self.subTest(cleanup=cleanup), patch("computer.local_native.BUILD", self.root / str(index) / "build"):
                backend, transport = self.native(); transport.pid += index
                original = transport.request
                def request(**args):
                    result = original(**args)
                    return {**result, "input_cleanup": cleanup} if args["op"] == "native_text" else result
                transport.request = request
                backend.inspect_tree(APP)
                result = backend.action(APP, "input", "type_text", text="A")
                self.assertTrue(result["action_sent"])
                self.assertEqual(result["input_cleanup"]["reason"], "invalid_cleanup_proof")
                backend.close()
                second, other = self.native(); other.pid = transport.pid; second.inspect_tree(APP)
                self.assertEqual(second.qualify_action("type_text", APP, {"handle": "input"})["reason"], "input_cleanup_unknown")
                self.assertEqual(other.sent, 0)
                second.close()
