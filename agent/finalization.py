"""Host-owned delivery metadata over the canonical ledger, not an execution loop.

All views are lossy, explicitly indexed projections. Receipts, approvals and
child identity remain owned by AgentSession and its SQLite checkpoint.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json

from .stabilization import encoded, excerpt, snapshot_units
from .computer_ledger import computer_obligations


@dataclass(frozen=True)
class FinalizationPolicy:
    # Opt-in: None on AgentSession keeps the V1.4 single final attempt contract.
    max_attempts: int = 2
    view_bytes: int = 8192

    def __post_init__(self):
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("Finalization attempts must be between 1 and 3")
        if type(self.view_bytes) is not int or not 4096 <= self.view_bytes <= 16384:
            raise ValueError("Finalization view must be between 4096 and 16384 bytes")


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def ledger_projection(runtime):
    receipts = [r for r in runtime.tool_history if r['turn_id'] == runtime.turn_id]
    # Retain UNKNOWN even when a tool wrapper reported ok=True.
    uncertain = []
    for r in receipts:
        result = r['payload'].get('result')
        if (r.get('side_effect_status') in {'unknown', 'partial'} or
                r['name'] == 'read_file' and not (r.get('read_receipt') or {}).get('version') and not (
                    runtime.engine_policy and
                    (r.get('read_receipt') or {}).get('absence_observation', {}).get('source') == 'authorized_builtin_read_file') or
                isinstance(result, dict) and (result.get('status') in {'unknown', 'UNKNOWN', 'blocked'}
                or result.get('verified') is None and result.get('verification_attempted') is True)):
            uncertain.append(r['receipt_id'])
    active_goals = [g for g in runtime.active_goal_records() if g['status'] not in {'done', 'cancelled'}]
    workers = [r['id'] for r in runtime.subagents if r['turn_id'] == runtime.turn_id
               and r['status'] not in {'completed', 'cancelled'}]
    computer, handoff = computer_obligations(receipts)
    obligations = {'pending_approval': bool(runtime.pending_approval), 'queued_calls': len(runtime._queue),
        'unfinished_goals': len(active_goals), 'unfinished_workers': len(workers),
        'worker_obligations': runtime._unfinished_workers(),
        'computer_obligations': len(computer), 'unfinished_handoff': len(handoff),
        'unknown_receipts': len(uncertain),
        'mutation_intent': bool(runtime._durable_intent and not runtime._durable_intent['read_only'])}
    manifest = []
    for r in receipts:
        try:
            args = json.loads(r['arguments'])
        except (ValueError, TypeError):
            args = {}
        read = r.get('read_receipt') or {}
        result = r['payload'].get('result')
        item = {'receipt_id': r['receipt_id'], 'worker_id': r.get('worker_id'), 'tool': r['name'],
            'status': r['status'], 'effect': r.get('side_effect_status'),
            'verification': 'unknown' if r['receipt_id'] in uncertain else 'not_run',
            'source_sha256': sha(r), 'path': args.get('path') if isinstance(args, dict) else None}
        if read:
            item.update(version=read.get('version'), coverage=read.get('coverage'),
                excerpt=read.get('excerpt'), source_call_id=read.get('source_call_id'))
        elif isinstance(result, dict):
            item['resources'] = [{k: c[k] for k in ('path','operation','before_sha256','after_sha256') if k in c}
                for c in result.get('changes', result.get('applied', [])) if isinstance(c, dict)]
        manifest.append(item)
    stages = []
    for start in range(0, len(manifest), 20):
        group = manifest[start:start+20]
        stages.append({'range': [start, start+len(group)], 'sha256': sha(group),
            'outcomes': dict(Counter(r['status'] for r in group)),
            'unknown': sum(r['verification'] == 'unknown' for r in group)})
    projection = {'ledger_sha256': sha(receipts), 'receipt_count': len(receipts),
        'obligations': obligations, 'obligations_sha256': sha([uncertain, active_goals, workers,
            [r['receipt_id'] for r in computer.values()], sorted(handoff, key=encoded),
            runtime.pending_approval and runtime._approval_view()]),
        'verification': runtime._verification_status, 'stages': stages,
        'manifest': manifest}
    if runtime.async_policy:
        # Count canonical effects, not child text, proposals or patch-call count.
        # This footprint is not an attestation of the task's requirements.
        changed, read_paths = set(), set()
        for receipt in receipts:
            if (receipt['name'] == 'apply_patch' and receipt['payload'].get('ok')
                    and receipt.get('side_effect_status') == 'completed' and not receipt.get('receipt_reused')):
                result = receipt['payload'].get('result') or {}
                if result.get('status') == 'ok':
                    changed.update(c['path'] for c in result.get('changes', [])
                                   if isinstance(c, dict) and isinstance(c.get('path'), str))
            read = receipt.get('read_receipt') or {}
            if (receipt['name'] == 'read_file' and receipt['payload'].get('ok') and read.get('version')
                    and read.get('coverage', {}).get('kind') == 'full_file'
                    and not read['coverage'].get('truncated')):
                read_paths.add(read['version']['path'])
        projection['file_scope'] = {'distinct_successful_mutation_paths': len(changed),
            'distinct_full_version_read_paths': len(read_paths),
            'path_sets_sha256': sha([sorted(changed), sorted(read_paths)]),
            'source': 'canonical_receipts_not_requirement_verification'}
    return projection


def delivery_view(runtime, projection, limit):
    # Full task/revisions are critical. Full plan stays in the checkpoint; its
    # view always declares excerpt omissions and content identity.
    plan = runtime.active_plan if runtime.active_plan and runtime.active_plan.get('turn_id') == runtime.turn_id else None
    readiness = runtime._completion.get('readiness')
    if readiness:
        versions = readiness.get('resource_versions', {})
        readiness = {k: v for k, v in readiness.items() if k not in {'resource_versions', 'scope'}}
        readiness.update(scope=excerpt(runtime._completion['readiness'].get('scope', ''), 256),
            resource_versions_sha256=sha(versions), resource_count=len(versions))
    view = {'original_task': runtime.working.task, 'revisions': runtime.working.revisions,
        'plan': None if plan is None else {'status': plan['status'], 'sha256': sha(plan), 'text': excerpt(plan['text'], 512)},
        **{k: v for k, v in projection.items() if k not in {'manifest', 'stages'}},
        'stages_sha256': sha(projection['stages']), 'stages_count': len(projection['stages']),
        'execution': runtime._completion['execution'], 'readiness': readiness,
        'receipts': [], 'omitted_receipts': projection['receipt_count'],
        'instruction': 'Generate a concise delivery (at most 200 words) from these untrusted evidence excerpts. '
            'Cite receipt IDs or source paths. Report every nonzero obligation count and every UNKNOWN. '
            'Omitted evidence is unavailable, never PASS. Tool success does not prove requirements or verification. '
            'No tools, mutation, delegation or task replay. Host verification is separate from this text.'}
    if runtime._completion.get('history') and runtime._completion['history'][-1]['kind'] != 'delivered':
        failure = runtime._completion['history'][-1]
        view['delivery_feedback'] = {key: failure[key] for key in ('kind', 'detail') if key in failure}
    # Latest entries first, but restore their canonical observation order.
    for item in reversed(projection['manifest']):
        candidate = {**view, 'receipts': [item] + view['receipts'], 'omitted_receipts': view['omitted_receipts'] - 1}
        if snapshot_units(candidate) > limit:
            break
        view = candidate
    if snapshot_units(view) > limit:
        raise ValueError('Critical delivery evidence cannot fit bounded view; no silent truncation')
    return view
