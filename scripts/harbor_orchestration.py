"""Frozen execution contract for the optional, single-model child-agent arm."""

LOCALPILOT_ADAPTER = 'scripts.localpilot_harbor:LocalPilotHarborAgent'
WORKER_DEFAULTS = {'max_worker_steps':6, 'max_worker_tool_calls':8,
                   'max_worker_token_units':131072, 'max_worker_output_tokens':1024}
ORCHESTRATION_OPTIONS = {'orchestration', 'max_children', 'max_running_children', *WORKER_DEFAULTS}


def orchestration_contract(options):
    mode = options.get('orchestration', 'single')
    if not isinstance(mode, str) or mode not in {'single', 'multi-agent'}:
        raise ValueError('orchestration must be single or multi-agent')
    if mode == 'single':
        if any(options.get(name) is not None for name in ORCHESTRATION_OPTIONS - {'orchestration'}):
            raise ValueError('Child limits require multi-agent orchestration')
        children = running = 0
    else:
        if options.get('provider_kind', 'local-openai') != 'local-openai' or not isinstance(options.get('model_budget'), dict):
            raise ValueError('Multi-agent evaluation requires the shared measured local model transport')
        children = options.get('max_children')
        running = options.get('max_running_children')
        children = 4 if children is None else children
        running = 2 if running is None else running
        if any(type(value) is not int or value <= 0 for value in (children, running)) or running > children:
            raise ValueError('Child limits must be positive integers with running children <= total children')
    contract = {'version':1, 'mode':mode, 'max_children':children,
            'max_running_children':running, 'max_depth':1, 'model_slots':1,
            'model_backends':1, 'tool_target':'harbor_task_environment'}
    if mode == 'multi-agent':
        worker = {name:default if options.get(name) is None else options[name]
                  for name,default in WORKER_DEFAULTS.items()}
        if any(type(value) is not int or value <= 0 for value in worker.values()):
            raise ValueError('Worker budgets must be positive integers')
        output = options.get('max_output_tokens', 2048)
        if type(output) is not int or output <= 0:
            raise ValueError('Parent output budget must be a positive integer')
        if options.get('max_worker_output_tokens') is None:
            worker['max_worker_output_tokens'] = min(worker['max_worker_output_tokens'], output)
        if worker['max_worker_output_tokens'] > output:
            raise ValueError('Worker output budget cannot exceed its parent output budget')
        contract['worker_budgets'] = worker
    return contract


def arm_orchestration(agent):
    options = agent.get('kwargs', {})
    if agent.get('import_path') == LOCALPILOT_ADAPTER:
        return orchestration_contract(options)
    if ORCHESTRATION_OPTIONS.intersection(options):
        raise ValueError('LocalPilot orchestration options cannot configure a reference adapter')
    return {'mode':'reference_native', 'model_slots':1}


def validate_orchestration_evidence(value, contract, measured, model):
    if not isinstance(value, dict) or value.get('contract') != contract:
        raise ValueError('Observed orchestration differs from the frozen configuration')
    if value.get('shared_backend') is not True or value.get('shared_scheduler') is not True:
        raise ValueError('Parent and workers did not share one backend and model scheduler')
    if value.get('model_slots') != contract['model_slots']:
        raise ValueError('Observed model concurrency differs from the frozen slot limit')
    if value.get('cancellation_requested') is not False:
        raise ValueError('Cancelled container execution has no portable termination receipt')
    registries = value.get('registries')
    children = value.get('children')
    if not isinstance(registries, list) or not isinstance(children, list) or len(registries) != len(children) + 1:
        raise ValueError('Missing parent or child tool registry evidence')
    if any(registry != ['shell'] for registry in registries):
        raise ValueError('A parent or child registry exposed tools outside the container bridge')
    if len(children) > contract['max_children'] or len({row['id'] for row in children}) != len(children):
        raise ValueError('Duplicate children or child count exceeds the frozen limit')
    if any(row.get('configured_model') != model for row in children):
        raise ValueError('A worker used a different configured model')
    denials = measured.get('denied_before_dispatch', 0)
    if value.get('model_attempts') != measured['requests'] + denials or value.get('model_calls') != measured['requests']:
        raise ValueError('Parent/worker model statistics do not reconcile with the shared budget ledger')
    for name in ('input_tokens', 'output_tokens'):
        if value.get(name) != measured[name]:
            raise ValueError('Parent/worker token statistics do not reconcile with the shared budget ledger')
    if value.get('failed_attempts') != denials:
        raise ValueError('Worker model failures have incomplete provider usage')
    return {'mode':contract['mode'], 'children':len(children), 'model_slots':1,
            'observed_delegation':bool(children),
            'scope':'SINGLE_MODEL_SHARED_BUDGET_CONTAINER_TOOLS'}
