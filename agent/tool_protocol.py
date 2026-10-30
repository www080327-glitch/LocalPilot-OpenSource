"""Pure pre-dispatch validation; tool exceptions never certify absence of effects."""
import math


class ToolArgumentsError(ValueError):
    def __init__(self, errors):
        self.errors = errors[:8]
        super().__init__('Invalid tool argument fields: ' + '; '.join(self.errors))


def schema_errors(value, schema, path='$'):
    """Validate the schema subset used by host tools; Gateway checks still apply."""
    errors = []
    kind = schema.get('type')
    types = {'object': lambda v: isinstance(v, dict), 'array': lambda v: isinstance(v, list),
             'string': lambda v: isinstance(v, str), 'boolean': lambda v: type(v) is bool,
             'integer': lambda v: type(v) is int,
             'number': lambda v: type(v) in (int, float) and math.isfinite(v), 'null': lambda v: v is None}
    kinds = kind if isinstance(kind, list) else [kind]
    if any(k in types for k in kinds) and not any(types[k](value) for k in kinds if k in types):
        return [f'{path}: expected {kind}']
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: expected one of {schema["enum"]}')
    if 'const' in schema and value != schema['const']:
        errors.append(f'{path}: expected {schema["const"]!r}')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                errors.append(f'{path}.{key}: required')
        if schema.get('additionalProperties') is False:
            for key in sorted(value.keys() - props.keys()):
                errors.append(f'{path}.{key}: unexpected field')
        for key in sorted(value.keys() & props.keys()):
            errors.extend(schema_errors(value[key], props[key], f'{path}.{key}'))
    if isinstance(value, list):
        for key, test in [('minItems', lambda n: len(value) < n), ('maxItems', lambda n: len(value) > n)]:
            if key in schema and test(schema[key]):
                errors.append(f'{path}: violates {key}={schema[key]}')
        for i, item in enumerate(value):
            errors.extend(schema_errors(item, schema.get('items', {}), f'{path}[{i}]'))
            if len(errors) >= 8:
                break
    if isinstance(value, str):
        for key, test in [('minLength', lambda n: len(value) < n), ('maxLength', lambda n: len(value) > n)]:
            if key in schema and test(schema[key]):
                errors.append(f'{path}: violates {key}={schema[key]}')
    if type(value) in (int, float):
        for key, test in [('minimum', lambda n: value < n), ('maximum', lambda n: value > n),
                          ('exclusiveMinimum', lambda n: value <= n)]:
            if key in schema and test(schema[key]):
                errors.append(f'{path}: violates {key}={schema[key]}')
    for part in schema.get('allOf', []):
        errors.extend(schema_errors(value, part, path))
    if 'if' in schema and not schema_errors(value, schema['if'], path):
        errors.extend(schema_errors(value, schema.get('then', {}), path))
    return errors[:8]


def validate_arguments(name, arguments, schemas):
    canonical = 'execute' if name == 'run_command' else name
    from .schemas import TOOL_SCHEMAS
    from .runtime_tools import RUNTIME_TOOL_NAMES, ASYNC_TOOL_NAMES
    if canonical not in {s['function']['name'] for s in TOOL_SCHEMAS} | RUNTIME_TOOL_NAMES | ASYNC_TOOL_NAMES:
        # Native/host extensions retain their owning protocol validators. This
        # change cannot reinterpret postconditions, qualification or UNKNOWN.
        return
    schema = next((s['function']['parameters'] for s in schemas
                   if s['function']['name'] == canonical), None)
    if not isinstance(arguments, dict):
        raise ToolArgumentsError(['$: expected object'])
    errors = schema_errors(arguments, schema) if schema is not None else []
    if canonical == 'apply_patch' and not errors:
        for i, change in enumerate(arguments['changes']):
            operation = change['operation']
            required = ['content'] if operation == 'create' else ['old_text', 'new_text'] if operation == 'update' else ['expected_sha256']
            errors.extend(f'$.changes[{i}].{key}: required for {operation}' for key in required if key not in change)
            if operation == 'update' and not change.get('old_text'):
                errors.append(f'$.changes[{i}].old_text: must be nonempty')
            if operation == 'delete' and not change.get('expected_sha256'):
                errors.append(f'$.changes[{i}].expected_sha256: must be nonempty')
            allowed = {'path', 'operation', 'expected_sha256'} | (
                {'content'} if operation == 'create' else {'old_text', 'new_text'} if operation == 'update' else set())
            for key in sorted(change.keys() - allowed):
                errors.append(f'$.changes[{i}].{key}: not valid for {operation}')
    if errors:
        raise ToolArgumentsError(errors)


def resolves_patch_rejection(rejected, successful):
    """Bind a fresh successful patch to a compatible, NEVER-dispatched proposal.

    This settles a rejected proposal, not the task or its verification. No failed,
    dispatched, partial, UNKNOWN or different-worker receipt can be settled here.
    """
    import json
    if rejected['name'] != 'apply_patch' or successful['name'] != 'apply_patch':
        return False
    result = rejected['payload'].get('result', {})
    if (not isinstance(result, dict) or result.get('stage') != 'not_dispatched'
            or result.get('action_sent') is not False or result.get('action_may_have_applied') is not False
            or rejected.get('side_effect_status') != 'not_completed'
            or not successful['payload'].get('ok') or successful.get('receipt_reused')
            or successful.get('side_effect_status') != 'completed'
            or rejected.get('worker_id') != successful.get('worker_id')):
        return False
    try:
        before, after = json.loads(rejected['arguments']), json.loads(successful['arguments'])
        requested, performed = before['changes'], after['changes']
        if not isinstance(requested, list) or not requested:
            return False
        # Only known fields can be related. Never interpret arbitrary invalid data.
        if set(before) - {'changes', 'operation'}:
            return False
        for change in requested:
            if (not isinstance(change, dict) or not isinstance(change.get('path'), str)
                    or set(change) - {'path','operation','content','old_text','new_text','expected_sha256'}):
                return False
            wanted = dict(change)
            if 'operation' in before:
                if 'operation' in wanted and wanted['operation'] != before['operation']:
                    return False
                wanted['operation'] = before['operation']
            # A bare path or broken field type is insufficient identity for repair.
            if not any(k in wanted for k in ('content','old_text','expected_sha256')):
                return False
            if not any(all(k in c and type(c[k]) is type(v) and c[k] == v for k,v in wanted.items()) for c in performed):
                return False
        return True
    except (ValueError, KeyError, TypeError):
        return False


