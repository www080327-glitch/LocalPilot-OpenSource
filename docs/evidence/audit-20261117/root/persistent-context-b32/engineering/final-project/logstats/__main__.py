import argparse
import json
import sys
from pathlib import Path

from .aggregate import summarize
from .parser import parse_records


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = _ArgumentParser(prog="python -m logstats")
    parser.add_argument("input", help="UTF-8 CSV event log")
    parser.add_argument("--output", help="write JSON to this path instead of stdout")

    try:
        args = parser.parse_args(argv)
        text = Path(args.input).read_text(encoding="utf-8")
        result = summarize(parse_records(text))
        serialized = json.dumps(result, ensure_ascii=False) + "\n"
        if args.output is None:
            sys.stdout.write(serialized)
        else:
            Path(args.output).write_text(serialized, encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
