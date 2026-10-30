"""Opt-in host model catalog, canonical handoff and audited cloud admission.

No tool executor, credentials store or replay engine lives here.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
import time

from .backends import Message, ToolCall
from .persistence import PersistenceError, backend_identity, recovery_class


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode()).hexdigest()


class EgressMode(str, Enum):
    LOCAL_ONLY = 'LOCAL_ONLY'
    CLOUD_ALLOWED = 'CLOUD_ALLOWED'
    REQUIRES_APPROVAL = 'REQUIRES_APPROVAL'


@dataclass(frozen=True)
class CloudEgressPolicy:
    mode: str = EgressMode.REQUIRES_APPROVAL.value
    allowed_paths: tuple[str, ...] = ()
    max_request_bytes: int = 131072

    def __post_init__(self):
        EgressMode(self.mode)
        if type(self.max_request_bytes) is not int or self.max_request_bytes <= 0:
            raise ValueError('Egress byte ceiling must be positive')
        if not isinstance(self.allowed_paths, tuple) or any(
                not isinstance(p, str) or not p or PurePosixPath(p).is_absolute()
                or '..' in PurePosixPath(p).parts or str(PurePosixPath(p)) != p
                for p in self.allowed_paths):
            raise ValueError('Egress paths must be exact normalized relative workspace paths')


@dataclass(frozen=True)
class HybridPolicy:
    egress: CloudEgressPolicy = field(default_factory=CloudEgressPolicy)
    automatic_failover: bool = False
    max_cloud_requests_per_turn: int = 32
    # Host-supplied estimates, USD per million tokens, never provider invoices.
    rates: tuple = ()  # (backend_id, input_rate, output_rate), optional

    def __post_init__(self):
        if not isinstance(self.egress, CloudEgressPolicy) or type(self.automatic_failover) is not bool:
            raise ValueError('Hybrid policy is trusted typed host configuration')
        if type(self.max_cloud_requests_per_turn) is not int or self.max_cloud_requests_per_turn < 1:
            raise ValueError('Cloud request ceiling must be positive')
        if not isinstance(self.rates, tuple) or any(not isinstance(r, tuple) or len(r) != 3
                or not isinstance(r[0], str) or any(type(v) not in {int, float} or not math.isfinite(v)
                or v < 0 for v in r[1:]) for r in self.rates):
            raise ValueError('Rates must be finite nonnegative host estimates')
        if len({r[0] for r in self.rates}) != len(self.rates):
            raise ValueError('Duplicate backend rates')


class CloudEgressDenied(PermissionError):
    retryable = False


class CloudEgressApprovalNeeded(CloudEgressDenied):
    def __init__(self, summary):
        super().__init__('Cloud request requires exact host egress approval')
        self.summary = summary


class HybridController:
    def __init__(self, runtime, policy, catalog, primary):
        if not isinstance(policy, HybridPolicy):
            raise TypeError('hybrid_policy must be a host HybridPolicy')
        self.runtime, self.policy = runtime, policy
        self.initial_backend_id = primary
        self.catalog = dict(catalog)
        if not self.catalog or any(not isinstance(k, str) or not k or len(k) > 128
                or getattr(v, 'is_local', None) not in (True, False)
                or not getattr(getattr(v, 'model_info', None), 'effective_context', None)
                for k, v in self.catalog.items()):
            raise ValueError('Hybrid catalog requires named classified model adapters with context limits')
        if primary not in self.catalog:
            raise ValueError('Hybrid primary is not registered')
        self.state = {'backend_id': primary, 'generation': 0, 'task': {}, 'attempts': [],
                      'handoffs': [], 'egress': [], 'grants': [], 'turn_restore': None,
                      'parent_handoff': None}
        if any(getattr(b, "service_cache_stable_prefix", False) is True for b in self.catalog.values()):
            self.state["cache_public_assistant"] = {}
        if any(getattr(b, "service_reasoning_replay", False) is True for b in self.catalog.values()):
            self.state["deepseek_reasoning_public"] = {}
        self.check_target(primary)
        runtime.primary = self.kind(primary)

    def kind(self, alias):
        return 'local' if self.catalog[alias].is_local else 'cloud'

    @property
    def backend(self):
        return self.catalog[self.state['backend_id']]

    def configuration(self):
        result = {'version': 1, 'policy': asdict(self.policy), 'initial_backend_id': self.initial_backend_id,
                  'catalog': {k: backend_identity(v) for k, v in self.catalog.items()}}
        if getattr(self.runtime, 'cooperative', None):
            result['cooperative'] = self.runtime.cooperative.configuration()
        public_tools = getattr(self.runtime.registry, 'public_tool_results', ())
        if public_tools:
            if (not isinstance(public_tools, tuple) or len(set(public_tools)) != len(public_tools)
                    or any(name not in self.runtime.registry._tools for name in public_tools)):
                raise ValueError('Public tool disclosure requires exact host-registered names')
            result['public_tool_results'] = list(public_tools)
        return result

    def check_target(self, alias, *, target=None, model=None):
        if alias not in self.catalog:
            raise ValueError('Unregistered hybrid backend_id')
        kind = self.kind(alias)
        if target is not None and target != kind:
            raise ValueError('backend_id contradicts backend_preference/target')
        if model is not None and model != self.runtime._model_name(self.catalog[alias]):
            raise ValueError('Model assertion does not match registered backend')
        policy = self.runtime.routing_policy.value
        if (kind == 'cloud' and (policy == 'local-only' or self.runtime.hard_data_policy.local_only
                or self.policy.egress.mode == 'LOCAL_ONLY') or kind == 'local' and policy == 'cloud-only'):
            self.runtime._emit('HybridRouteRejected', backend_id=alias, reason='host_data_or_route_policy')
            raise CloudEgressDenied('Host routing/data policy forbids selected backend')
        if kind == 'local':
            from .policy import DataPolicy
            DataPolicy(local_only=True).check_backend(self.catalog[alias])
        return self.catalog[alias]

    def resolve(self, target, alias=None, model=None, tier=None):
        if alias is None:
            backend = (self.runtime.local_backend if target == 'local' else
                       self.runtime.cloud_worker_backends.get(tier) if tier else self.runtime.cloud_backend)
            alias = next((k for k, v in self.catalog.items() if v is backend), None)
        return alias, self.check_target(alias, target=target, model=model)

    def contract(self, backend=None):
        from .finalization import ledger_projection
        r = self.runtime
        backend = backend or self.backend
        projection = ledger_projection(r)
        manifest = []
        for item in projection['manifest']:
            manifest.append({k: deepcopy(v) for k, v in item.items() if k != 'excerpt'})
        # Full obligations stay critical. Completed evidence has an indexed bound.
        recent = manifest[-24:]
        contract = {'model_handoff_version': 1, 'task_identity': deepcopy(self.state['task']),
            'turn_id': r.turn_id, 'worker_id': r._worker_id,
            'generation': self.state['generation'], 'current_goal': r.working.task,
            'revisions': deepcopy(r.working.revisions), 'parent_handoff': deepcopy(self.state['parent_handoff']),
            'completed_steps': [i for i in recent if i['status'] == 'completed'
                                and i.get('effect') not in {'unknown', 'partial'} and i['verification'] != 'unknown'],
            'failed_unknown_actions': [i for i in manifest if i['status'] != 'completed'
                                       or i.get('effect') in {'unknown', 'partial'} or i['verification'] == 'unknown'],
            'pending_obligations': projection['obligations'],
            'pending_call_ids': [c.id for c in r._queue],
            'verified_evidence': [i for i in recent if i['status'] == 'completed' and i['verification'] != 'unknown' and i.get('version') and
                                  i.get('coverage', {}).get('kind') == 'full_file'
                                  and not i.get('coverage', {}).get('truncated')],
            'evidence_scope': 'version_bound_observation; requirement verification is separate',
            'receipt_count': projection['receipt_count'], 'ledger_sha256': projection['ledger_sha256'],
            'omitted_receipts': max(0, len(manifest) - len(recent)),
            'file_scope': projection.get('file_scope'),
            'goal_state': [{k: v for k, v in g.items() if k != 'description'} | {'description_sha256': sha(g.get('description'))}
                           for g in r._goal_records()],
            'approval_state': {'pending_kind': (r.pending_approval or {}).get('kind'),
                               'authority': 'host only; no approval inferred from model/context'},
            'approved_capabilities': asdict(r.registry.gateway.capabilities),
            'permission_mode': r.permission_mode,
            'cloud_body_allowlist': list(self.policy.egress.allowed_paths),
            'cloud_context_instruction': 'Only these exact paths may have file bodies disclosed to cloud. Use declared task paths; do not guess additional numbered files. Withheld bodies are unavailable, and absence observations do not clear failed/UNKNOWN receipts.',

            'available_tools': [s['function']['name'] for s in r._schemas()],
            'tool_schema_sha256': sha(r._schemas()),
            'resource_budget': {'remaining_steps': r.budgets.max_steps - r._attempts,
                'remaining_tools': r.budgets.max_tool_calls - r._tool_proposals,
                'remaining_admission_units': r.budgets.max_token_units - r._token_units,
                'child_reserved_units': r._reserved_child_budget('_token_units')},
            'context_budget': {'model': r._model_name(backend),
                'capacity_units': backend.model_info.effective_context,
                'output_token_ceiling': r.budgets.max_output_tokens,
                'estimator': 'utf8_bytes_conservative_not_measured_tokens'},
            'finalization': deepcopy(r._completion and {k: r._completion.get(k)
                for k in ('execution', 'delivery', 'attempts', 'obligations')}),
            'verification_status': r._verification_status,
            'instruction': 'Receipts are evidence, model judgments are unverified. Never replay completed or UNKNOWN mutation. Omitted evidence is unavailable. Tool approvals and cloud egress are separate host authorities.'}
        # JSON checkpoint encoding sorts maps. Stabilize nested ordering before
        # embedding the contract in a string and fingerprinting egress approval.
        return json.loads(json.dumps(contract, ensure_ascii=False, sort_keys=True))

    def _cache_scope(self, backend_id=None):
        return sha({"backend_id":backend_id or self.state["backend_id"],
                    "egress":asdict(self.policy.egress)})

    def _reasoning_scope(self, backend_id=None):
        alias = backend_id or self.state['backend_id']
        backend = self.catalog[alias]
        return sha({'scope': self._cache_scope(alias), 'provider': getattr(backend, 'provider', None),
                    'model': self.runtime._model_name(backend)})

    def project_messages(self, messages, backend_id=None):
        """Strip private reasoning; replay only hash-bound same-model cloud output.

        Preserve paired provider call IDs. Canonical messages stay untouched.
        """
        cloud = self.kind(backend_id or self.state['backend_id']) == 'cloud'
        out, proposals = [], {}
        for original in messages:
            m = Message.from_dict(original.to_dict())
            if not cloud:
                out.append(m)
                continue
            if m.role == 'assistant':
                target = self.catalog[backend_id or self.state['backend_id']]
                same_cloud_message = (getattr(target, 'service_reasoning_replay', False) is True
                        and self.state.get('deepseek_reasoning_public', {}).get(
                            sha(original.to_dict(include_reasoning=True))) == self._reasoning_scope(backend_id))
                if same_cloud_message:
                    m.reasoning_content = original.reasoning_content
                    m.native_replay = deepcopy(original.native_replay)
                same_cloud_output = same_cloud_message or (
                    getattr(target, "service_cache_stable_prefix", False) is True
                    and self.state.get("cache_public_assistant", {}).get(sha(original.to_dict())) == self._cache_scope(backend_id))
                if not same_cloud_output:
                    m.content = None if m.tool_calls else '[Prior model judgment omitted; unverified]'
                calls = []
                for call in m.tool_calls:
                    try:
                        args = json.loads(call.arguments)
                    except (ValueError, TypeError):
                        args = {}
                    proposals[call.id] = (call.name, args)
                    if call.name in getattr(self.runtime.registry, 'public_tool_results', ()):
                        calls.append(ToolCall(call.id, call.name, call.arguments))
                        continue
                    if call.name == 'apply_patch':
                        args = deepcopy(args)
                        for change in args.get('changes', []):
                            if change.get('path') not in self.policy.egress.allowed_paths:
                                for key in ('content', 'old_text', 'new_text'):
                                    if key in change:
                                        change[key] = '[LOCAL_BODY_WITHHELD sha256=' + sha(change[key]) + ']'
                    elif call.name in {'move_file','copy_file'} and all(args.get(k) in self.policy.egress.allowed_paths for k in ('source','destination')):
                        pass  # Exact authorized path/hash proposals; no file bodies.
                    elif call.name not in {'read_file', 'file_info', 'list_files', 'list_directory','list_entries','inspect_file'}:
                        public = {
                            'delegate': {'backend_preference', 'backend_id', 'model', 'tier', 'read_only', 'mode', 'budget'},
                            'request_model_switch': {'target', 'backend_id', 'model', 'task_complexity', 'scope'},
                            'child_status': set(), 'wait_children': set(), 'cancel_child': {'worker_id'},
                            'manage_goal': {'action', 'id', 'status'}, 'get_env': set(),
                            'search_text': {'path', 'file_pattern', 'case_sensitive', 'max_results'},
                        }.get(call.name, set())
                        projected = {k: deepcopy(v) for k, v in args.items() if k in public}
                        private_fields = {
                            'delegate': {'task'}, 'request_model_switch': {'reason'},
                            'manage_goal': {'description', 'subgoals'},
                            'search_text': {'query'}, 'execute': {'argv'}, 'run_command': {'argv'},
                        }.get(call.name, set())
                        # Keep schema field names and types; a hash must never
                        # masquerade as a fresh, advertised tool parameter.
                        for k, v in args.items():
                            if k in public or k not in private_fields:
                                continue
                            marker = '[LOCAL_ARGUMENT_WITHHELD sha256=' + sha(v) + ']'
                            if isinstance(v, str):
                                projected[k] = marker
                            elif isinstance(v, list) and all(isinstance(x, str) for x in v):
                                projected[k] = [marker]
                        args = projected
                    raw_arguments = json.dumps(args, ensure_ascii=False)
                    if same_cloud_message:
                        try:
                            if json.loads(call.arguments) == args: raw_arguments = call.arguments
                        except (ValueError, TypeError):
                            pass
                    calls.append(ToolCall(call.id, call.name, raw_arguments))
                m.tool_calls = calls
            elif m.role == 'tool':
                name, args = proposals.get(m.tool_call_id, (None, {}))
                if name in getattr(self.runtime.registry, 'public_tool_results', ()):
                    out.append(m)
                    continue
                if name in {'move_file','copy_file'} and all(args.get(k) in self.policy.egress.allowed_paths for k in ('source','destination')):
                    try: payload=json.loads(m.content or '{}')
                    except ValueError:payload={}
                    result=payload.get('result')
                    if isinstance(result,dict):
                        public={k:deepcopy(result[k]) for k in ('status','operation','verification','action_sent','action_may_have_applied','replay_allowed','error_type') if k in result}
                        for key in ('source','destination'):
                            if result.get(key)==args.get(key):public[key]=result[key]
                        for key in ('before','after'):
                            if isinstance(result.get(key),dict):public[key]={k:result[key][k] for k in ('device','inode','size_bytes','modified_ns','type','sha256') if k in result[key]}
                        m.content=json.dumps({'ok':payload.get('ok'),'result':public,'scope':'Exact-path filesystem receipt metadata only; no file bodies or semantic task attestation'})
                        out.append(m);continue
                if name in {'file_info','inspect_file'} and args.get('path') in self.policy.egress.allowed_paths:
                    try:
                        payload = json.loads(m.content or '{}')
                    except ValueError:
                        payload = {}
                    info = payload.get('result')
                    if payload.get('ok') is True and isinstance(info, dict):
                        # Only explicit-path metadata, never extension bodies.
                        metadata = {}
                        if isinstance(info.get('path'), str):
                            metadata['path'] = info['path']
                        if isinstance(info.get('type'), str) and info['type'] in {'file', 'directory'}:
                            metadata['type'] = info['type']
                        if type(info.get('size_bytes')) is int and info['size_bytes'] >= 0:
                            metadata['size_bytes'] = info['size_bytes']
                        if name=='inspect_file':
                            for key in ('device','inode','modified_ns'):
                                if type(info.get(key)) is int:metadata[key]=info[key]
                            if isinstance(info.get('sha256'),str) and re.fullmatch(r'[0-9a-f]{64}',info['sha256']):metadata['sha256']=info['sha256']
                        if type(info.get('exists')) is bool:
                            metadata['exists'] = info['exists']
                        if info.get('observation') == 'target_not_found':
                            metadata['observation'] = 'target_not_found'
                        m.content = json.dumps({'ok': True, 'result': metadata,
                            'scope': 'metadata observation only; no read coverage or goal verification'})
                        out.append(m)
                        continue
                if not (name in {'read_file','list_entries','list_directory'} and args.get('path','.') in self.policy.egress.allowed_paths):
                    try:
                        payload = json.loads(m.content or '{}')
                    except ValueError:
                        payload = {}
                    projected = {'ok': payload.get('ok'), 'body_withheld': True,
                        'tool': name, 'result_sha256': sha(m.content),
                        'status': (payload.get('result') or {}).get('status') if isinstance(payload.get('result'), dict) else None,
                        'instruction': 'Use canonical handoff receipt metadata; withheld body is unavailable. Historical argument markers are not executable arguments.'}
                    if self.runtime.harness_policy:
                        # Safe protocol state, never goal descriptions, child prose,
                        # mutation contents or arbitrary extension return bodies.
                        result = payload.get('result')
                        def goal_state(g):
                            return {k:deepcopy(g[k]) for k in ('id','status','subgoals','parent_id') if k in g}
                        if name == 'manage_goal':
                            if isinstance(result,dict):projected['goal_state']=goal_state(result)
                            elif isinstance(result,list):projected['goal_state']=[goal_state(g) for g in result if isinstance(g,dict)]
                        elif name == 'apply_patch' and isinstance(result,dict):
                            projected['effect_resources']=[{k:c[k] for k in ('path','operation','before_sha256','after_sha256') if k in c}
                                for c in result.get('changes',[]) if isinstance(c,dict)]
                            projected['effect_scope']='Receipt metadata only; not task verification'
                        elif name in {'delegate','wait_children','child_status'} and isinstance(result,dict):
                            projected['worker_state']={k:deepcopy(result[k]) for k in ('status','worker_id') if k in result}
                    error = payload.get('error') or {}
                    if isinstance(error, dict) and error.get('type') in {'schema_validation', 'invalid_json_arguments', 'unknown_tool'}:
                        projected['error'] = {'type': error['type']}
                        if isinstance(error.get('fields'), list):
                            projected['error']['fields'] = [v for v in error['fields'][:8] if isinstance(v, str)]
                        result = payload.get('result') or {}
                        if isinstance(result, dict):
                            projected['validation'] = {k: result[k] for k in ('stage', 'action_sent', 'action_may_have_applied', 'repair_allowed', 'repair_attempts_remaining') if k in result}
                    m.content = json.dumps(projected)
            out.append(m)
        return out

    def authorize(self, messages, schemas):
        if self.backend.is_local:
            return None
        r = self.runtime
        packet = {'backend_id': self.state['backend_id'], 'identity': backend_identity(self.backend),
                  'messages': [m.to_dict() for m in messages], 'tools': schemas}
        raw = json.dumps(packet, ensure_ascii=False, sort_keys=True)
        summary = {'request_sha256': sha(packet), 'backend_id': self.state['backend_id'],
                   'handoff_sha256': sha(self.contract()),
                   'bytes': len(raw.encode()), 'categories': ['task', 'canonical_receipt_metadata', 'tool_schema'],
                   'allowed_body_paths': list(self.policy.egress.allowed_paths),
                   'reason': 'current task model inference; minimum canonical handoff'}
        # Known credentials never leave even an explicitly allowed file/prompt.
        configured = [*self.catalog.values(), r.local_backend, r.cloud_backend, *r.cloud_worker_backends.values()]
        keys = [getattr(b, key, None) for b in configured for key in ('api_key', '_api_key')]
        strings = [raw]
        def collect(value):
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, dict):
                for v in value.values():
                    collect(v)
            elif isinstance(value, list):
                for v in value:
                    collect(v)
        collect(packet)
        scan = '\n'.join(strings)
        secret = any(isinstance(k, str) and k and k in scan for k in keys)
        secret = secret or bool(re.search(r'(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:api[_ -]?key|password|access[_ -]?token|secret)["\']?\s*[=:]\s*["\']?[A-Za-z0-9_+/.-]{8,}|\bsk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9_.-]{16,})', scan))
        decision = ('denied_sensitive_data' if secret else
                    'denied_local_only' if self.policy.egress.mode == 'LOCAL_ONLY' or r.hard_data_policy.local_only else
                    'denied_size' if summary['bytes'] > self.policy.egress.max_request_bytes else
                    'allowed' if self.policy.egress.mode == 'CLOUD_ALLOWED' or summary['request_sha256'] in self.state['grants'] else 'approval_required')
        self.state['egress'].append({**summary, 'decision': decision, 'at': time.time()})
        r._emit('CloudEgressDecision', **summary, decision=decision)
        if decision == 'approval_required':
            raise CloudEgressApprovalNeeded(summary)
        if decision != 'allowed':
            raise CloudEgressDenied(decision)
        return summary

    def completed_patch(self, args):
        """Same-task semantic replay returns a past receipt, never dispatches.

        Only exact workspace patch operations qualify. External commands do not
        have a generic semantic identity, and current file verification is still
        required independently of this past effect receipt.
        """
        from .safety import resolve_workspace_path
        r = self.runtime
        ceiling = r.registry.gateway.capabilities
        if not ceiling.write or ceiling.read_only or r._planning:
            return None
        root = r
        while root._ledger_parent:
            root = root._ledger_parent
        def identity(arguments):
            changes = []
            for change in arguments['changes']:
                c = deepcopy(change)
                if getattr(r.registry, 'scope_policy', None):
                    # Scope preflight precedes replay matching. Canonical identity
                    # must support that already-validated exact outside action.
                    import os
                    c['path'] = os.path.abspath(r.workspace / c['path'])
                else:
                    c['path'] = str(resolve_workspace_path(r.workspace, c['path'], must_exist=False, writing=True))
                changes.append(c)
            return sha(sorted(changes, key=lambda c: (c['path'], c['operation'], sha(c))))
        target = identity(args)
        for receipt in root.tool_history:
            if (receipt['turn_id'] != root.turn_id or receipt['name'] != 'apply_patch'
                    or receipt.get('side_effect_status') != 'completed' or not receipt['payload'].get('ok')
                    or receipt.get('receipt_reused')):
                continue
            try:
                match = identity(json.loads(receipt['arguments'])) == target
            except (ValueError, KeyError, TypeError):
                continue
            if match:
                return receipt
        return None

    def begin_attempt(self, request_units, egress):
        r = self.runtime
        root = r
        while root._ledger_parent:
            root = root._ledger_parent
        if not self.backend.is_local:
            from .persistence import nodes
            count = sum(len([a for a in n.hybrid.state['attempts'] if a['kind'] == 'cloud'
                             and a['task_identity'] == self.state['task']])
                        for n in nodes(root) if n.hybrid)
            if count >= self.policy.max_cloud_requests_per_turn:
                raise CloudEgressDenied('Cloud request budget exhausted')
        if r.adaptive and not self.backend.is_local:
            r.adaptive.reserve_cloud(request_units, r._request_output_tokens or r.budgets.max_output_tokens)
        attempt = {'id': len(self.state['attempts']), 'backend_id': self.state['backend_id'],
            'kind': self.kind(self.state['backend_id']), 'configured_model': r.current_primary_model,
            'provider': getattr(self.backend, 'provider', 'local_http' if self.backend.is_local else 'unknown'),
            'task_identity': deepcopy(self.state['task']), 'turn_id': r.turn_id, 'worker_id': r._worker_id,
            'generation': self.state['generation'], 'started_at': time.time(), 'status': 'inflight',
            'request_admission_units': request_units, 'input_tokens': None, 'output_tokens': None,
            'latency_seconds': None, 'estimated_api_cost_usd': None,
            'egress_sha256': egress and egress['request_sha256']}
        self.state['attempts'].append(attempt)
        return attempt

    def end_attempt(self, attempt, response=None, error=None):
        usage = (response.usage or {}) if response else {}
        attempt.update(status='response' if response else 'failed',
            latency_seconds=time.time() - attempt['started_at'],
            reported_model=response.model if response else None,
            finish_reason=response.finish_reason if response else None,
            error_type=type(error).__name__ if error else None,
            input_tokens=usage.get('prompt_tokens'), output_tokens=usage.get('completion_tokens'),
            provider_tokens_per_second=usage.get('generation_tokens_per_second'))
        attempt['queue_seconds'] = (attempt['dispatch_authorized_at'] - attempt['started_at']) if attempt.get('dispatch_authorized_at') else None
        attempt['adapter_wall_seconds'] = time.time() - attempt['dispatch_authorized_at'] if attempt.get('dispatch_authorized_at') else None
        # Some providers' usage is missing or malformed. Never turn it into zero.
        for key in ('input_tokens', 'output_tokens'):
            if type(attempt[key]) is not int or attempt[key] < 0:
                attempt[key] = None
        rate = next((v for v in self.policy.rates if v[0] == attempt['backend_id']), None)
        if rate and attempt['kind'] == 'cloud' and all(attempt[k] is not None for k in ('input_tokens', 'output_tokens')):
            attempt['estimated_api_cost_usd'] = (attempt['input_tokens'] * rate[1] + attempt['output_tokens'] * rate[2]) / 1e6
            attempt['cost_source'] = 'host_flat_rate_estimate_not_invoice_or_cache_adjusted_price'
        if (response and error is None and attempt["kind"] == "cloud"
                and response.finish_reason in {None, "stop", "tool_calls"}
                and getattr(self.backend, "service_cache_stable_prefix", False) is True):
            public = self.state.setdefault("cache_public_assistant", {})
            public[sha(response.message.to_dict())] = self._cache_scope()
            while len(public) > 512:
                del public[next(iter(public))]
        if (response and error is None and attempt['kind'] == 'cloud'
                and response.finish_reason in {'stop', 'tool_calls'}
                and getattr(self.backend, 'service_reasoning_replay', False) is True):
            public = self.state.setdefault('deepseek_reasoning_public', {})
            public[sha(response.message.to_dict(include_reasoning=True))] = self._reasoning_scope()
            while len(public) > 512:
                del public[next(iter(public))]
        for field in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
            value = usage.get(field)
            attempt[field] = value if type(value) is int and value >= 0 else None
        hit, miss = attempt["prompt_cache_hit_tokens"], attempt["prompt_cache_miss_tokens"]
        known = hit is not None and miss is not None and hit+miss == attempt["input_tokens"]
        attempt["cache_hit_ratio"] = hit/(hit+miss) if known and hit+miss else None
        attempt["cache_usage_status"] = "PROVIDER_REPORTED" if known else "UNKNOWN"
        self.runtime._emit('HybridModelUsage', usage=deepcopy(attempt))

    def mark_dispatch(self):
        attempt = self.state['attempts'][-1]
        attempt['dispatch_authorized_at'] = time.time()
        self.runtime._emit('HybridModelDispatchAuthorized', attempt_id=attempt['id'], backend_id=attempt['backend_id'])

    def switch(self, alias, reason, scope='session', *, automatic=False, call=None):
        r = self.runtime
        started = time.perf_counter()
        backend = self.check_target(alias)
        if alias == self.state['backend_id'] or r._switches >= r.budgets.max_primary_switches_per_turn:
            raise ValueError('Same backend or switch budget exhausted')
        if recovery_class(r) == 'UNKNOWN_BLOCKED' or r._durable_intent or r.pending_approval:
            raise PersistenceError('Unsafe handoff: unresolved effect or approval')
        if any(c.name != 'request_model_switch' for c in r._queue):
            raise ValueError('Handoff requires drained proposal queue')
        r._effective_thinking(backend)
        from .harness_context import transfer_with_optional_projection
        # Recalculate target admission before committing a route change. This
        # remains a conservative byte estimate, never a tokenizer measurement.
        transfer_with_optional_projection(self.project_messages(r.messages, alias), None if r._finalizing else r._schemas(),
            backend.model_info.effective_context, r.budgets.max_output_tokens * 16,
            working_state=self.contract(backend), final_only=r._finalizing,
            enabled=bool(r.harness_policy and backend.is_local and not r._finalizing))
        if r.adaptive:
            r.adaptive.check_switch(alias)
        before = self.state['backend_id']
        if scope == 'turn':
            self.state['turn_restore'] = before
        self.state['backend_id'] = alias
        self.state['generation'] += 1
        r.primary = self.kind(alias)
        r._switches += 1
        record = {'from_backend_id': before, 'to_backend_id': alias, 'reason': reason,
                  'automatic': automatic, 'at': time.time(), 'contract': self.contract(backend),
                  'task_identity': deepcopy(self.state['task']), 'turn_id': r.turn_id}
        record['proposal'] = {'turn_id': r.turn_id, 'call_id': call.id, 'signature': r._signature(call)} if call else None
        record['runtime_overhead_seconds'] = time.perf_counter() - started
        self.state['handoffs'].append(record)
        r._emit('ModelHandoffCommitted', from_backend_id=before, to_backend_id=alias,
                generation=self.state['generation'], reason=reason, automatic=automatic,
                contract_sha256=sha(record['contract']), runtime_overhead_seconds=record['runtime_overhead_seconds'])
        r._persist('model_handoff', 'ready')

    def fallback(self, error, streamed):
        from .retry import is_transient_error
        r = self.runtime
        if not self.policy.automatic_failover or streamed or getattr(error, 'response', None) is not None:
            return False
        if not (is_transient_error(error) or isinstance(error, CloudEgressDenied)
                and not isinstance(error, CloudEgressApprovalNeeded)):
            return False
        candidates = self.candidates()
        target_kind = 'cloud' if self.backend.is_local else 'local'
        alias = next((c['backend_id'] for c in candidates if c['kind'] == target_kind and c['eligible']), None)
        if alias is None:
            return False
        try:
            self.switch(alias, 'transient_backend_failure' if is_transient_error(error) else 'cloud_egress_rejected', automatic=True)
        except (ValueError, PermissionError, PersistenceError):
            return False
        return True

    def candidates(self):
        """Deterministic shadow eligibility; never trusts a recommender to authorize."""
        result = []
        for alias, backend in self.catalog.items():
            reason = None
            try:
                self.check_target(alias)
                if not backend.capabilities.supports_tool_calling and not self.runtime._finalizing:
                    reason = 'tool_capability'
                elif backend.model_info.effective_context <= self.runtime.budgets.max_output_tokens * 16 + 4096:
                    reason = 'context_budget'
                elif backend.is_local and not backend.health_check():
                    reason = 'unavailable'
            except (ValueError, PermissionError):
                reason = 'data_or_route_policy'
            result.append({'backend_id': alias, 'kind': self.kind(alias), 'eligible': reason is None,
                           'reason': reason, 'source': 'deterministic_shadow_not_recommender_authority'})
        return result

    def restore(self, data):
        if data.get('configuration') != sha(self.configuration()):
            raise PersistenceError('Hybrid checkpoint configuration mismatch')
        state = data.get('state')
        if not isinstance(state, dict) or set(state) != set(self.state) or state['backend_id'] not in self.catalog:
            raise PersistenceError('Invalid hybrid checkpoint state')
        for field in ('cache_public_assistant', 'deepseek_reasoning_public'):
            public = state.get(field, {})
            if (not isinstance(public, dict) or len(public)>512 or any(
                    not isinstance(k, str) or not re.fullmatch(r"[0-9a-f]{64}", k)
                    or not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for k,v in public.items())):
                raise PersistenceError("Invalid cache provenance checkpoint")
        self.state = deepcopy(state)
        if self.runtime.primary != self.kind(self.state['backend_id']):
            raise PersistenceError('Hybrid primary identity mismatch')
        self.check_target(self.state['backend_id'])
        for a in self.state['attempts']:
            if a['status'] == 'inflight':
                a.update(status='process_interrupted', error_type='ProcessInterrupted',
                         latency_seconds=None, input_tokens=None, output_tokens=None)

    def summary(self):
        from .persistence import nodes
        attempts = [a for n in nodes(self.runtime) if n.hybrid for a in n.hybrid.state['attempts']
                    if a['task_identity'] == self.state['task'] and a['turn_id'] == n.turn_id]
        result = {'calls': len(attempts), 'actual_api_cost': 'UNKNOWN', 'local_resource_cost': 'adapter_wall_seconds_only',
                  'backend_id': self.state['backend_id'], 'generation': self.state['generation'],
                  'switching_overhead_seconds': sum(h['runtime_overhead_seconds'] for n in nodes(self.runtime)
                      if n.hybrid for h in n.hybrid.state['handoffs'] if h['task_identity'] == self.state['task']), 'by_backend': {}}
        for alias in sorted({a['backend_id'] for a in attempts}):
            group = [a for a in attempts if a['backend_id'] == alias]
            item = {'kind': group[0]['kind'], 'calls': len(group),
                'known_input_tokens': sum(a['input_tokens'] or 0 for a in group),
                'known_output_tokens': sum(a['output_tokens'] or 0 for a in group),
                'unknown_usage_calls': sum(a['input_tokens'] is None or a['output_tokens'] is None for a in group),
                'known_request_wall_seconds': sum(a['latency_seconds'] or 0 for a in group),
                'known_inference_seconds': sum(a.get('adapter_wall_seconds') or 0 for a in group),
                'known_queue_seconds': sum(a.get('queue_seconds') or 0 for a in group),
                'unknown_inference_time_calls': sum(a.get('adapter_wall_seconds') is None for a in group),
                'unknown_latency_calls': sum(a['latency_seconds'] is None for a in group),
                'estimated_api_cost_usd': sum(a['estimated_api_cost_usd'] for a in group)
                    if all(a['estimated_api_cost_usd'] is not None for a in group) else None,
                'cost_source': 'host_rate_estimate_only', 'configured_models': sorted({a['configured_model'] for a in group})}
            cache_known = all(a.get("cache_usage_status") == "PROVIDER_REPORTED" for a in group)
            item["prompt_cache_hit_tokens"] = sum(a["prompt_cache_hit_tokens"] for a in group) if cache_known else None
            item["prompt_cache_miss_tokens"] = sum(a["prompt_cache_miss_tokens"] for a in group) if cache_known else None
            total = item["known_input_tokens"]
            item["cache_hit_ratio"] = item["prompt_cache_hit_tokens"]/total if cache_known and total else None
            item["cache_usage_unknown_calls"] = sum(a.get("cache_usage_status") != "PROVIDER_REPORTED" for a in group)
            item['wall_output_tokens_per_second'] = item['known_output_tokens'] / item['known_inference_seconds'] if item['known_inference_seconds'] else None
            item['throughput_source'] = 'output_tokens_per_summed_adapter_wall_seconds_including_prefill_not_decode_tps'
            result['by_backend'][alias] = item
        return result
