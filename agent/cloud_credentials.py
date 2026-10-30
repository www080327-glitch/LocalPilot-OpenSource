"""Explicit host credential inputs. No discovery, shell evaluation or logging."""
import os
import stat


class CloudCredentialError(ValueError):
    def __init__(self, category):
        self.category = category
        super().__init__('Cloud credential configuration: ' + category)


def resolve_deepseek_key(api_key=None, *, key_file=None):
    """Explicit key > explicit file > environment key > environment file.

    Files contain one raw key, must be owner-only regular files and are never
    copied to environment, evidence, SQLite or another file.
    """
    if api_key is not None:
        key = api_key
    elif key_file is None and os.environ.get('DEEPSEEK_API_KEY'):
        key = os.environ['DEEPSEEK_API_KEY']
    else:
        path = key_file if key_file is not None else os.environ.get('DEEPSEEK_API_KEY_FILE')
        if not path:
            raise CloudCredentialError('missing_credentials')
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except (OSError, TypeError, ValueError):
            raise CloudCredentialError('configuration_path_error') from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise CloudCredentialError('unsafe_credential_file')
            if info.st_size > 4096:
                raise CloudCredentialError('invalid_credential_format')
            try:
                key = os.read(fd, 4097).decode('utf-8').removesuffix('\n')
            except UnicodeError:
                raise CloudCredentialError('invalid_credential_format') from None
        finally:
            os.close(fd)
    if not isinstance(key, str) or not key or len(key) > 4096 or any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in key):
        raise CloudCredentialError('invalid_credential_format')
    return key


def deepseek_configured():
    """Presence only; malformed explicit configuration must fail on loading."""
    return bool(os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('DEEPSEEK_API_KEY_FILE'))


def main():
    """Operator-only terminal entry; hidden input never enters command history."""
    import argparse
    import getpass
    import sys
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Save a project DeepSeek key using hidden terminal input.')
    parser.add_argument('--store', required=True, type=Path)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error('Hidden credential input requires your own interactive terminal.')
    key = resolve_deepseek_key(getpass.getpass('DeepSeek API key (hidden input): '))
    args.store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(args.store, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as target:
        target.write(key + '\n')
    print('Credential saved in an owner-only file. No API request was made.')


if __name__ == '__main__':
    main()
