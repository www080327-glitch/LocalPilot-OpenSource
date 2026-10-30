"""Disposable pure JSON Schema validation; no MCP transport or Core imports."""
import json
import resource
import sys


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from jsonschema import Draft202012Validator
    value = json.loads(sys.stdin.buffer.read(1048577))
    errors = []
    for error in Draft202012Validator(value['schema']).iter_errors(value['value']):
        path = '.'.join(str(part)[:64] for part in error.absolute_path)[:256]
        errors.append('$.' + path + ': violates ' + str(error.validator))
        if len(errors) >= 8:
            break
    print(json.dumps(errors))


if __name__ == '__main__':
    main()
