"""Opt-in task contracts and bounded feedback over the existing runtime.

No new planner, authority, executor, automatic mutation retry or oracle access.
"""
from dataclasses import asdict, dataclass
import json
from .stabilization import file_version


STRATEGIES=('single-model-direct','local-first-cloud-escalation','cloud-first-local-execution',
            'cloud-review','parallel-specialist','explicit-handoff')


def proposal_identity(name,arguments):
    try:value=json.dumps(json.loads(arguments),sort_keys=True,separators=(',',':'))
    except (ValueError,TypeError):value=arguments
    return name,value


@dataclass(frozen=True)
class HarnessPolicy:
    strategy: str = 'single-model-direct'
    max_completion_repairs: int = 2
    max_invalid_calls: int = 3
    max_identical_invalid_calls: int = 2
    cache_stable_prefix: bool = False

    def __post_init__(self):
        if type(self.cache_stable_prefix) is not bool:raise ValueError('cache_stable_prefix must be a host boolean')
        if self.strategy not in STRATEGIES:raise ValueError('Unknown harness collaboration strategy')
        for name,low,high in [('max_completion_repairs',0,3),('max_invalid_calls',1,4),('max_identical_invalid_calls',1,3)]:
            v=getattr(self,name)
            if type(v) is not int or not low<=v<=high:raise ValueError('Invalid bounded harness budget: '+name)


@dataclass(frozen=True)
class TaskContract:
    input_paths: tuple = ()
    output_paths: tuple = ()
    independent_children: int = 0
    review_required: bool = False
    handoff_required: bool = False
    privacy_local_only: bool = False
    child_output_groups: tuple = ()
    parent_output_paths: tuple = ()
    independent_review_paths: tuple = ()

    def __post_init__(self):
        from pathlib import PurePosixPath
        for field in ('input_paths','output_paths'):
            values=getattr(self,field)
            if type(values) is not tuple or len(values)>128 or len(values)!=len(set(values)):
                raise ValueError('Task paths must be unique bounded tuples')
            for v in values:
                if not isinstance(v,str) or not v or PurePosixPath(v).is_absolute() or '..' in PurePosixPath(v).parts:
                    raise ValueError('Contract paths must stay within workspace')
        if type(self.independent_children) is not int or not 0<=self.independent_children<=4:
            raise ValueError('Invalid independently required child count')
        for f in ('review_required','handoff_required','privacy_local_only'):
            if type(getattr(self,f)) is not bool:raise ValueError('Contract flags must be booleans')
        if type(self.child_output_groups) is not tuple or len(self.child_output_groups)>4:
            raise ValueError('Child output groups must be bounded tuples')
        child_paths=[]
        for group in self.child_output_groups:
            if type(group) is not tuple or not group:raise ValueError('Empty or invalid child output group')
            child_paths.extend(group)
        if len(child_paths)!=len(set(child_paths)) or not set(child_paths)<=set(self.output_paths):
            raise ValueError('Child ownership must be disjoint declared outputs')
        for field in ('parent_output_paths','independent_review_paths'):
            v=getattr(self,field)
            if type(v) is not tuple or len(v)!=len(set(v)) or not set(v)<=set(self.output_paths):
                raise ValueError('Role paths must be unique declared output tuples')
        if set(self.parent_output_paths)&set(child_paths):raise ValueError('Parent and child write ownership overlap')


def decision(policy,contract):
    c=contract or TaskContract()
    if c.independent_children>1:mode,reason='PARALLEL_SUBTASKS','Public task explicitly requires independent, disjoint child roles'
    elif c.review_required:mode,reason='SEQUENTIAL_SUBTASKS','Independent implementation/review is an explicit task obligation'
    elif c.handoff_required:mode,reason='MODEL_ESCALATION','Explicit model handoff retains stage ownership and prior receipts'
    elif c.child_output_groups:mode,reason='SEQUENTIAL_SUBTASKS','An independently owned child stage is required on the permitted model'
    elif c.privacy_local_only:mode,reason='NO_DELEGATION','Local privacy contract; direct work avoids extra disclosure'
    else:mode,reason='DIRECT_EXECUTION','No independently required collaborator; sequential steps stay in the primary context'
    return {'mode':mode,'strategy':policy.strategy,'reason':reason,
        'fallback':'Single-model direct execution only when public role obligations permit and host permissions/egress/budgets allow; never replay mutation'}


