"""Model admission, streaming and final delivery for the canonical Session."""
from copy import deepcopy
from dataclasses import asdict
import json
import sys
import time
from .async_runtime import external
from .hybrid import HybridController, HybridPolicy
from .host_tools import qualified_shell
from .backends import BackendCapabilities, BackendResponse, Message
from .context import context_units, ContextTooSmall
from .context_budget import request_budget, context_tokens
from .loop import Agent
from .policy import DataPolicy
from .retry import RetryPolicy, call_with_retry, is_transient_error
from .routing import FallbackReason, RoutingPolicy
from .stabilization import WorkingStateTooLarge, ReserveReached, evaluate_verification, encoded, snapshot_units, excerpt
from .session_types import PartialStreamError, SessionCancelled, SessionState


class SessionModelCalls:
    def _complete_unexecuted(self, calls, reason):
        for call in calls:
            self.messages.append(Message("tool", json.dumps({"ok": False, "error": {"type": reason}}), tool_call_id=call.id))

    @property
    def _output_guard(self):
        return self.budgets.max_output_tokens * 16

    @property
    def _exploration_limit(self):
        return self.budgets.max_token_units - self._final_reserve

    def _enter_finalizing(self, reason):
        self._finalizing = True
        self._final_reason = reason
        self.state = SessionState.FINALIZING
        if self.finalization_policy:
            self._prepare_delivery()
        self._emit("FinalizingStarted", reason=reason, attempts=self._attempts,
                   admission_units=self._token_units, reserve_units=self._final_reserve)

    def _prepare_delivery(self):
        from .finalization import ledger_projection, delivery_view
        if not self.finalization_policy or not self._completion:
            return
        projection = ledger_projection(self)
        obligations = projection['obligations']
        execution = ('unknown_blocked' if obligations['unknown_receipts'] or obligations['mutation_intent'] else
                     'incomplete' if any(obligations.values()) else 'settled')
        readiness = None
        if self.completion_check and execution == 'settled':
            try:
                check = self.completion_check(self.workspace, deepcopy(projection))
                verified, _, reason = evaluate_verification(self.workspace, check)
                readiness = {**asdict(check), 'reason': reason, 'source': 'trusted_completion_check'}
                if verified == 'passed':
                    execution = 'completed'
                else:
                    execution = 'unknown_blocked' if verified in {'unknown', 'blocked'} else 'incomplete'
            except Exception as error:
                execution = 'unknown_blocked'
                readiness = {'status': 'unknown', 'error_type': type(error).__name__, 'source': 'trusted_completion_check'}
        self._completion.update(execution=execution, readiness=readiness,
            ledger_sha256=projection['ledger_sha256'], receipt_count=projection['receipt_count'],
            obligations=obligations)
        if self.harness_policy:
            from .harness import file_evidence
            evidence = file_evidence(self)
            self._completion['file_evidence'] = evidence
            if evidence['failures'] and execution in {'settled', 'completed'}:
                self._completion['execution'] = 'incomplete'
        limit = self.finalization_policy.view_bytes
        self._delivery_view = delivery_view(self, projection, limit)
        if self._finalizing:
            self._completion['delivery'] = 'pending' if self._completion['delivery'] != 'failed' else 'failed'

    def _delivery_failure(self, kind, detail, usage=None, finish_reason=None):
        # A natural final response in exploration also consumes a delivery
        # attempt. Final-only attempts were counted before model_start commit.
        if not self._completion['attempts']:
            self._completion['attempts'] = 1
        self._completion['delivery'] = 'failed'
        self._completion['history'].append({'attempt': self._completion['attempts'], 'kind': kind,
            'detail': excerpt(detail, 512), 'finish_reason': finish_reason, 'provider_usage': usage})
        self._emit('FinalizationFailed', **self._completion['history'][-1])
        self._persist('finalization_failed', 'ready')

    def _can_recover_delivery(self):
        return (self._completion['attempts'] < self.finalization_policy.max_attempts
                and self._attempts < self.budgets.max_steps
                and self._completion['execution'] not in {'unknown_blocked'}
                and not self.pending_approval and not self._queue)

    def _working_snapshot(self, max_bytes=None):
        if self.computer:
            self.working.computer = self._computer_summary()
        ledger = None
        if self.finalization_policy:
            from .finalization import ledger_projection, sha
            projection = ledger_projection(self)
            ledger = {k: v for k, v in projection.items() if k not in {'manifest', 'stages'}}
            ledger.update(stages_count=len(projection['stages']), stages_sha256=sha(projection['stages']))
        return self.working.snapshot(phase="finalizing" if self._finalizing else self.state.value,
            plan=self.active_plan if not self.active_plan or self.active_plan.get("turn_id", self.turn_id) == self.turn_id else None, goals=self._goal_records(),
            pending={"kind": self.pending_approval["kind"], "name": self.pending_approval.get("name")} if self.pending_approval else None,
            plan_mode=self._planning if self.computer else None,
            permission_mode=self.permission_mode if self.computer else None, max_bytes=max_bytes,
            read_allowed=self.registry.gateway.capabilities.read, turn_id=self.turn_id,
            finalization_reason=self._final_reason,
            ledger=ledger,
            budget={"attempts": self._attempts, "max_attempts": self.budgets.max_steps,
                    "tool_proposals": self._tool_proposals, "max_tool_calls": self.budgets.max_tool_calls,
                    "admission_units": self._token_units, "max_units": self.budgets.max_token_units})

    def _request_history_scope(self, backend, canonical_view, schemas):
        if not canonical_view:
            return None
        from .persistence import backend_identity, digest, dumps
        scope = {'backend': backend_identity(backend),
                 'hybrid': self.hybrid._reasoning_scope() if self.hybrid else None,
                 'system': next((m.content for m in self.messages if m.role == 'system'), None),
                 'tools': schemas,
                 'desktop_context': getattr(self, '_desktop_cloud_context', False)}
        if self.computer and getattr(self.computer, 'v5_integration_revision', None) == 1:
            scope['computer_egress'] = asdict(self.computer.cloud_egress)
        return digest(dumps(scope))

    def _model_request(self):
        if self.cooperative:
            self.cooperative.before_request()
        if self.async_policy:
            if (self._attempts + self._reserved_child_budget('_attempts') >= self.budgets.max_steps - 1 or
                    self._token_units + self._reserved_child_budget('_token_units') >= self._exploration_limit):
                self._async_barrier()
                if self.pending_approval:
                    raise ReserveReached("Children awaiting host approval; parent request withheld")
        self._refresh_prompt()
        backend = self.current_backend
        if not self.legacy and self.routing_policy == RoutingPolicy.CLOUD_ONLY and self.primary != "cloud":
            raise PermissionError("cloud-only forbids a local primary")
        policy = DataPolicy(local_only=self.hard_data_policy.local_only or self.routing_policy == RoutingPolicy.LOCAL_ONLY)
        policy.check_backend(backend)
        self.registry.gateway.data_policy = policy
        if self.primary == "local" and not self.legacy and not self._eligible():
            detail = self.local_backend.status().get("error") if hasattr(self.local_backend, "status") else None
            raise RuntimeError("Local main agent unavailable: " +
                               (detail or "backend, model size or context eligibility failed."))
        if backend is None:
            raise RuntimeError("Cloud backend unavailable. Set DEEPSEEK_API_KEY; local provisioning/download is not implemented in this build.")
        schemas = None if self._finalizing or getattr(backend, "service_reasoning_only", False) else self._schemas()
        capabilities = getattr(backend, "capabilities", None)
        if capabilities is not None and not capabilities.supports_tool_calling:
            schemas = None
        window = getattr(getattr(backend, "model_info", None), "effective_context", None) or 131072
        self._request_output_tokens = self.budgets.max_output_tokens
        if self.finalization_policy:
            recovery_slots = max(1, self.finalization_policy.max_attempts - self._completion['attempts'])
            # Byte guards, not measured tokens. Grow the protected allowance
            # with evidence size; never increase the host/client output ceiling.
            target = min(self.budgets.max_output_tokens, max(256, 256 + 24 * len(self.working.evidence)))
            if self._finalizing:
                self._request_output_tokens = min(self.budgets.max_output_tokens, target * (2 ** self._completion['attempts']))
            final_input = context_units([m for m in self.messages if m.role == 'system'], None) + self.finalization_policy.view_bytes + 1024
            output_reserves = sum(min(self.budgets.max_output_tokens, target * 2 ** i) * 16
                                  for i in range(self._completion['attempts'], self.finalization_policy.max_attempts))
            self._final_reserve = recovery_slots * final_input + output_reserves
        if self.controls.reserve and self._final_reserve > self.budgets.max_token_units:
            raise ValueError("Turn budget cannot fit minimum bounded final reserve; no request sent.")
        try:
            state_view = None
            state_limit = None
            request_messages = self.messages
            projected_reads = []
            retained_reads = []
            retained_resume = False
            if self.controls.working_state:
                if self.computer:
                    output_reserve = self._request_output_tokens + max(64, window // 50)
                    prefix_units = context_tokens([m for m in self.messages if m.role == "system"], schemas,
                                                  tokenizer=getattr(backend, 'tokenizer', None))
                    # Space for the serialized state Message header/framing.
                    # Reduce optional old evidence, never the output/final reserve
                    # or the critical task/control/current observation fields.
                    state_limit = min(self.working.max_snapshot_bytes, window - output_reserve - prefix_units - 512)
                    try:
                        state_view = self._working_snapshot(max_bytes=state_limit)
                    except WorkingStateTooLarge as error:
                        raise ContextTooSmall(str(error)) from error
                    if not self._finalizing:
                        read_messages, sources, group_units = self._computer_context_read()
                        resume_messages, host_resume, resume_units = self._computer_context_resume()
                        if host_resume:
                            read_messages, sources, group_units = resume_messages, [], resume_units
                        if group_units and context_units(self.messages, schemas) + snapshot_units(state_view) + 512 > window - output_reserve:
                            try:
                                state_view = self._working_snapshot(max_bytes=state_limit - group_units)
                            except WorkingStateTooLarge:
                                pass  # Critical state takes precedence; never weaken admission.
                            else:
                                request_messages, projected_reads = read_messages, sources
                                retained_resume = host_resume
                                state_limit -= group_units
                                for message in reversed(request_messages):
                                    if message.role != "tool":
                                        break
                                    retained_reads.insert(0, message.tool_call_id)
                try:
                    if state_view is None:
                        state_view = self._working_snapshot(max_bytes=state_limit)
                except WorkingStateTooLarge as error:
                    raise ContextTooSmall(str(error)) from error
            if self.finalization_policy and self._finalizing:
                state_view = self._delivery_view
            history_prefix, history_scope = [], None
            history_source_count = len(self.messages)
            if self.engine_policy:
                history_scope = self._request_history_scope(backend, request_messages is self.messages, schemas)
                history_prefix, request_messages = self._request_history.split(request_messages, history_scope)
            if self.hybrid:
                request_messages = self.hybrid.project_messages(request_messages)
                contract = self.hybrid.contract(backend)
                if getattr(backend, 'service_receipt_refs', False) and not backend.is_local:
                    from .deepseek_context import project_handoff
                    contract = project_handoff(contract, schemas)
                state_view = None if getattr(backend, 'service_reasoning_only', False) else contract if not backend.is_local else {'working_state': state_view, 'model_handoff': contract}
            request_messages = history_prefix + request_messages
            from .harness_context import transfer_with_optional_projection
            transfer = transfer_with_optional_projection
            v5_options = {}
            if self.engine_policy:
                from .context_v5 import transfer, host_state
                state_view = host_state(self, state_view, schemas)
                if self._finalizing:
                    v5_options['delivery_budget'] = {
                        'remaining': self.budgets.max_token_units - self._token_units - self._reserved_child_budget('_token_units'),
                        'slots': recovery_slots if self.finalization_policy else 1,
                        'output_units': output_reserves if self.finalization_policy else self._request_output_tokens * 16}
            if (sys.platform == 'linux' and qualified_shell(self.registry, 'shell')
                    and any(schema['function']['name'] == 'shell' for schema in schemas or ())):
                # Platform facts belong to the current request, not frozen checkpoint contracts.
                state_view = {**(state_view or {}), 'host_shell': {
                    'platform': 'linux', 'executable': '/bin/bash', 'scoped_backend': 'bubblewrap',
                    'permission_mode': self.permission_mode,
                    'contract': 'Persisted macOS labels are historical; this Shell executes on Linux. Full uses the current Linux user without an app sandbox. Confined modes require bubblewrap and restrict writes, not network. Current host permissions remain authoritative.'}}
            view, compacted = transfer(request_messages, schemas, window,
                self._request_output_tokens + max(64, window // 50),
                plan=self.active_plan, goals=self._goal_records(),
                working_state=state_view,
                final_only=self._finalizing,
                stable_history_prefix=bool((self.harness_policy and self.harness_policy.cache_stable_prefix)
                    or getattr(backend, "service_cache_stable_prefix", False)),
                enabled=bool(self.harness_policy and self.hybrid and backend.is_local and not self._finalizing),
                tokenizer=getattr(backend, 'tokenizer', None), **v5_options)
        except ContextTooSmall:
            if self.controls.reserve and not self._finalizing:
                self._enter_finalizing("context_reserve")
                return self._model_request()
            raise
        if compacted and self.controls.working_state:
            compacted["state_bytes"] = len(encoded(state_view))
            compacted["state_limit_bytes"] = state_limit
            if retained_reads:
                compacted["retained_ax_read_call_ids"] = retained_reads
                compacted["unprojected_history_estimated_units"] = context_units(self.messages, schemas)
            if projected_reads:
                compacted["projected_ax_read_call_ids"] = projected_reads
            if retained_resume:
                compacted["retained_host_resume_instruction"] = True
        if compacted:
            self._emit("ContextCompacted", **compacted)
        egress = None
        if self.computer and getattr(self.computer, 'v5_integration_revision', None) == 1 and not backend.is_local:
            # Reuse the existing exact-packet Cloud Egress Policy and approval
            # flow. No hybrid switching, canonical replay or automatic uploads.
            if self._computer_egress is None:
                from .hybrid import HybridController, HybridPolicy
                self._computer_egress = HybridController(self, HybridPolicy(self.computer.cloud_egress,
                    automatic_failover=False), {'computer': backend}, 'computer')
            egress = self._computer_egress.authorize(view, schemas)
        if self.hybrid:
            try:
                egress = self.hybrid.authorize(view, schemas)
            except Exception as error:
                if self.hybrid.fallback(error, False):
                    return self._model_request()
                raise
        context_budget = request_budget(view, schemas, self._request_output_tokens,
                                        tokenizer=getattr(backend, 'tokenizer', None))
        if context_budget['total_tokens'] > window:
            raise ContextTooSmall("Projected model input and output exceed the model's token window.")
        request_units = context_units(view, schemas)
        output_charge = self._request_output_tokens * 16 if self.controls.reserve else self._request_output_tokens
        limit = (self.budgets.max_token_units if self._finalizing else self._exploration_limit) - self._reserved_child_budget('_token_units')
        if self.controls.reserve and not self._finalizing and self._token_units + request_units + output_charge > limit:
            self._enter_finalizing("token_reserve")
            return self._model_request()
        if self._token_units + request_units + output_charge > limit:
            raise RuntimeError("Turn token admission budget exhausted (conservative byte estimate).")
        effort = self._effective_thinking(backend)
        if hasattr(backend, "thinking_mapping"):
            mapping = backend.thinking_mapping(effort, has_tools=bool(schemas))
            self._debug({"event": "thinking_mode_mapped", **mapping})
        elif not getattr(backend, "capabilities", BackendCapabilities()).supports_reasoning_effort:
            self._debug({"event": "thinking_mode_mapped", "requested": effort,
                         "effective": "provider_default", "reason": "unsupported_reasoning_effort"})
        self._emit("ModelRequestStarted", primary=self.primary, model=self.current_primary_model, thinking=effort, phase="finalizing" if self._finalizing else "exploring", role="worker" if self.depth else "parent")
        self._emit('ModelBudgetEstimated', estimator=context_budget['estimator'],
            context_capacity_units=window, request_units=context_budget['input_tokens'],
            remaining_context_units=window - context_budget['total_tokens'],
            remaining_turn_units=self.budgets.max_token_units - self._token_units,
            legacy_turn_request_bytes=request_units, estimated_context_tokens=context_budget,
            max_output_tokens=self._request_output_tokens, protected_final_units=self._final_reserve)
        self._debug({"event": "model_request", "step": len(self._usage) + 1})
        started = time.perf_counter()
        self._streamed = False
        cache_snapshot_committed = False
        def request():
            nonlocal cache_snapshot_committed
            self._check_cancel()
            # Retries are charged as requests too; never reset a budget on retry.
            if self.controls.reserve and (self._attempts >= self.budgets.max_steps - (0 if self._finalizing else self.finalization_policy.max_attempts if self.finalization_policy else 1)
                    or self._token_units + request_units + output_charge > limit):
                raise ReserveReached("Request retry cannot consume final reserve.")
            if self._token_units + request_units + output_charge > limit:
                raise RuntimeError("Turn token budget exhausted during request retry.")
            self._attempts += 1
            if self.finalization_policy and self._finalizing:
                self._completion['attempts'] += 1
                self._completion['delivery'] = 'pending'
            self._token_units += request_units
            self._request_bytes += request_units
            self._emit("ModelAttempt", attempt=self._attempts, request_bytes=request_units,
                       role="worker" if self.depth else "parent", phase="finalizing" if self._finalizing else "exploring")
            policy.check_backend(backend)
            attempt = self.hybrid.begin_attempt(request_units, egress) if self.hybrid else None
            try:
                if self.engine_policy and not cache_snapshot_committed:
                    # Keep exactly the authorized, budgeted view. New canonical
                    # messages are projected once and appended on the next call.
                    self._request_history.commit(view, history_source_count, history_scope)
                    cache_snapshot_committed = True
                if self._cache_enabled() and not self.engine_policy and state_view is not None and not cache_snapshot_committed:
                    # Persist the exact approved request snapshot before dispatch,
                    # so the following call extends the entire previous prefix.
                    # Canonical tool/receipt history remains intact.
                    self.messages.append(deepcopy(view[-1]))
                    cache_snapshot_committed = True
                response = self._request_once(backend, view, schemas, effort)
                if self.hybrid:
                    self.hybrid.end_attempt(attempt, response)
                return response
            except Exception as error:
                if self.hybrid:
                    self.hybrid.end_attempt(attempt, getattr(error, 'response', None), error)
                if getattr(error, 'response', None) is not None:
                    return error.response
                self._failed_attempts += 1
                self._emit("ModelAttemptFailed", attempt=self._attempts, role="worker" if self.depth else "parent",
                           error_type=type(error).__name__, provider_usage=None)
                # Failed/partial attempts have unknown provider usage. Charge the
                # strict allowance conservatively, never label it measured cost.
                if self.controls.reserve:
                    self._token_units += output_charge
                raise
        try:
            response = call_with_retry(request, RetryPolicy(max_attempts=1) if self._finalizing else self.retry_policy,
                on_retry=lambda event: self._emit("ModelRetry", **event), sleep=self._stop_requested.wait)
        except ReserveReached:
            if self._finalizing:
                raise
            self._enter_finalizing("retry_reserve")
            return self._model_request()
        except Exception as error:
            if self.hybrid:
                if self.hybrid.fallback(error, self._streamed):
                    return self._model_request()
                raise
            if (not self._finalizing and self.primary == "local" and self.routing_policy == RoutingPolicy.LOCAL_FIRST
                    and is_transient_error(error) and not self._streamed and self.cloud_backend is not None
                    and not self.hard_data_policy.local_only
                    and self._switches < self.budgets.max_primary_switches_per_turn):
                self.primary = "cloud"
                self._switches += 1
                self._turn_primary_restore = None
                self._emit("BackendFallback", reason=FallbackReason.LOCAL_BACKEND_FAILURE.value,
                           target="cloud", data_categories=self._data_categories())
                self._emit("ModelSwitched", primary="cloud", reason="local_backend_failure")
                self._refresh_prompt()
                return self._model_request()
            raise
        response_bytes = len(json.dumps(response.message.to_dict(include_reasoning=True), ensure_ascii=False).encode())
        self._response_bytes += response_bytes
        # Invalid/oversized complete responses are charged conservatively too.
        self._token_units += min(response_bytes, self._output_guard) if self.controls.reserve else response_bytes
        if response.message.role != "assistant":
            raise ValueError("Backend response must be an assistant message")
        if schemas is None and response.message.tool_calls and not self._finalizing:
            raise ValueError("Backend returned tools despite disabled tool calling")
        if response_bytes > self._request_output_tokens * 16:
            raise ValueError("Model response exceeded the output byte guard; no tools executed")
        latency = time.perf_counter() - started
        if self._token_units > limit:
            raise RuntimeError("Model response exceeded the turn token budget; no tools executed.")
        self._emit("ModelResponseCompleted", role="worker" if self.depth else "parent",
                   response_bytes=response_bytes, finish_reason=response.finish_reason)
        self._debug({"event": "model_response", "step": len(self._usage) + 1, "latency_seconds": latency})
        return response, latency

    def _request_once(self, backend, messages, schemas, effort):
        self._check_cancel()
        self._persist("model_start", "model_inflight")
        def receive():
            self._in_model_call=True
            try:return self._receive_response(backend,messages,schemas,effort)
            except Exception:
                self._check_cancel()
                raise
            finally:self._in_model_call=False
        if self._async_enabled:
            with external(self._state_condition):
                with self._scheduler.model_slot(self):
                    self._check_cancel()
                    if self._persistence_hook:
                        # Storage could have failed in a sibling while queued.
                        with self._state_condition:
                            self._persist("model_admitted", "model_inflight")
                    return receive()
        return receive()

    def _receive_response(self, backend, messages, schemas, effort):
        if self.hybrid:
            if self._async_enabled:
                with self._state_condition:
                    self.hybrid.mark_dispatch()
                    self._persist('hybrid_dispatch_authorized', 'model_inflight')
            else:
                self.hybrid.mark_dispatch()
                self._persist('hybrid_dispatch_authorized', 'model_inflight')
        capabilities = getattr(backend, "capabilities", BackendCapabilities())
        self._emit("ModelResponseStarted", primary=self.primary)
        if self.streaming and capabilities.supports_streaming and hasattr(backend, "stream"):
            response = None
            visible_bytes = 0
            reasoning_bytes = 0
            try:
                for chunk in backend.stream(messages, tools=schemas, thinking=effort,
                                            max_tokens=self._request_output_tokens or self.budgets.max_output_tokens):
                    if chunk.kind != 'response':
                        self._check_cancel()
                    if chunk.kind == "reasoning" and chunk.text:
                        reasoning_bytes += len(chunk.text.encode())
                        if reasoning_bytes + visible_bytes > self.budgets.max_output_tokens * 16:
                            raise ValueError("Streaming response exceeded output byte guard")
                        self._streamed = True
                        if self.reasoning_mode == "full":
                            self._emit("ReasoningDelta", text=chunk.text)
                    if chunk.kind == "text" and chunk.text:
                        visible_bytes += len(chunk.text.encode())
                        if visible_bytes + reasoning_bytes > self.budgets.max_output_tokens * 16:
                            raise ValueError("Streaming text exceeded output byte guard")
                        self._streamed = True
                        self._emit("TextDelta", text=chunk.text)
                    elif chunk.kind == "response":
                        response = chunk.response
                if response is None:
                    raise RuntimeError("Stream ended without a complete response.")
                if self.reasoning_mode == "summary" and response.message.reasoning_content:
                    self._emit("ReasoningSummary", characters=len(response.message.reasoning_content))
                return response
            except SessionCancelled:
                raise
            except Exception as error:
                self._emit("ModelStreamInterrupted", role="worker" if self.depth else "parent",
                           observed_text_bytes=visible_bytes, observed_reasoning_bytes=reasoning_bytes,
                           provider_usage=getattr(getattr(error, 'response', None), 'usage', None),
                           finish_reason=getattr(getattr(error, 'response', None), 'finish_reason', None))
                if self._streamed:
                    if getattr(error, 'response', None) is not None:
                        raise
                    raise PartialStreamError("Response stream interrupted after visible text; no tools from this response executed. " + str(error)) from error
                raise
        if hasattr(backend, "request"):
            response = backend.request(messages, tools=schemas, thinking=effort,
                                       max_tokens=self._request_output_tokens or self.budgets.max_output_tokens)
        else:
            # Compatibility adapter for V0 backends/benchmark fixtures only.
            raw = backend.chat([m.to_dict() for m in messages], tools=schemas)
            response = BackendResponse(Message.from_dict(Agent._assistant_message(raw)), raw.get("usage") or {}, raw.get("model"))
        if response.message.reasoning_content:
            if self.reasoning_mode == "full":
                self._emit("ReasoningDelta", text=response.message.reasoning_content, buffered=True)
            elif self.reasoning_mode == "summary":
                self._emit("ReasoningSummary", characters=len(response.message.reasoning_content))
        if self.streaming and response.message.content:
            self._emit("TextDelta", text=response.message.content, buffered=True)
        return response
