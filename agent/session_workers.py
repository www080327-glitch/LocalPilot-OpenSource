"""Child construction, delegation, accounting and scheduler boundaries."""
from copy import deepcopy
from dataclasses import asdict
import time
from .async_runtime import serialized
from .computer_ledger import action_key, computer_obligations
from .persistence import PersistenceError
from .backends import ToolCall
from .routing import RoutingPolicy
from .runtime_tools import ASYNC_SCHEMAS
from .session_types import SessionBudgets, SessionState


class SessionWorkers:
    def _child_traits(self):
        from dataclasses import replace
        return replace(self.adaptive.traits, independent_children=0, review_required=False)

    def _delegate(self, call, args, approved=False):
        async_mode = args.get("mode", "sync") == "async"
        if args.get("mode", "sync") not in {"sync", "async"} or async_mode and not self.async_policy:
            raise ValueError("Async delegation requires host opt-in")
        if async_mode:
            existing = next((r for r in self.subagents if r.get('async') and r['turn_id'] == self.turn_id and r['call']['id'] == call.id), None)
            if existing:
                if self._signature(ToolCall.from_dict(existing['call'])) != self._signature(call):
                    raise ValueError("Child proposal identity changed")
                return self._payload({'worker_id':existing['id'], 'status':existing['status']})
        target = args["backend_preference"]
        tier = args.get("tier")
        read_only = args.get("read_only", True)
        if not isinstance(read_only, bool) or not isinstance(args["task"], str) or not 1 <= len(args["task"]) <= 16000:
            raise ValueError("Worker requires a bounded task and boolean read_only")
        if async_mode and not read_only:
            from .persistence import recovery_class
            if recovery_class(self) == 'UNKNOWN_BLOCKED':
                return self._payload({'status':'denied','reason':'Uncertain child effects quarantine new mutating delegation.'})
        if self._planning and not read_only:
            return self._payload({"status": "denied", "reason": "Plan Mode permits read-only delegates only."})
        if target not in {"local", "cloud"}:
            raise ValueError("Worker backend must be local or cloud")
        if tier is not None and (target != "cloud" or tier not in {"LIGHT", "STRONG"}):
            raise ValueError("LIGHT/STRONG tier requires a cloud worker")
        if self.depth >= self.budgets.max_subagent_depth or self._subagent_count >= self.budgets.max_subagents_per_turn:
            return self._payload({"status": "denied", "reason": "Subagent depth/count budget exhausted."})
        if (target == "cloud" and (self.routing_policy == RoutingPolicy.LOCAL_ONLY or self.hard_data_policy.local_only)) or (target == "local" and self.routing_policy == RoutingPolicy.CLOUD_ONLY):
            return self._payload({"status": "denied", "reason": "Routing policy forbids this worker."})
        backend = (self.local_backend if target == "local" else
                   self.cloud_worker_backends.get(tier) if tier else self.cloud_backend)
        backend_id = None
        if self.hybrid:
            backend_id, backend = self.hybrid.resolve(target, args.get('backend_id'), args.get('model'), tier)
        if self.adaptive:
            decision = self.adaptive.decide('child', call.id, current=backend_id,
                                           locked=args.get('backend_id') or (backend_id if args.get('model') else None))
            if self.adaptive.enabled() and not decision['selected']:
                return self._payload({'status': 'denied', 'reason': decision['reason']})
            if self.adaptive.enabled() and decision['selected']:
                backend_id = decision['selected']
                backend = self.hybrid.check_target(backend_id)
                target = self.hybrid.kind(backend_id)
                tier = tier if target == 'cloud' else None
                decision['applied'] = True
                self._emit('AdaptiveRouteApplied', scope='child', backend_id=backend_id, call_id=call.id)
        if backend is None or (target == "local" and not backend.health_check()):
            return self._payload({"status": "unavailable", "tier": tier,
                "reason": "Worker backend unavailable; check provider API credentials and model access."})
        worker_efforts = getattr(getattr(backend, "capabilities", None), "supported_thinking_efforts", ())
        child_thinking = self.thinking_mode if self.thinking_mode in worker_efforts else None
        if self.thinking_mode is not None and child_thinking is None:
            self._emit("SubagentThinkingDefaulted", backend=target, model=self._model_name(backend),
                       requested=self.thinking_mode, effective="provider_default")
        if target == "cloud" and not approved and not self._runtime_preapproved(target):
            self.pending_approval = {"kind": "delegate", "call": deepcopy(call), "task": args["task"],
                "tier": tier, "provider": getattr(backend, "provider", "unknown"),
                "configured_model": self._model_name(backend),
                "data_categories": ["delegated_task", "workspace_snippets", "tool_result"],
                "notice": "Cloud worker receives the task and any workspace content permitted by its tools."}
            self.state = SessionState.TOOL_AWAITING_APPROVAL
            self._emit("ApprovalRequired", **self._approval_view())
            return self._payload({"status": "approval_required"})
        if async_mode and self.adaptive and self.adaptive.enabled() and self.async_policy.max_running_per_session > self.adaptive.policy.max_child_concurrency:
            return self._payload({"status": "denied", "reason": "Host scheduler exceeds adaptive concurrency ceiling"})
        if async_mode and (self._subagent_count >= self.async_policy.max_children_per_turn or
                           len(self._scheduler.queue) >= self.async_policy.max_queued_children):
            return self._payload({"status":"denied", "reason":"Child admission/backpressure limit"})
        requested = args.get("budget", {})
        if not isinstance(requested, dict) or set(requested) - {"steps", "tools", "tokens"}:
            raise ValueError("Invalid worker budget")
        for key, value in requested.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < (0 if key == "tools" else 1):
                raise ValueError("Worker budgets must be bounded integers")
        remaining_steps = self.budgets.max_steps - (self._attempts if self.controls.reserve else len(self._usage)) - ((self.finalization_policy.max_attempts if self.finalization_policy else 1) if self.controls.reserve else 0)
        remaining_tools = max(0, self.budgets.max_tool_calls - self._tool_proposals)
        remaining_steps -= self._reserved_child_budget('_attempts')
        remaining_tools = max(0, remaining_tools - self._reserved_child_budget('_tool_proposals'))
        remaining_tokens = self._exploration_limit - self._token_units - self._reserved_child_budget('_token_units')
        if remaining_steps <= 0 or remaining_tokens <= 0:
            return self._payload({"status": "denied", "reason": "Parent budget exhausted."})
        budgets = SessionBudgets(max_steps=min(requested.get("steps", self.budgets.max_worker_steps), remaining_steps, self.budgets.max_worker_steps),
            max_tool_calls=min(requested.get("tools", self.budgets.max_worker_tool_calls), remaining_tools, self.budgets.max_worker_tool_calls),
            max_token_units=min(requested.get("tokens", self.budgets.max_worker_token_units), remaining_tokens, self.budgets.max_worker_token_units),
            max_output_tokens=min(self.budgets.max_output_tokens, self.budgets.max_worker_output_tokens),
            max_primary_switches_per_turn=self.budgets.max_primary_switches_per_turn if self.hybrid else 0, max_subagent_depth=self.budgets.max_subagent_depth,
            max_subagents_per_turn=0)
        self._subagent_count += 1
        worker_id = f"{self.turn_id}.{self._subagent_count}"
        record = {"id": worker_id, "turn_id": self.turn_id, "backend": target, "tier": tier,
                  "provider": getattr(backend, "provider", "unknown"),
                  "configured_model": self._model_name(backend), "status": "running", "task": args["task"],
                  "permission_mode": self.permission_mode, "read_only": read_only,
                  "workspace": str(self.workspace), "depth": self.depth + 1}
        if self.hybrid:
            record['backend_id'] = backend_id
        from .child_sessions import create_child
        child = create_child(self, record, budgets, child_thinking, inherit_tools=True)
        if self.hybrid:
            child.hybrid.state['task'] = deepcopy(self.hybrid.state['task'])
            child.hybrid.state['parent_handoff'] = self.hybrid.contract()
        self.subagents.append(record)
        self._children[worker_id] = child
        self.state = SessionState.WAITING_SUBAGENT
        self._emit("SubagentStarted", id=worker_id, backend=target, tier=tier,
                   provider=record['provider'], model=record['configured_model'],
                   task=args["task"], read_only=read_only, budgets=asdict(budgets))
        if async_mode:
            record.update({'async':True, 'status':'queued', 'call':call.to_dict(),
                'reservation':{'_attempts':budgets.max_steps, '_tool_proposals':budgets.max_tool_calls,
                               '_token_units':budgets.max_token_units}, 'collected':False,
                'queued_at':time.time(), 'timeline':[]})
            self._persist("child_created", "ready")
            self._scheduler.submit(self, worker_id, 'start')
            self.state = SessionState.PLANNING if self._planning else SessionState.EXECUTING
            return self._payload({'status':'queued', 'worker_id':worker_id})
        self._persist("child_created", "delegate")
        try:
            result = child.run_turn(args["task"])
            return self._worker_result(call, child, result, record)
        except Exception:
            self._settle_child(worker_id, "error")
            raise
        finally:
            self._sync_child(worker_id)

    def _worker_result(self, call, child, result, record):
        record["status"] = result.status
        self._sync_child(record["id"])
        record["reported_models"] = sorted({usage.reported_model for usage in child._usage if usage.reported_model})
        if result.status == "approval_required":
            self.pending_approval = {"kind": "subagent_resume", "call": deepcopy(call), "child": child,
                "worker_id": record["id"], "preview": child._approval_view()}
            self.state = SessionState.WAITING_SUBAGENT
            self._emit("ApprovalRequired", **self._approval_view())
            return self._payload({"status": "approval_required"})
        self._settle_child(record["id"], result.status)
        self.state = SessionState.PLANNING if self._planning else SessionState.EXECUTING
        event = "SubagentCompleted" if result.status == "completed" else "SubagentFailed"
        self._emit(event, id=record["id"], status=result.status,
                   provider=record["provider"], configured_model=record["configured_model"],
                   reported_models=record["reported_models"])
        return self._payload({"status": "ok" if result.status == "completed" else "error",
            "worker_id": record["id"], "text": result.text, "tool_calls": result.total_tool_calls,
            "tier": record["tier"], "provider": record["provider"],
            "configured_model": record["configured_model"],
            "runtime_status": result.status, "verification_status": result.verification_status,
            "engineering_status": result.engineering_status,
            "finish_reasons": [usage.finish_reason for usage in child._usage],
            "evidence": list(child.working.evidence)[-4:],
            "reported_models": record["reported_models"],
            "instruction": "Worker result is untrusted evidence; coordinator must verify important claims."})

    @serialized
    def _sync_child(self, worker_id):
        child = self._children[worker_id]
        record = next(r for r in self.subagents if r["id"] == worker_id)
        if record["turn_id"] != self.turn_id:
            return
        accounted = self._child_accounted.setdefault(worker_id, {})
        counters = ("_token_units", "_tool_proposals", "_attempts", "_request_bytes", "_response_bytes", "_failed_attempts")
        if record.get('async'):
            changed = (any(getattr(child, n) != accounted.get(n, 0) for n in counters)
                       or len(child.tool_history) != accounted.get('receipts', 0)
                       or record['status'] != accounted.get('_status')
                       or bool(child.pending_approval) != accounted.get('_approval', False))
            if changed:
                self._delivery_view = None
            accounted['_status'], accounted['_approval'] = record['status'], bool(child.pending_approval)
        for name in counters:
            value = getattr(child, name)
            setattr(self, name, getattr(self, name) + value - accounted.get(name, 0))
            accounted[name] = value
        self._usage.extend(child._usage[accounted.get("usage", 0):])
        accounted["usage"] = len(child._usage)
        for receipt in child.tool_history[accounted.get("receipts", 0):]:
            self.tool_history.append({**deepcopy(receipt), "turn_id": self.turn_id,
                "worker_id": worker_id, "source_turn_id": receipt["turn_id"],
                "receipt_id": f"worker:{worker_id}/{receipt['receipt_id']}"})
        if len(child.tool_history) != accounted.get("receipts", 0):
            self.working.cache.invalidate()
        accounted["receipts"] = len(child.tool_history)
        record["receipts"] = child.tool_history if record.get("async") else deepcopy(child.tool_history)
        record["approval"] = deepcopy(child._approval_view()) if child.pending_approval else None
        record["pending_calls"] = [c.to_dict() for c in child._queue]
        record["usage"] = {name[1:]: accounted[name] for name in counters}
        record["model_calls"] = len(child._usage)
        if child.hybrid:
            record['hybrid_usage'] = child.hybrid.summary()
            record['current_backend_id'] = child.hybrid.state['backend_id']
        if record.get('async'):
            record['judge_calls'] = getattr(child.registry.gateway.judge, 'calls', 0)
            record['judge_provider_usage'] = 'UNKNOWN' if record['judge_calls'] else 'NOT_APPLICABLE'

        from computer.schemas import WRITE_NAMES
        unresolved, handoff = computer_obligations(self.tool_history)
        unfinished = {}
        for receipt in self.tool_history:
            signature = receipt["signature"]
            payload = receipt["payload"]
            rejected = payload.get("error", {}).get("type") == "user_rejected"
            if (payload.get("ok") and not receipt.get("receipt_reused")) or rejected:
                unfinished.pop(signature, None)
                repaired = set(receipt.get('repaired_proposals', []))
                # Child receipt IDs gain the worker prefix when projected into parent.
                for old_signature, old_receipt in list(unfinished.items()):
                    old_id = old_receipt['receipt_id']
                    source_id = old_id.split('/', 1)[1] if old_receipt.get('worker_id') else old_id
                    if old_receipt.get('worker_id') == receipt.get('worker_id') and source_id in repaired:
                        unfinished.pop(old_signature)
            elif receipt.get("worker_id") == worker_id:
                # Capability denial is failed work, not the host withdrawing
                # the obligation. Only explicit user_rejected settles it.
                if receipt["name"] in WRITE_NAMES | {"verify"}:
                    if action_key(receipt) in unresolved or action_key(receipt) in handoff:
                        unfinished[signature] = receipt
                else:
                    unfinished[signature] = receipt
        record["unfinished_calls"] = deepcopy(list(unfinished.values()))
        record["obligation_status"] = ("pending_approval" if record["approval"] else
            "unresolved" if record["unfinished_calls"] or record["pending_calls"] or record["status"] in
                {"error", "max_steps_exceeded", "incomplete", "tool_budget_exceeded"}
                or (record["status"] == "computer_paused" and not any(r["name"] in WRITE_NAMES | {"verify"}
                    for r in record["receipts"])) else "resolved")

    def _sync_children(self):
        for worker_id in self._children:
            self._sync_child(worker_id)

    def _cancel_queued(self, reason):
        while self._queue:
            call = self._queue.popleft()
            uncertain = (self._durable_intent and not self._durable_intent["read_only"]
                and self._durable_intent["turn_id"] == self.turn_id
                and self._durable_intent["signature"] == self._signature(call))
            self._record_call(call, {"ok": False, "error": {"type": "cancelled_unknown_effect" if uncertain else reason,
                "message": "Host cancellation retires control, not an uncertain external effect." if uncertain else
                    "Unexecuted proposal retired; no action sent. The requested work remains unfinished."},
                "result": {"status": "cancelled", "action_sent": None if uncertain else False,
                    **({"action_may_have_applied": True} if uncertain else {}), "replay_allowed": False}})
        self.pending_approval = None

    def _settle_child(self, worker_id, reason):
        child = self._children[worker_id]
        record = next(r for r in self.subagents if r["id"] == worker_id)
        if child.state != SessionState.SESSION_FINISHED:
            if reason == "completed" and (child._queue or child.pending_approval):
                reason = "incomplete"
            self._sync_child(worker_id)
            child.request_cancel(self._stop_reason if self._stop_requested.is_set() else "cancelled")
            child._cancel_queued(reason)
            child.close()
            record["status"] = reason
            if reason == "cancelled_for_handoff":
                record["handoff_receipts"] = deepcopy(child.tool_history)
        self._sync_child(worker_id)

    def _settle_children(self, reason):
        for worker_id, child in self._children.items():
            record = next(r for r in self.subagents if r["id"] == worker_id)
            if record["turn_id"] != self.turn_id:
                continue
            was_open = child.state != SessionState.SESSION_FINISHED
            self._settle_child(worker_id, reason)
            if was_open:
                self._emit("SubagentFailed", id=worker_id, status=reason)

    def _unfinished_workers(self):
        from computer.schemas import WRITE_NAMES
        for record in self.subagents:
            if record.get('async') and record.get('turn_id') == self.turn_id and (
                    record['status'] != 'completed' or not record.get('collected')):
                return True
            if record.get("turn_id") != self.turn_id:
                continue
            unfinished = record.get("unfinished_calls", [])
            # GUI failures can be resolved by a later causal parent verification.
            # Non-GUI incomplete work and failed worker execution remain explicit.
            if any(r["name"] not in WRITE_NAMES | {"verify"} for r in unfinished):
                return True
            if record["status"] in {"error", "max_steps_exceeded", "incomplete", "tool_budget_exceeded"}:
                return True
            if record["status"] == "computer_paused" and not any(r["name"] in WRITE_NAMES | {"verify"}
                    for r in record.get("receipts", [])):
                return True
        return False

    def _continue_worker(self, pending, approve):
        child = pending["child"]
        record = next(r for r in self.subagents if r["id"] == pending["worker_id"])
        try:
            result = child.approve() if approve else child.reject()
            return self._worker_result(pending["call"], child, result, record)
        except Exception:
            self._settle_child(record["id"], "error")
            raise
        finally:
            self._sync_child(record["id"])

    def _reserved_child_budget(self, name):
        return sum(max(0, r['reservation'][name] - self._child_accounted.get(r['id'], {}).get(name, 0))
                   for r in self.subagents if r.get('async') and r['turn_id'] == self.turn_id
                   and r['status'] in {'queued','running','approval_required'})

    @serialized
    def children_snapshot(self):
        self._sync_children()
        return [{'worker_id':r['id'], 'status':r['status'], 'collected':r.get('collected',False),
                 'text':r.get('text',''), 'usage':r.get('usage'), 'obligation_status':r.get('obligation_status'),
                 'approval':r.get('approval'), 'timeline':deepcopy(r.get('timeline',[]))}
                for r in self.subagents if r.get('async') and r['turn_id'] == self.turn_id]

    def _async_action(self, call, args):
        schema = next(s['function']['parameters'] for s in ASYNC_SCHEMAS if s['function']['name'] == call.name)
        if set(args) - set(schema['properties']) or any(k not in args for k in schema['required']):
            raise ValueError('Invalid async action fields')
        if call.name == 'cancel_child':
            self.cancel_child(args['worker_id'])
        elif call.name == 'wait_children':
            self._async_barrier(call=call)
        return self._payload(self.children_snapshot())

    @serialized
    def cancel_child(self, worker_id):
        record = next((r for r in self.subagents if r.get('async') and r['id'] == worker_id and r['turn_id'] == self.turn_id), None)
        if record is None:
            raise ValueError('Child is not owned by the current parent turn')
        child = self._children[worker_id]
        # The durable terminal commit is the completion/cancel linearization
        # point, even before the worker has published its parent status.
        if child._durable_phase == 'terminal':
            return
        if record['status'] in {'queued','running','approval_required'}:
            record['cancel_requested'] = True
            child.request_cancel()
            self._persist('child_cancel_intent')
            if record['status'] == 'approval_required':
                self._scheduler.submit(self, worker_id, 'continue')
            self._state_condition.notify_all()

    def _run_async_child(self, worker_id, operation):
        child = self._children[worker_id]
        record = next(r for r in self.subagents if r['id'] == worker_id)
        try:
            with self._state_condition:
                record['status'] = 'running'
                record['timeline'].append({'event':operation, 'at':time.time()})
                self._persist('child_running')
            if operation == 'start':
                result = child.run_turn(record['task'])
            elif operation == 'approve':
                result = child.approve()
            elif operation == 'reject':
                result = child.reject()
            else:
                result = child.continue_checkpoint() if child.turn_id else child.run_turn(record['task'])
            with self._state_condition:
                record['status'], record['text'] = result.status, result.text
                record['timeline'].append({'event':result.status, 'at':time.time()})
                self._sync_child(worker_id)
                if result.status != 'approval_required':
                    self._settle_child(worker_id, result.status)
                    child.working.cache.invalidate()
                self._persist('child_settled')
                self._emit('SubagentCompleted' if result.status == 'completed' else 'SubagentFailed',
                           id=worker_id, status=result.status, asynchronous=True)
                self._state_condition.notify_all()
        except Exception as error:
            with self._state_condition:
                record['status'], record['text'] = 'error', str(error)
                record['timeline'].append({'event':'error','at':time.time(),'error_type':type(error).__name__})
                self._sync_child(worker_id)
                # A persistence failure fences dispatch globally; preserve intent.
                if not isinstance(error, PersistenceError):
                    self._settle_child(worker_id, 'error')
                    self._persist('child_failed')
                self._state_condition.notify_all()

    def _recover_async_children(self):
        for r in self.subagents:
            if r.get('async') and r['turn_id'] == self.turn_id and r['status'] in {'queued','running','approval_required'}:
                if self._scheduler.owns_worker(self, r['id']):
                    continue  # host approval may arrive while a live sibling is still in flight
                child = self._children[r['id']]
                if child._durable_phase == 'terminal':
                    r['status'] = next((e.data['status'] for e in reversed(child.events.events) if e.type == 'TurnFinished'), 'error')
                    r['text'] = child._turn_text
                    self._settle_child(r['id'], r['status'])
                    continue
                if child.pending_approval:
                    r['status'] = 'approval_required'
                    continue
                self._scheduler.submit(self, r['id'], 'continue')

    def _async_barrier(self, call=None, stopping=False):
        records = [r for r in self.subagents if r.get('async') and r['turn_id'] == self.turn_id]
        if not records:
            return
        if stopping:
            for r in records:
                if r['status'] in {'queued','running','approval_required'}:
                    self.cancel_child(r['id'])
        self.state = SessionState.WAITING_SUBAGENT
        self._persist('children_wait', 'ready')
        while any(r['status'] in {'queued','running'} for r in records):
            self._state_condition.wait(0.05)
            if self._stop_requested.is_set() and not stopping:
                return self._async_barrier(call, stopping=True)
        self._sync_children()
        if not stopping:
            approval = next((r for r in records if r['status'] == 'approval_required'), None)
            if approval:
                child = self._children[approval['id']]
                self.pending_approval = {'kind':'async_child', 'call':deepcopy(call),
                    'worker_id':approval['id'], 'child':child, 'preview':child._approval_view()}
                self._persist('approval_wait', 'ready')
                return
        for r in records:
            r['collected'] = True
        self._persist('children_collected', 'ready')
        self.state = SessionState.PLANNING if self._planning else SessionState.EXECUTING

    def _wait_async_boundary(self):
        """Yield approval only after live siblings have settled their intents.

        An active intent is not a lost receipt. Preserve the selected approval;
        joins/collection still use the existing barrier.
        """
        if not self.async_policy:
            return
        while any(r.get('async') and r['turn_id'] == self.turn_id and r['status'] in {'queued', 'running'} for r in self.subagents):
            self._check_cancel()
            self._state_condition.wait(.05)
        self._sync_children()
