"""Opt-in step routing over the existing HybridController and receipt ledger.

Frozen development profiles calibrate task buckets. Model self-confidence is
never input. All switches use HybridController's existing admission checks.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import math

from .adaptive import wilson
from .context import context_units
from .hybrid import sha
from .routing import parse_policy


@dataclass(frozen=True)
class CooperativePolicy:
    mode: str = 'balanced'
    max_local_requests: int = 2
    max_stagnation: int = 2
    max_tool_errors: int = 1
    minimum_samples: int = 20
    quality_floor: float = .95
    max_local_queue_seconds: float = 10
    # Ablations are frozen in the configuration/recovery fingerprint.
    use_calibration: bool = True
    use_failure_escalation: bool = True
    use_queue_prediction: bool = True
    use_token_budget: bool = True

    def __post_init__(self):
        parse_policy(self.mode)
        for key in ('max_local_requests', 'max_stagnation', 'max_tool_errors', 'minimum_samples'):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError('Cooperative request/history limits must be positive integers')
        for key in ('quality_floor', 'max_local_queue_seconds'):
            v = getattr(self, key)
            if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
                raise ValueError('Cooperative prediction limits must be finite')
        if self.quality_floor > 1:
            raise ValueError('quality_floor exceeds one')
        for key in ('use_calibration', 'use_failure_escalation', 'use_queue_prediction', 'use_token_budget'):
            if type(getattr(self, key)) is not bool:
                raise ValueError('Ablation flags must be booleans')


def task_bucket(task):
    """Cheap declared heuristic, no extra routing-model inference or answer data."""
    text = task.lower()
    complex_terms = ('debug', 'refactor', 'repository', 'implement', '多文件', '调试', '重构')
    return 'complex' if len(task.encode()) > 4000 or any(w in text for w in complex_terms) else 'simple'


def decide(policy, *, current, local_requests, tool_errors, stagnation,
           context_bytes, local_context, bucket, profile, escalated=False,
           cloud_allowed=True, local_queue_seconds=None, verification_failed=False):
    """Return a single target and a reason; never invokes both providers."""
    mode = parse_policy(policy.mode).value
    def result(target, reason, **extra):
        return {'target': target, 'reason': reason, 'bucket': bucket,
                'quality_evidence': 'UNKNOWN', **extra}
    if mode == 'local-only': return result('local', 'host_local_only')
    if mode == 'cloud-only': return result('cloud', 'host_cloud_only')
    if not cloud_allowed: return result('local', 'cloud_egress_closed')
    # One-way hysteresis: never oscillate back to local within the task.
    if escalated or current == 'cloud' and local_requests:
        return result('cloud', 'route_hysteresis')
    if policy.use_token_budget and context_bytes > local_context:
        return result('cloud', 'local_context_insufficient')
    if policy.use_failure_escalation and (verification_failed or tool_errors >= policy.max_tool_errors or stagnation >= policy.max_stagnation):
        return result('cloud', 'verification_failed' if verification_failed else 'tool_error' if tool_errors else 'no_progress')
    if local_requests >= policy.max_local_requests:
        return result('cloud', 'local_trial_budget_exhausted')
    if policy.use_queue_prediction and local_queue_seconds is not None and local_queue_seconds > policy.max_local_queue_seconds:
        return result('cloud', 'local_queue_deadline')
    n, s = profile.get('samples', 0), profile.get('successes', 0)
    interval = wilson(s, n)
    calibrated = n >= policy.minimum_samples and interval[0] >= policy.quality_floor
    if mode == 'cloud-first':
        return result('local' if policy.use_calibration and calibrated and bucket == 'simple' else 'cloud',
                      'calibrated_simple_step' if policy.use_calibration and calibrated and bucket == 'simple' else 'cloud_quality_priority',
                      success_interval_95=interval, development_samples=n)
    if mode == 'balanced':
        local = bucket == 'simple' and (calibrated if policy.use_calibration else True)
        # No invented confidence for unseen buckets: retain quality priority.
        return result('local' if local else 'cloud', 'calibrated_cost_choice' if local else 'insufficient_local_quality_evidence',
                      success_interval_95=interval, development_samples=n)
    return result('cloud' if bucket == 'complex' else 'local',
                  'difficulty_early_escalation' if bucket == 'complex' else 'bounded_local_trial')


class CooperativeController:
    def __init__(self, runtime, policy, profiles=None):
        if not isinstance(policy, CooperativePolicy) or not runtime.hybrid or runtime.adaptive:
            raise ValueError('Cooperative routing requires its typed policy and exclusive HybridController')
        if parse_policy(policy.mode) != runtime.routing_policy:
            raise ValueError('Cooperative mode must match the host route policy')
        profiles = deepcopy(profiles or {'split': 'development', 'buckets': {}})
        if set(profiles)-{'split','buckets','backend_identity_sha256'} or not {'split','buckets'} <= set(profiles) or profiles['split'] != 'development' or not isinstance(profiles['buckets'], dict):
            raise ValueError('Only frozen development profiles may calibrate routes')
        if profiles['buckets']:
            from .persistence import backend_identity
            local = next((b for b in runtime.hybrid.catalog.values() if b.is_local), None)
            if local is None or profiles.get('backend_identity_sha256') != sha(backend_identity(local)):
                raise ValueError('Development calibration must bind the exact local backend identity')
        for key, row in profiles['buckets'].items():
            if key not in {'simple', 'complex'} or not isinstance(row, dict) or set(row) != {'samples', 'successes'}:
                raise ValueError('Invalid development bucket')
            if any(type(row[k]) is not int for k in row) or not 0 <= row['successes'] <= row['samples']:
                raise ValueError('Invalid development outcomes')
        self.runtime, self.policy, self.profiles = runtime, policy, profiles
        runtime.hybrid.state['cooperative'] = {'turn_id': 0, 'escalated': False, 'decisions': []}

    def configuration(self):
        return {'policy': asdict(self.policy), 'profiles': self.profiles,
                'revision': 1, 'task_predictor': 'declared_lexical_heuristic_v1'}

    def before_request(self):
        r, h = self.runtime, self.runtime.hybrid
        state = h.state['cooperative']
        if state['turn_id'] != r.turn_id:
            state.update(turn_id=r.turn_id, escalated=False, decisions=[])
        # No switching while proposals, approvals, or uncertain effects remain.
        if r._queue or r.pending_approval or r._durable_intent:
            return
        rows = [a for a in h.state['attempts'] if a.get('turn_id') == r.turn_id]
        local_requests = sum(h.kind(a['backend_id']) == 'local' for a in rows)
        tools = [t for t in r.tool_history if t['turn_id'] == r.turn_id]
        errors = sum(t.get('payload', {}).get('ok') is False for t in tools)
        local_alias = next((a for a, b in h.catalog.items() if b.is_local), None)
        cloud_alias = next((a for a, b in h.catalog.items() if not b.is_local), None)
        local = h.catalog.get(local_alias)
        bucket = task_bucket(r.working.task)
        d = decide(self.policy, current=h.kind(h.state['backend_id']), local_requests=local_requests,
            tool_errors=errors, stagnation=r.working.no_progress,
            context_bytes=context_units(r.messages, r._schemas()) + r.budgets.max_output_tokens * 16 + 8192,
            local_context=local.model_info.effective_context if local else 0, bucket=bucket,
            profile=self.profiles['buckets'].get(bucket, {}), escalated=state['escalated'],
            cloud_allowed=h.policy.egress.mode == 'CLOUD_ALLOWED' and not r.hard_data_policy.local_only,
            local_queue_seconds=getattr(local, 'queue_seconds_estimate', None),
            verification_failed=bool(r._completion and r._completion.get('v5_repairs')))
        target = local_alias if d['target'] == 'local' else cloud_alias
        d.update(turn_id=r.turn_id, step=r._attempts, profile_sha256=sha(self.profiles),
                 backend_id=target, outcome='retained')
        if target is None:
            d['outcome'] = 'target_unavailable'
        elif target != h.state['backend_id']:
            h.switch(target, 'cooperative:' + d['reason'], automatic=True)
            state['escalated'] |= d['target'] == 'cloud' and bool(local_requests)
            d['outcome'] = 'switched'
        state['decisions'].append(d)
        r._emit('CooperativeRouteDecision', **{k:v for k,v in d.items() if k != 'turn_id'})