def prompt(policy,contract):
    return '\nHOST HARNESS CONTRACT (data, not evidence): '+json.dumps({
        'decision':decision(policy,contract),'contract':asdict(contract or TaskContract()),
        'execution_rules':'Use the fewest necessary steps. Do not create goals for a simple task. For complex tasks, each goal needs an explicit evidence-based completion. Child contracts contain input/output paths, constraints and acceptance conditions, never guessed answers. Child budget.tokens is cumulative host UTF-8 admission units, NOT provider tokens; it must cover complete prompts, tool schemas, handoff and all output allowances. Prefer omitting budget.tokens to use the existing bounded host worker ceiling. Never switch to an unregistered model; a single-model catalog means no cross-model handoff is available. For an output that may not exist yet, use a permitted metadata tool (file_info or a complete untruncated list_directory) before attempting read_file. An absence observation is not a content read or task verification. Read current changed versions after each final mutation. Never use an old call ID for fresh observations. After collecting Children, complete every original Parent-owned stage and parent_output_paths before final delivery. Child completion never substitutes for remaining Parent deliverables. Stop once all requested outputs, roles, receipts, goals and reads are satisfied. Tool errors with not_dispatched/action_sent=false/action_may_have_applied=false permit bounded correction with a fresh ID. Dispatched uncertain mutation never permits replay. Model/child/tool success alone does not satisfy the task.'},sort_keys=True)


def file_evidence(runtime):
    """Current generation, post-last-effect, full version reads for declared outputs."""
    contract=runtime.task_contract
    if not contract:return {'versions':{},'failures':[]}
    history=[r for r in runtime.tool_history if r['turn_id']==runtime.turn_id]
    versions={};failures=[]
    for path in contract.output_paths:
        try:v=file_version(runtime.workspace,path)
        except (OSError,ValueError):v=None
        if not v:failures.append({'path':path,'reason':'current_version_unknown'});continue
        versions[path]=v['sha256'];last=-1;effect=None
        for i,r in enumerate(history):
            if r['name']=='apply_patch' and r.get('side_effect_status')=='completed' and not r.get('receipt_reused'):
                for c in (r['payload'].get('result') or {}).get('changes',[]):
                    if c.get('path')==path:last,effect=i,c.get('after_sha256')
        if last<0 or effect!=v['sha256']:
            failures.append({'path':path,'reason':'current_version_not_bound_to_effect_receipt'});continue
        reads=[r for r in history[last+1:] if r['name']=='read_file' and r['payload'].get('ok')
            and not (r.get('read_receipt') or {}).get('identity_reuse')
            and (r.get('read_receipt') or {}).get('version')==v
            and (r.get('read_receipt') or {}).get('coverage',{}).get('kind')=='full_file'
            and not (r.get('read_receipt') or {}).get('coverage',{}).get('truncated')]
        if not reads:failures.append({'path':path,'reason':'missing_current_full_read_after_last_mutation'})
    failures.extend(role_failures(runtime,history,versions))
    return {'versions':versions,'failures':failures,'turn_id':runtime.turn_id,
        'generation':runtime.hybrid.state['generation'] if runtime.hybrid else runtime.turn_id,
        'scope':'file effect/observation causality only; semantic host verification remains required'}


