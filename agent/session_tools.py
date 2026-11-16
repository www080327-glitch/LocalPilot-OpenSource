"""Tool dispatch, approval resource identity and durable effect receipts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .async_runtime import serialized, external
from .backends import Message
from .loop import Agent
from .persistence import PersistenceError
from .runtime_tools import RUNTIME_TOOL_NAMES, ASYNC_TOOL_NAMES
from .safety import resolve_workspace_path
from .session_types import SessionState, SessionCancelled
from .stabilization import ReserveReached, excerpt


class SessionToolCalls:
    @serialized
    def _charge_judge(self, units):
        if (self._token_units + units + self._reserved_child_budget('_token_units') > self._exploration_limit or self._finalizing or
                (self.controls.reserve and self._attempts + self._reserved_child_budget('_attempts') >= self.budgets.max_steps - (self.finalization_policy.max_attempts if self.finalization_policy else 1))):
            raise ReserveReached("Safety judge cannot consume final reserve; human approval required.")
        self._token_units += units
        self._attempts += 1
        self._emit("JudgeAttempt", attempt=self._attempts, conservative_units=units)

    def _call_key(self, call):
        return (self.turn_id, call.id)

    @staticmethod
    def _signature(call):
        return hashlib.sha256((call.name + "\0" + call.arguments).encode()).hexdigest()

    def _dispatch(self, call, approved=False, scope_approval=None):
        self._check_cancel()
        self._persist("dispatch_check", "ready")
        if self.computer:
            self._call_context[self._call_key(call)] = {"dispatch_generation": self.computer.revision,
                "resync_generation": self.computer.resync_generation, "resync_revision": self.computer.resync_revision}

        prior = self.completed_tool_calls.get(self._call_key(call))
        if prior:
            if prior["signature"] != self._signature(call):
                return {"ok": False, "error": {"type": "tool_call_id_reused", "message": "Completed ID cannot be reused with changed arguments."}}
            self._call_context[self._call_key(call)] = {**self._call_context.get(self._call_key(call), {}),
                "receipt_reused": True}
            if call.name in {"verify", "inspect_tree", "observe", "inspect_windows", "find_element"}:
                return {"ok": False, "error": {"type": "stale_computer_call_id",
                    "message": "Old observation/verify identity cannot supply current evidence. Use a new call ID for a fresh read."}}
            if prior.get("read_receipt"):
                self._read_receipts[call.id] = {**deepcopy(prior["read_receipt"]), "reused": True, "new_coverage": False, "identity_reuse": True}
            return deepcopy(prior["payload"])
        self._emit("ToolCallRequested", tool_call_id=call.id, name=call.name, arguments=Agent._safe_arguments(call.arguments))
        try:
            args = json.loads(call.arguments)
            if not isinstance(args, dict):
                from .tool_protocol import ToolArgumentsError
                raise ToolArgumentsError(['$: expected object'])
            from .tool_protocol import validate_arguments
            validate_arguments(call.name, args, self._schemas())
            if (self.harness_policy and self.task_contract and self.task_contract.child_output_groups
                    and self._worker_id is None and call.name == 'apply_patch'):
                # Declared disjoint ownership is a host contract, not merely a
                # final-score condition. Reject before approval/intent/effect.
                child_owned = {(self.workspace / path).resolve()
                    for group in self.task_contract.child_output_groups for path in group}
                parent_owned = {(self.workspace / path).resolve()
                    for path in self.task_contract.output_paths} - child_owned
                if any((self.workspace / change['path']).resolve() not in parent_owned
                       for change in args['changes']):
                    from .tool_protocol import ToolArgumentsError
                    raise ToolArgumentsError(['$.changes: host role policy forbids Parent mutations of Child-owned outputs; use Parent-owned paths and preserve all Child obligations'])
            if self.harness_policy and self.hybrid and call.name in {'delegate','request_model_switch'}:
                from .tool_protocol import ToolArgumentsError
                try:
                    self.hybrid.resolve(args.get('backend_preference',args.get('target')),args.get('backend_id'),args.get('model'),args.get('tier'))
                except ValueError as error:
                    raise ToolArgumentsError(['$.backend_id/model: '+str(error)]) from error
            if call.name not in RUNTIME_TOOL_NAMES | ASYNC_TOOL_NAMES:
                # These checks cannot dispatch; exceptions after intent remain UNKNOWN.
                import inspect
                canonical = 'execute' if call.name == 'run_command' else call.name
                if canonical not in self.registry._tools:
                    if self.legacy:
                        raise ValueError(f'Unknown tool: {canonical}')
                    return self._argument_rejection(call, 'unknown_tool', [f'Unknown registered tool: {canonical}'])
                self.registry.metadata(canonical)
                self.registry.validate_extension_arguments(canonical, args)
                try:
                    inspect.signature(self.registry._tools[canonical]).bind(workspace_root=self.workspace, **args)
                except TypeError as error:
                    if self.legacy:
                        raise
                    return self._argument_rejection(call, 'schema_validation', [str(error)])
            self._emit('ToolArgumentsAccepted', tool_call_id=call.id, name=call.name,
                       stage='accepted_not_executed', normalized_arguments=args)
            if call.name in RUNTIME_TOOL_NAMES | ASYNC_TOOL_NAMES:
                if not self.runtime_tools and not (self.hybrid and call.name == 'request_model_switch'):
                    raise ValueError("Runtime actions are disabled")
                if (self.permission_mode in {"approve-all", "all_confirm"} and not approved
                        and call.name != "request_model_switch"):
                    self.pending_approval = {"kind": "runtime", "call": deepcopy(call), "name": call.name,
                        "preview": args, "fingerprint": self._fingerprint(args)}
                    self.state = SessionState.TOOL_AWAITING_APPROVAL
                    self._emit("ApprovalRequired", **self._approval_view())
                    return self._payload({"status": "approval_required"})
                if call.name in ASYNC_TOOL_NAMES:
                    if not self.async_policy:
                        raise ValueError("Async coordinator actions are disabled")
                    return self._async_action(call, args)
                return self._runtime_action(call, args, approved)
            self.registry.gateway.plan_read_only = self._planning
            if not self.legacy and call.name not in RUNTIME_TOOL_NAMES | ASYNC_TOOL_NAMES:
                from .scope_permissions import proposal
                from .persistence import recovery_class
                if self.registry.metadata(call.name).mutating and recovery_class(self) == 'UNKNOWN_BLOCKED':
                    return {'ok':False,'error':{'type':'unknown_effect_quarantined','message':'Uncertain effects require host recovery'},
                        'result':{'status':'blocked','stage':'not_dispatched','action_sent':False,'repair_allowed':False,'replay_allowed':False}}
                try:
                    request = proposal(self.registry, call.name, args)
                    from .scope_permissions import automatic
                    if request and scope_approval is None and automatic(self.registry,call.name):scope_approval=request
                    if scope_approval is not None and request != scope_approval:
                        raise PermissionError("Approval expired: action or resource changed")
                except (PermissionError, ValueError, OSError) as error:
                    return {'ok':False, 'error':{'type':'scope_denied','message':str(error)},
                        'result':{'status':'denied','stage':'not_dispatched','action_sent':False,
                            'action_may_have_applied':False,'repair_allowed':False,'replay_allowed':False}}
                if request and scope_approval is None:
                    preview = {"status": "approval_required", "scope_request": request, "action_sent": False}
                    self.pending_approval = {"kind": "scope", "call": deepcopy(call), "tool_call_id": call.id,
                        "name": call.name, "preview": preview, "scope_request": request}
                    self.state = SessionState.TOOL_AWAITING_APPROVAL
                    self._emit("ApprovalRequired", **self._approval_view())
                    return self._payload(preview)
            if self.hybrid and call.name == 'apply_patch':
                past = self.hybrid.completed_patch(args)
                if past:
                    self._call_context[self._call_key(call)] = {'receipt_reused': True}
                    payload = deepcopy(past['payload'])
                    payload['result'].update(canonical_receipt_reused=past['receipt_id'], action_sent=False,
                        replay_allowed=False, instruction='Prior completed effect receipt only. No mutation dispatched; read current versions before claiming verification.')
                    self._emit('HybridMutationReplaySuppressed', tool_call_id=call.id, source_receipt_id=past['receipt_id'])
                    return payload
            self._emit("ToolCallStarted", tool_call_id=call.id, name=call.name)
            self._check_cancel()
            if self.legacy:
                result = self.registry.call(call.name, args, approved=True) if approved else self.registry.call(call.name, args)
            else:
                metadata = self.registry.metadata(call.name)
                from .host_tools import qualified_shell
                if self.hybrid and metadata.mutating and call.name not in {'apply_patch','make_directory','move_file','copy_file'} and not qualified_shell(self.registry,call.name) and not self.registry.is_plugin_tool(call.name):
                    return {'ok': False, 'error': {'type': 'hybrid_mutation_unqualified',
                        'message': 'Hybrid mutation identity is qualified only for workspace apply_patch.'},
                        'result': {'status': 'denied', 'stage': 'not_dispatched', 'action_sent': False,
                                   'action_may_have_applied': False, 'replay_allowed': False}}
                if metadata.mutating and not self.computer:
                    from .persistence import recovery_class
                    if recovery_class(self) == 'UNKNOWN_BLOCKED':
                        return {'ok':False,'error':{'type':'unknown_effect_quarantined',
                            'message':'Uncertain effects require host recovery; no new mutation dispatched.'},
                            'result':{'status':'blocked','action_sent':False,'replay_allowed':False}}
                self._durable_intent = {"call": call.to_dict(), "turn_id": self.turn_id,
                    "signature": self._signature(call),
                    "read_only": metadata.read_only and not metadata.mutating}
                self._persist("tool_intent", "tool_inflight")
                if getattr(self.registry, 'plugin_manager', None):
                    self.registry.plugin_request_id = f'{self._plugin_namespace}/turn:{self.turn_id}/call:{call.id}'
                if self._async_enabled:
                    with external(self._state_condition):
                        result = self.registry._call_prevalidated(call.name, args, approved=approved, receipt_id=call.id, scope_approval=scope_approval)
                else:
                    result = self.registry._call_prevalidated(call.name, args, approved=approved, receipt_id=call.id, scope_approval=scope_approval)
            payload = self._payload(result)
            from .host_tools import qualified_shell
            completed_shell_failure = (qualified_shell(self.registry,call.name) and isinstance(result,dict)
                and result.get('status')=='nonzero_exit' and result.get('process_completed') is True)
            if (not self.legacy and metadata.mutating and isinstance(result, dict)
                    and result.get('status') in {'unknown','UNKNOWN'}):
                payload = {'ok':False,'error':{'type':'unknown_effect','message':'Tool reported an uncertain mutation.'},
                    'result':{**result,'action_may_have_applied':True,'replay_allowed':False}}
            if (not self.legacy and not self.computer and metadata.mutating and not payload.get("ok")
                    and isinstance(result, dict) and result.get("status") in {"error", "timeout", "nonzero_exit"}
                    and result.get("action_sent") is not False and result.get("applied") != [] and not completed_shell_failure):
                # A failing process/extension may already have changed the world.
                # A receipt for failure is not a certificate of no side effects.
                payload["result"] = {**result, "action_may_have_applied": True, "replay_allowed": False}
            if getattr(self.registry, "last_read_receipt", None):
                self._read_receipts[call.id] = deepcopy(self.registry.last_read_receipt)
            if isinstance(result, dict) and result.get("status") == "approval_required":
                self.pending_approval = {"kind": "tool", "call": deepcopy(call), "tool_call_id": call.id,
                    "name": call.name, "preview": result, "fingerprint": self._tool_fingerprint(call, args)}
                self.state = SessionState.TOOL_AWAITING_APPROVAL
                self._emit("ApprovalRequired", **self._approval_view())
            return payload
        except SessionCancelled:
            raise
        except PersistenceError:
            raise
        except json.JSONDecodeError as error:
            if (self._durable_intent and not self._durable_intent['read_only']
                    and self.registry.last_dispatch_started):
                return {'ok':False,'error':{'type':type(error).__name__,'message':str(error)},
                    'result':{'status':'error','action_may_have_applied':True,'replay_allowed':False}}
            return self._argument_rejection(call, 'invalid_json_arguments', [str(error)])
        except Exception as error:
            from .tool_protocol import ToolArgumentsError
            absence = getattr(self.registry, 'last_read_failure', None)
            if (self.engine_policy and call.name == 'read_file' and type(error) is FileNotFoundError
                    and absence and absence.get('source') == 'authorized_builtin_read_file'):
                self._read_receipts[call.id] = {'absence_observation': deepcopy(absence),
                    'evidence_id': 'absence-' + self._signature(call)[:16],
                    'excerpt': excerpt('Authorized built-in read observed target_not_found; no content read.', 256),
                    'version': None, 'coverage': {'kind': 'none', 'truncated': False},
                    'reused': False, 'source_call_id': call.id}
            if isinstance(error, ToolArgumentsError) and not self._durable_intent:
                return self._argument_rejection(call, 'schema_validation', error.errors)
            if (self._durable_intent and not self._durable_intent["read_only"]
                    and self.registry.last_dispatch_started):
                return {"ok": False, "error": {"type": type(error).__name__, "message": str(error)},
                    "result": {"status": "error", "action_may_have_applied": True, "replay_allowed": False}}
            return {"ok": False, "error": {"type": type(error).__name__, "message": str(error)}}

    def _argument_rejection(self, call, kind, errors):
        rejected = sum(r['turn_id'] == self.turn_id and
                       r['payload'].get('error', {}).get('type') in {'schema_validation', 'invalid_json_arguments', 'unknown_tool'}
                       for r in self.tool_history)
        repair_allowed = rejected < 3
        remaining = max(0, 3-rejected)
        repair_policy = self.engine_policy or self.harness_policy
        if repair_policy:
            from .harness import proposal_identity
            identical = sum(r['turn_id'] == self.turn_id and r['name'] == call.name
                and proposal_identity(r['name'],r['arguments']) == proposal_identity(call.name,call.arguments)
                and r['payload'].get('error', {}).get('type') in {'schema_validation','invalid_json_arguments','unknown_tool'}
                for r in self.tool_history)
            repair_allowed = (rejected + 1 < repair_policy.max_invalid_calls
                and identical + 1 < repair_policy.max_identical_invalid_calls)
            remaining = max(0,min(repair_policy.max_invalid_calls-rejected-1,
                repair_policy.max_identical_invalid_calls-identical-1))
        self._emit('ToolArgumentsRejected', tool_call_id=call.id, name=call.name,
                   stage='not_dispatched', errors=errors, repair_allowed=repair_allowed)
        return {'ok': False, 'error': {'type': kind, 'message': '; '.join(errors), 'fields': errors},
                'result': {'status': 'invalid_arguments', 'stage': 'not_dispatched', 'action_sent': False,
                           'action_may_have_applied': False, 'repair_allowed': repair_allowed,
                           'repair_attempts_remaining': remaining,
                           'instruction': 'Correct the listed schema fields and replan with a new call ID; no tool was dispatched.'
                               if repair_allowed else 'Schema repair limit exhausted. Stop and report unfinished work.'}}

    @staticmethod
    def _payload(result):
        unsuccessful = isinstance(result, dict) and result.get("status") in {"denied", "unavailable", "approval_required", "timeout", "cancelled", "nonzero_exit", "error", "unknown", "UNKNOWN", "blocked"}
        payload = {"ok": not unsuccessful, "result": result}
        if unsuccessful:
            payload["error"] = {"type": result["status"], "message": "Tool operation did not complete successfully."}
        return payload

    def _record_call(self, call, payload):
        # Bound coordinator/worker outputs through the same output budget.
        if "result" in payload:
            payload = {**payload, "result": self.registry._bound_result(payload["result"])}
        read_receipt = self._read_receipts.pop(call.id, None)
        if not self.legacy:
            try:
                entry = self.working.record(call, payload, read_receipt)
                self._emit("EvidenceRecorded", tool_call_id=call.id, tool=call.name, evidence_id=entry["evidence_id"],
                           reused=bool(entry.get("reused")), duplicate_same_version=entry["duplicate_same_version"],
                           new_evidence=not entry["duplicate_no_progress"],
                           physical_read=bool(read_receipt and not read_receipt.get("reused")),
                           read_cache_hit=bool(read_receipt and read_receipt.get("reused") and not read_receipt.get("identity_reuse")),
                           coverage=entry["coverage"], version=entry.get("version"),
                           no_progress=self.working.no_progress)
            except (ValueError, TypeError):
                # Invalid model arguments are still accounted as repeated failure.
                self.working.no_progress += 1
        message = Message("tool", json.dumps(payload, ensure_ascii=False), tool_call_id=call.id)
        self.messages.append(message)
        result = payload.get("result")
        partial_effect = isinstance(result, dict) and (bool(result.get("applied")) or result.get("action_sent") is True) and not payload.get("ok")
        unknown_effect = isinstance(result, dict) and result.get("action_may_have_applied") is True
        from .host_tools import qualified_shell
        completed_shell_failure = (qualified_shell(self.registry,call.name) and isinstance(result,dict)
            and result.get('status')=='nonzero_exit' and result.get('process_completed') is True)
        record = {"signature": self._signature(call), "arguments": call.arguments,
                  "payload": deepcopy(payload), "read_receipt": deepcopy(read_receipt),
                  "receipt_id": f"turn:{self.turn_id}/call:{call.id}/entry:{len(self.tool_history)}",
                  "status": "completed" if payload.get("ok") else "failed",
                  "side_effect_completed": bool(payload.get("ok")) or partial_effect and not completed_shell_failure,
                  "side_effect_status": "unknown" if unknown_effect else "failed_process" if completed_shell_failure else "partial" if partial_effect else "completed" if payload.get("ok") else "not_completed"}
        context = self._call_context.pop(self._call_key(call), {})
        record["receipt_reused"] = context.pop("receipt_reused", False)
        from .tool_protocol import resolves_patch_rejection
        current = {'name': call.name, **record}
        repaired_proposals = [r['receipt_id'] for r in self.tool_history
            if r['turn_id'] == self.turn_id and resolves_patch_rejection(r, current)]
        if repaired_proposals:
            record['repaired_proposals'] = repaired_proposals
        if self.computer:
            context.setdefault("dispatch_generation", self.computer.revision)
            context.setdefault("resync_generation", self.computer.resync_generation)
            context.setdefault("resync_revision", self.computer.resync_revision)
            context["recorded_at"] = self.computer.clock()
            record["computer_context"] = context
            observation = result.get("observation") if isinstance(result, dict) else None
            observed = next((r for r in self.computer.observations.values() if r["token"] == observation), None)
            if observed and not record["receipt_reused"]:
                record["computer_evidence"] = {"source_call_id": call.id, "source_turn_id": self.turn_id,
                    "observation": observation, "observation_generation": observed["generation"],
                    "observed_at": observed["at"], "resync_generation": observed["resync_generation"]}
        self.completed_tool_calls.setdefault(self._call_key(call), record)
        self.tool_history.append({"turn_id": self.turn_id, "id": call.id, "name": call.name, **record})
        if self._ledger_parent:
            self._ledger_parent._sync_child(self._worker_id)
        self._durable_intent = None
        self._persist("tool_receipt", "receipt")
        self._emit("ToolCallCompleted" if payload.get("ok") else "ToolCallDenied", tool_call_id=call.id, name=call.name,
                   status=record["status"], error_type=payload.get("error", {}).get("type"))
        native_call = {"id": call.id, "function": {"name": call.name, "arguments": call.arguments}}
        self._debug(Agent._tool_trace(native_call, message.to_dict(), len(self._usage)))

    def _tool_fingerprint(self, call, args):
        if self.registry.is_plugin_tool(call.name):
            return self.registry._tools[call.name].approval_fingerprint(args)
        return self._fingerprint(args)

    def _fingerprint(self, args):
        from .scope_permissions import workspace_arguments
        args = workspace_arguments(self.registry, "apply_patch" if "changes" in args else "read_file", args)
        result = {}
        for change in args.get("changes", []):
            path = resolve_workspace_path(self.workspace, change["path"], must_exist=False, writing=True)
            result[change["path"]] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        # Approval binds the complete immutable proposal and referenced resource versions.
        result['arguments_sha256']=hashlib.sha256(json.dumps(args,sort_keys=True).encode()).hexdigest()
        from .safe_files import inspect_file
        paths=[args[k] for k in ('path','source','destination') if isinstance(args.get(k),str)]
        for value in args.get('argv',[]):
            if isinstance(value,str) and not value.startswith('-') and not Path(value).is_absolute():
                if (self.workspace/value).is_file():paths.append(value)
        for path in paths:
            try:result['resource:'+path]=inspect_file(self.workspace,path)
            except FileNotFoundError:result['resource:'+path]=None
        return result
