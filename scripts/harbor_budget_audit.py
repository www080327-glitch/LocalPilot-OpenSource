"""Qualification of a paired experiment, separate from its observed rewards."""
from hashlib import sha256
import json

from scripts.harbor_orchestration import arm_orchestration, validate_orchestration_evidence


LIMIT_DEFAULTS = {'max_requests':24, 'max_input_tokens':32768, 'max_output_tokens':1024,
                  'max_total_tokens':500000, 'min_available_bytes':8 * 1024**3, 'tokenizer_timeout':30}
MEASURED_ADAPTERS = {'scripts.localpilot_harbor:LocalPilotHarborAgent',
                     'scripts.harbor_reference:BudgetedTerminusAgent'}


def normalized_limits(value):
    if not isinstance(value,dict):
        raise ValueError('Registered model budget must be an object')
    limits = {**LIMIT_DEFAULTS, **value}
    for name in LIMIT_DEFAULTS:
        if type(limits[name]) is not int or limits[name] <= 0:
            raise ValueError('Invalid registered model budget: ' + name)
    for name in ('tokenizer_path', 'tokenizer_python'):
        if not isinstance(limits.get(name), str) or not limits[name]:
            raise ValueError('Missing registered tokenizer input: ' + name)
    return limits


def comparison_configuration(spec):
    arms = {arm['id']:arm for arm in spec['arms']}
    selected = [arms[spec['comparison'][side]] for side in ('candidate','baseline')]
    candidate, baseline = [arm['agent'] for arm in selected]
    reasons = []
    orchestration = {}
    for side, agent in zip(('candidate','baseline'), (candidate,baseline)):
        try:
            orchestration[side] = arm_orchestration(agent)
        except ValueError as exc:
            reasons.append(str(exc))
    if candidate['model_name'] != baseline['model_name']:
        reasons.append('Different configured models')
    if spec['purpose'] == 'smoke':
        return {'qualified':not reasons, 'scope':'SMOKE_ONLY', 'reasons':reasons, 'orchestration':orchestration}
    options = [agent.get('kwargs',{}) for agent in (candidate,baseline)]
    if any(agent.get('import_path') not in MEASURED_ADAPTERS for agent in (candidate,baseline)):
        reasons.append('Both arms must use a reviewed adapter with the measured model transport')
    budgets = []
    for option in options:
        try:
            budgets.append(normalized_limits(option.get('model_budget',{})))
        except (TypeError,ValueError) as exc:
            reasons.append(str(exc))
    if len(budgets) == 2 and budgets[0] != budgets[1]:
        reasons.append('Different model request/token/tokenizer budgets')
    if options[0].get('endpoint') != options[1].get('endpoint') or not options[0].get('endpoint'):
        reasons.append('Different or missing model endpoints')
    if any(option.get('provider_kind','local-openai') != 'local-openai' for option in options):
        reasons.append('Cloud transport has not qualified measured tokenizer budgets')
    if options[0].get('model_timeout',120) != options[1].get('model_timeout',120):
        reasons.append('Different model request timeouts')
    if candidate.get('override_timeout_sec') != baseline.get('override_timeout_sec') or candidate.get('max_timeout_sec') != baseline.get('max_timeout_sec'):
        reasons.append('Different agent task timeout overrides')
    for agent, option in zip((candidate,baseline),options):
        if agent.get('import_path') == 'scripts.localpilot_harbor:LocalPilotHarborAgent' and option.get('chat_template_kwargs') != {'enable_thinking':False}:
            reasons.append('LocalPilot thinking/template configuration differs from the measured reference')
    identity = spec.get('model_identity',{})
    if not isinstance(identity,dict) or identity.get('model_name') != candidate['model_name'] or any(
            not isinstance(identity.get(name),str) or not identity[name] for name in ('revision','quantization','tokenizer_sha256')):
        reasons.append('Missing frozen model revision, quantization, or tokenizer identity')
    if spec['execution']['n_concurrent_trials'] != 1:
        reasons.append('The measured local comparison requires sequential trials')
    return {'qualified':not reasons, 'scope':'MATCHED_MODEL_AND_MEASURED_BUDGET', 'reasons':reasons,
            'orchestration':orchestration,
            'comparison_limit':'Harness comparison under one model and total model budget; tool protocols and child scheduling may differ. This is not a multi-model or hardware-cost equivalence claim.',
            'model_identity':identity, 'identity_limit':'Frozen declarations and tokenizer evidence do not independently certify model weights'}