def role_failures(runtime,history,versions):
    c=runtime.task_contract;failures=[]
    patches=[(i,r,ch) for i,r in enumerate(history) if r['name']=='apply_patch' and r.get('side_effect_status')=='completed'
        and not r.get('receipt_reused') for ch in (r['payload'].get('result') or {}).get('changes',[])]
    children=[v for v in runtime.subagents if v['turn_id']==runtime.turn_id]
    ownership={}
    for i,r,ch in patches:ownership.setdefault(ch['path'],set()).add(r.get('worker_id'))
    if c.child_output_groups:
        owners=[]
        for group in c.child_output_groups:
            ids=set().union(*(ownership.get(p,set()) for p in group))
            if len(ids)!=1 or None in ids or any(ownership.get(p)!=ids for p in group):
                failures.append({'paths':list(group),'reason':'child_output_ownership_unproved','repairable_by_observation':False})
            else:owners.extend(ids)
        if (len(children)!=len(c.child_output_groups) or len(owners)!=len(set(owners))
                or set(owners)!={v['id'] for v in children}
                or any(v['status']!='completed' or v.get('read_only',True) for v in children)):
            failures.append({'reason':'independent_child_roles_unproved','repairable_by_observation':False})
    if any(ownership.get(p)!={None} for p in c.parent_output_paths):
        failures.append({'paths':list(c.parent_output_paths),'reason':'parent_output_ownership_unproved','repairable_by_observation':False})
    for p in c.independent_review_paths:
        changes=[(i,r,ch) for i,r,ch in patches if ch['path']==p]
        if not changes or any(r.get('worker_id') is None for _,r,_ in changes):
            failures.append({'path':p,'reason':'independent_review_effect_unproved','repairable_by_observation':False});continue
        first,last=changes[0],changes[-1]
        reads=[(i,(r.get('read_receipt') or {}).get('version') or {}) for i,r in enumerate(history) if r['name']=='read_file'
            and r['payload'].get('ok') and r.get('worker_id') is None and not (r.get('read_receipt') or {}).get('identity_reuse')
            and (r.get('read_receipt') or {}).get('coverage',{}).get('kind')=='full_file'
            and not (r.get('read_receipt') or {}).get('coverage',{}).get('truncated')]
        if not any(i<first[0] and v.get('path')==p and v.get('sha256')==first[2].get('before_sha256') for i,v in reads):
            failures.append({'path':p,'reason':'parent_pre_review_version_unproved','repairable_by_observation':False})
        if not any(i>last[0] and v.get('path')==p and v.get('sha256')==versions.get(p) for i,v in reads):
            failures.append({'path':p,'reason':'parent_post_review_read_missing','repairable_by_observation':True})
    if c.handoff_required and runtime.hybrid:
        kinds={runtime.hybrid.kind(alias) for alias in runtime.hybrid.catalog}
        if runtime.hybrid.policy.egress.mode=='LOCAL_ONLY':kinds.discard('cloud')
        if len(kinds)>1 and not runtime._switches:
            failures.append({'reason':'explicit_model_handoff_unproved','repairable_by_observation':False})
    return failures


def repair_feedback(runtime):
    if not runtime.harness_policy or runtime._finalizing or not runtime._completion:return None
    from .finalization import ledger_projection
    ob=ledger_projection(runtime)['obligations']
    # Only safe observation/goal work. Never resume a failed/unknown worker or mutation.
    if any(v for k,v in ob.items() if k!='unfinished_goals'):return None
    evidence=file_evidence(runtime)
    if any(f.get('repairable_by_observation') is False for f in evidence['failures']):return None
    goals=[{'id':g['id'],'status':g['status'],'subgoals':g['subgoals']} for g in runtime.active_goal_records() if g['status'] not in {'done','cancelled'}]
    if not goals and not evidence['failures']:return None
    used=runtime._completion.get('harness_repairs',0)
    if used>=runtime.harness_policy.max_completion_repairs:return None
    runtime._completion['harness_repairs']=used+1
    return {'attempt':used+1,'unfinished_goals':goals,'file_evidence':evidence,
        'instruction':'Premature final withheld. Obtain fresh read_file observations for listed outputs; explicitly complete goals only if their requirements are satisfied by actual evidence. Do not repeat mutations, fabricate evidence or cancel obligations to force success. Then return the requested final format.'}
