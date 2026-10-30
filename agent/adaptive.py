"""Deterministic, host-owned routing. Recommendations never grant authority.

No prompt/answer inspection, training, network probes, or tool execution here.
Profiles are frozen training observations; evaluation outcomes cannot update them.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import time

from .hybrid import sha, CloudEgressDenied

CATEGORIES = ('file', 'multifile', 'bugfix', 'planning', 'review', 'parallel',
              'long', 'handoff', 'tool_recovery', 'persistence')
STRATEGIES = ('single-model', 'local-first', 'cloud-planning', 'cloud-review', 'parallel-specialist')


def wilson(success, total):
    if not total:
        return [0.0, 1.0]
    z = 1.96
    p = success / total
    d = 1 + z*z/total
    center = (p + z*z/(2*total))/d
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/d
    return [max(0, center-half), min(1, center+half)]


@dataclass(frozen=True)
class TaskTraits:
    category: str = 'file'
    complexity: int = 1
    context_units: int = 16000  # conservative bytes, not measured tokens
    requires_tools: bool = True
    independent_children: int = 0
    review_required: bool = False
    deadline_seconds: float = 300

    def __post_init__(self):
        if self.category not in CATEGORIES:
            raise ValueError('Unsupported task category')
        for key in ('complexity', 'context_units', 'independent_children'):
            if type(getattr(self, key)) is not int:
                raise ValueError('Task traits require integer limits')
        if not 1 <= self.complexity <= 3 or self.context_units < 1 or not 0 <= self.independent_children <= 8:
            raise ValueError('Task traits outside bounded scope')
        if any(type(v) is not bool for v in (self.requires_tools, self.review_required)):
            raise ValueError('Task flags must be booleans')
        if type(self.deadline_seconds) not in (int, float) or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0:
            raise ValueError('Invalid task deadline estimate')


@dataclass(frozen=True)
class AdaptivePolicy:
    mode: str = 'shadow'
    allowed_categories: tuple = ()
    max_cloud_cost_usd: float = .05
    max_model_switches: int = 1  # whole parent/child tree, per turn
    max_child_concurrency: int = 2
    model_lock: str | None = None
    minimum_samples: int = 2
    # Conservative host rates, per million tokens; not billing attestation.
    input_rate_upper: float = .3
    output_rate_upper: float = 1.2

    def __post_init__(self):
        if self.mode not in {'shadow', 'automatic'} or not isinstance(self.allowed_categories, tuple) or set(self.allowed_categories)-set(CATEGORIES):
            raise ValueError('Invalid adaptive mode/scope')
        for key in ('max_cloud_cost_usd', 'input_rate_upper', 'output_rate_upper'):
            v = getattr(self, key)
            if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
                raise ValueError('Invalid finite cost ceiling/rate')
        for key in ('max_model_switches', 'max_child_concurrency', 'minimum_samples'):
            if type(getattr(self, key)) is not int or getattr(self, key) < (0 if key == 'max_model_switches' else 1):
                raise ValueError('Invalid adaptive resource limit')
        if self.model_lock is not None and (not isinstance(self.model_lock, str) or not self.model_lock):
            raise ValueError('Invalid explicit model lock')


def rank(traits, candidates, policy, *, current, local_only=False, route_policy='balanced',
         remaining_units=16000000, remaining_cloud_usd=None, switches=0):
    """Pure selection; a rejection list and uncertainty accompany every choice."""
    rows = []
    for c in candidates:
        reasons = []
        kind = c['kind']
        if kind == 'cloud' and (local_only or route_policy == 'local-only'):
            reasons.append('privacy_or_cloud_egress')
        if kind == 'local' and route_policy == 'cloud-only':
            reasons.append('host_cloud_only')
        if policy.model_lock and c['id'] != policy.model_lock:
            reasons.append('explicit_model_lock')
        if not c['available']:
            reasons.append('unavailable')
        if traits.requires_tools and not c['tool_calling']:
            reasons.append('tool_capability')
        if c['context_units'] < traits.context_units:
            reasons.append('context_window')
        if traits.context_units > remaining_units:
            reasons.append('resource_budget')
        estimated_cost = c.get('estimated_task_cost_usd')
        if kind == 'cloud' and (estimated_cost is None or estimated_cost > (policy.max_cloud_cost_usd if remaining_cloud_usd is None else remaining_cloud_usd)):
            reasons.append('cloud_cost_budget_or_unknown_estimate')
        if switches >= policy.max_model_switches and c['id'] != current and switches:
            reasons.append('handoff_limit')
        n, s = c.get('samples', 0), c.get('successes', 0)
        interval = wilson(s, n)
        observed_latency = c.get('latency_seconds')
        complexity_factor = 1 + .25*(traits.complexity-1)
        latency = observed_latency*complexity_factor if observed_latency is not None else None
        rows.append({**c, 'rejected': reasons, 'success_interval_95': interval,
                     'quality_evidence': 'MEASURED_UNCERTAIN' if n else 'NOT_VERIFIED',
                     'latency_prediction': latency, 'latency_provenance': 'training_median_times_unvalidated_complexity_heuristic' if latency else 'UNKNOWN',
                     'complexity_factor': complexity_factor,
                     'handoff_penalty_seconds': c.get('handoff_seconds', 0) if c['id'] != current else 0})
    eligible = [r for r in rows if not r['rejected']]
    if not eligible:
        return {'mode': None, 'strategy': 'single-model', 'selected': None, 'child_backend': None,
                'reason': 'no_eligible_candidate', 'candidates': rows, 'quality_superiority': 'UNKNOWN'}
    # Only nonoverlapping intervals with adequate samples establish a quality preference.
    supported = [r for r in eligible if r['samples'] >= policy.minimum_samples]
    dominant = [r for r in supported if len(eligible) > 1 and all(r is q or r['success_interval_95'][0] > q['success_interval_95'][1] for q in eligible)]
    qualified = [r for r in eligible if r['samples'] >= policy.minimum_samples and r['successes'] > 0]
    if qualified:
        for r in eligible:
            if r['samples'] >= policy.minimum_samples and r['successes'] == 0:
                r['rejected'].append('no_verified_delivery_in_training_under_current_configuration')
        eligible = [r for r in eligible if not r['rejected']]
    timely = [r for r in eligible if r['latency_prediction'] is not None and
              r['latency_prediction'] + r['handoff_penalty_seconds'] <= traits.deadline_seconds]
    pool = dominant or timely or eligible
    # No prior "cloud is smarter" score. Prefer measured lower cost; thin data
    # retains the fixed backend unless a host limit excludes it.
    measured = [r for r in pool if r['samples'] >= policy.minimum_samples]
    pool = measured or [r for r in pool if r['id'] == current] or pool
    selected = min(pool, key=lambda r: (r.get('estimated_task_cost_usd') if r.get('estimated_task_cost_usd') is not None else math.inf,
                                       r['handoff_penalty_seconds'], r['latency_prediction'] or math.inf, r['id']))
    strategy, mode, child = 'single-model', selected['kind'].upper(), selected['id']
    local = next((r for r in eligible if r['kind']=='local'), None)
    cloud = next((r for r in eligible if r['kind']=='cloud'), None)
    if local and cloud and traits.review_required:
        strategy, mode, child, selected = 'cloud-review', 'HYBRID', local['id'], cloud
    elif local and cloud and traits.independent_children > 1:
        strategy, mode, child = 'parallel-specialist', 'HYBRID', local['id']
    elif local and cloud and selected['kind']=='cloud' and traits.independent_children==1 and traits.category in {'planning', 'multifile', 'long'}:
        strategy, mode, child = 'cloud-planning', 'HYBRID', local['id']
    elif selected['kind']=='local':
        strategy = 'local-first'
    return {'mode': mode, 'strategy': strategy, 'selected': selected['id'], 'child_backend': child,
            'reason': 'separated_quality_intervals' if dominant else 'cost_latency_and_coordination_under_uncertain_quality',
            'candidates': rows, 'quality_superiority': 'SUPPORTED_SCOPED' if any(r['id']==selected['id'] for r in dominant) else 'UNKNOWN'}


def active_nodes(runtime):
    """Only the current durable task tree; historical children keep evidence."""
    yield runtime
    current = {r['id'] for r in runtime.subagents if r['turn_id']==runtime.turn_id}
    for worker_id, child in runtime._children.items():
        if worker_id in current:
            yield from active_nodes(child)


class AdaptiveController:
    def __init__(self, runtime, policy, profiles, traits):
        if not isinstance(policy, AdaptivePolicy) or not isinstance(traits, TaskTraits) or not isinstance(profiles, dict):
            raise TypeError('Adaptive routing requires typed host policy/traits and frozen profiles')
        if not runtime.hybrid:
            raise ValueError('Adaptive routing requires existing HybridController')
        if profiles.get('version') != 1 or set(profiles)-{'version', 'models', 'training_binding', 'limits'}:
            raise ValueError('Invalid capability profile')
        if policy.model_lock is not None and policy.model_lock not in runtime.hybrid.catalog:
            raise ValueError('Explicit model lock is not registered')
        if not isinstance(profiles.get('models'), dict):
            raise ValueError('Profile models must be a mapping')
        for alias, profile in profiles['models'].items():
            if alias not in runtime.hybrid.catalog or not isinstance(profile, dict) or type(profile.get('available')) is not bool:
                raise ValueError('Profile requires registered identity and boolean availability')
            for category, measured in profile.get('categories', {}).items():
                n, successes = measured.get('samples'), measured.get('successes')
                if category not in CATEGORIES or type(n) is not int or type(successes) is not int or not 0 <= successes <= n:
                    raise ValueError('Invalid measured sample counts')
                for key in ('median_e2e_seconds', 'median_cloud_cost_usd'):
                    v = measured.get(key)
                    if v is not None and (type(v) not in (int, float) or not math.isfinite(v) or v < 0):
                        raise ValueError('Invalid measured profile metric')
        self.runtime, self.policy, self.profiles, self.traits = runtime, policy, deepcopy(profiles), traits
        self.state = {'decisions': [], 'cloud_reservations': [], 'turn': 0}

    def configuration(self):
        return {'version': 1, 'policy': asdict(self.policy), 'profile_sha256': sha(self.profiles), 'traits': asdict(self.traits)}

    def root(self):
        r = self.runtime
        while r._ledger_parent:
            r = r._ledger_parent
        return r

    def spent(self):
        return sum(x['upper_estimate_usd'] for x in self.root().adaptive.state['cloud_reservations'] if x['turn']==self.root().turn_id)

    def candidates(self, traits):
        result = []
        for alias, b in self.runtime.hybrid.catalog.items():
            p = self.profiles.get('models', {}).get(alias, {})
            m = p.get('categories', {}).get(traits.category, {})
            identity_matches = sha(p.get('identity')) == sha(self.runtime.hybrid.configuration()['catalog'][alias])
            if not identity_matches:
                m = {}  # Never transfer measured quality across changed models/adapters.
            info = b.model_info
            result.append({'id': alias, 'kind': self.runtime.hybrid.kind(alias),
                'available': p.get('available', False), 'tool_calling': b.capabilities.supports_tool_calling,
                'context_units': info.effective_context, 'samples': m.get('samples', 0), 'successes': m.get('successes', 0),
                'latency_seconds': m.get('median_e2e_seconds'), 'handoff_seconds': p.get('handoff_seconds', 0),
                'estimated_task_cost_usd': 0 if b.is_local else m.get('median_cloud_cost_usd', .01),
                'identity_matches_measurement': identity_matches})
        return result

    def decide(self, scope='task', call_id=None, current=None, locked=None):
        r = self.runtime
        key = {'turn': r.turn_id, 'worker': r._worker_id, 'scope': scope, 'call_id': call_id}
        prior = next((d for d in self.state['decisions'] if d['key']==key), None)
        if prior:
            return prior  # Approval/resume uses the original decision, not fresh ranking.
        traits = self.traits
        if scope == 'child':
            traits = TaskTraits(traits.category, traits.complexity, min(traits.context_units, 32000), traits.requires_tools,
                                0, False, traits.deadline_seconds)
        from dataclasses import replace
        policy = replace(self.policy, model_lock=self.policy.model_lock or locked)
        root = self.root()
        switches = sum(n._switches for n in active_nodes(root))
        decision = rank(traits, self.candidates(traits), policy, current=current or r.hybrid.state['backend_id'],
            local_only=r.hard_data_policy.local_only or r.hybrid.policy.egress.mode=='LOCAL_ONLY',
            route_policy=r.routing_policy.value, remaining_units=r.budgets.max_token_units-r._token_units,
            remaining_cloud_usd=max(0,self.policy.max_cloud_cost_usd-self.spent()), switches=switches)
        if self.policy.model_lock and locked and locked != self.policy.model_lock:
            decision.update(selected=None, child_backend=None, mode=None, reason='proposal_conflicts_with_host_model_lock')
        decision.update(key=key, profile_sha256=sha(self.profiles), traits_sha256=sha(asdict(traits)),
                        mode_config=self.policy.mode, applied=False, at=time.time())
        self.state['decisions'].append(decision)
        r._emit('AdaptiveRouteDecision', decision=deepcopy(decision))
        return decision

    def enabled(self):
        return self.policy.mode=='automatic' and self.traits.category in self.policy.allowed_categories

    def start_turn(self):
        d = self.decide()
        r = self.runtime
        if self.enabled() and not d['selected']:
            raise CloudEgressDenied('Adaptive routing has no eligible candidate; fixed fallback cannot override hard gates')
        if self.enabled() and d['selected']:
            # Before the first inference/effect. This chooses an initial backend,
            # does not continue or replay a previous task and grants no approval.
            r.hybrid.check_target(d['selected'])
            r.hybrid.state['backend_id'] = d['selected']
            r.primary = r.hybrid.kind(d['selected'])
            d['applied'] = True
            r._emit('AdaptiveRouteApplied', scope='task', backend_id=d['selected'], strategy=d['strategy'])
        return d

    def check_switch(self, alias):
        if not self.enabled():
            return
        root = self.root()
        if self.policy.model_lock and alias != self.policy.model_lock:
            raise CloudEgressDenied('Adaptive explicit model lock')
        if sum(n._switches for n in active_nodes(root)) >= self.policy.max_model_switches:
            raise CloudEgressDenied('Adaptive tree model switch ceiling')

    def reserve_cloud(self, request_units, output_tokens):
        if not self.enabled():
            return
        upper = (request_units*self.policy.input_rate_upper + output_tokens*self.policy.output_rate_upper)/1e6
        root = self.root()
        # Session serialization uses the shared parent/child condition. Unknown
        # usage retains the full reservation, including across process restart.
        if self.spent()+upper > self.policy.max_cloud_cost_usd+1e-12:
            raise CloudEgressDenied('Adaptive conservative cloud cost ceiling')
        root.adaptive.state['cloud_reservations'].append({'turn':root.turn_id,'worker':self.runtime._worker_id,
            'upper_estimate_usd':upper,'request_units':request_units,'output_token_ceiling':output_tokens,
            'source':'host_rate_upper_and_utf8_admission; not_invoice', 'at':time.time()})
        self.runtime._emit('AdaptiveCloudBudgetReserved', upper_estimate_usd=upper, total_reserved_usd=self.spent())

    def summary(self):
        current = [d for d in self.state['decisions'] if d['key']['turn']==self.runtime.turn_id]
        return {'version': 1, 'mode': self.policy.mode, 'automatic_scope_enabled': self.enabled(),
                'profile_sha256': sha(self.profiles), 'decisions': deepcopy(current[-32:]),
                'omitted_decisions': max(0, len(current)-32),
                'cloud_reserved_upper_estimate_usd': self.spent(),
                'cloud_estimate_ceiling_usd': self.policy.max_cloud_cost_usd,
                'invoice': 'UNKNOWN', 'authority': 'routing never grants tool, egress or verification authority'}

    def restore(self, data):
        from .persistence import PersistenceError
        if data['configuration'] != sha(self.configuration()):
            raise PersistenceError('Adaptive configuration/profile checkpoint mismatch')
        self.state = deepcopy(data['state'])