def audit_budget_log(trial_path, raw, arm, model_identity):
    path = trial_path.parent / 'agent' / 'model-budget.jsonl'
    if not path.exists():
        started = (raw.get('agent_execution') or {}).get('started_at')
        return {'qualified':not started, 'status':'MISSING' if started else 'AGENT_NOT_STARTED',
                'requests':None if started else 0, 'issues':['Model budget ledger is missing'] if started else []}
    data = path.read_bytes()
    evidence = {'path':path.relative_to(trial_path.parent).as_posix(), 'sha256':sha256(data).hexdigest()}
    try:
        if not isinstance(model_identity,dict):
            raise ValueError('Frozen model identity must be an object')
        rows = [json.loads(line) for line in data.splitlines() if line.strip()]
        expected = normalized_limits(arm['agent'].get('kwargs',{}).get('model_budget',{}))
        result = _reconcile_budget(rows, expected, arm['agent']['model_name'], model_identity)
        contract = arm_orchestration(arm['agent'])
        if contract['mode'] == 'multi-agent':
            orchestration_path = path.with_name('localpilot-orchestration.json')
            data = orchestration_path.read_bytes()
            result['orchestration'] = validate_orchestration_evidence(json.loads(data), contract, result, arm['agent']['model_name'])
            result['orchestration_source'] = {'path':orchestration_path.relative_to(trial_path.parent).as_posix(),
                                              'sha256':sha256(data).hexdigest()}
    except (OSError,ValueError,TypeError,KeyError) as exc:
        result = {'qualified':False, 'status':'UNQUALIFIED', 'issues':[str(exc)]}
    return {**result, 'source':evidence}


def _integer(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(label + ' must be a nonnegative integer')
    return value


def _reconcile_budget(rows, expected, model, identity):
    if not rows or not isinstance(rows[0],dict) or rows[0].get('status') != 'budget_initialized':
        raise ValueError('No pre-dispatch budget initialization record; legacy settlement-only logs remain unqualified')
    first = rows[0]
    if normalized_limits(first['limits']) != expected or first.get('model') != model:
        raise ValueError('Budget initialization differs from the frozen model/configuration')
    if first.get('tokenizer_sha256') != identity.get('tokenizer_sha256'):
        raise ValueError('Actual tokenizer/template files differ from the frozen identity')
    requests, charged, inputs, outputs, denials, pending = 0, 0, 0, 0, 0, None
    for row in rows[1:]:
        if not isinstance(row,dict):
            raise ValueError('Invalid model budget record')
        if row.get('status') == 'denied_before_dispatch':
            if (first.get('admission_denials') is not True or pending is not None
                    or row.get('request') != requests + 1 or row.get('charged_total_tokens') != charged
                    or row.get('reason') not in {'memory_headroom','requests','tokens','tokenizer_failure'}):
                raise ValueError('Pre-dispatch denial has no reconciled admission boundary')
            if row['reason'] in {'memory_headroom','tokenizer_failure'}:
                raise ValueError('Required resource or token measurement was unavailable: ' + row['reason'])
            denials += 1
        elif row.get('status') == 'admitted':
            if pending is not None or row.get('request') != requests + 1:
                raise ValueError('Overlapping, duplicate, or missing model admission')
            requests += 1
            tokens = _integer(row.get('counted_input_tokens'),'counted_input_tokens')
            maximum = _integer(row.get('reserved_output_tokens'),'reserved_output_tokens')
            charged += tokens + maximum
            if requests > expected['max_requests'] or tokens > expected['max_input_tokens'] or not 1 <= maximum <= expected['max_output_tokens'] or charged > expected['max_total_tokens']:
                raise ValueError('Model admission exceeds a frozen budget')
            if row.get('charged_total_tokens') != charged:
                raise ValueError('Model admission reservation does not reconcile')
            pending = (tokens,maximum)
        elif row.get('status') == 'completed':
            if pending is None or row.get('request') != requests:
                raise ValueError('Model settlement has no matching admission')
            tokens,maximum = pending
            output = _integer(row.get('output_tokens'),'output_tokens')
            actual_input = _integer(row.get('provider_input_tokens'),'provider_input_tokens')
            if row.get('counted_input_tokens') != tokens or actual_input != tokens or output > maximum:
                raise ValueError('Provider usage does not match the admitted budget')
            if normalized_limits(row['limits']) != expected or row.get('model') != model:
                raise ValueError('Model settlement differs from frozen limits/model')
            charged -= maximum - output
            if row.get('charged_total_tokens') != charged:
                raise ValueError('Model settlement total does not reconcile')
            inputs += tokens
            outputs += output
            pending = None
        else:
            raise ValueError('Model budget has an uncertain or disqualifying record: ' + str(row.get('status')))
    if pending is not None:
        raise ValueError('Model request has no final usage settlement')
    return {'qualified':True, 'status':'QUALIFIED', 'requests':requests,
            'denied_before_dispatch':denials,
            'charged_total_tokens':charged, 'input_tokens':inputs, 'output_tokens':outputs, 'issues':[]}


def qualify_comparison(rows, study):
    result = comparison_configuration(study['specification'])
    if study['specification']['purpose'] != 'smoke':
        bad = [{'arm':row['arm'], 'repeat':row['repeat'], 'task':row['task'],
                'status':row.get('budget_audit',{}).get('status','NO_EVIDENCE')}
               for row in rows if not row.get('budget_audit',{}).get('qualified')]
        if bad:
            result['qualified'] = False
            result['reasons'].append('Some planned attempts lack complete measured budget evidence')
        result['unqualified_trials'] = bad
    return result
