"""Command-line interface for the logstats package."""

import argparse
import json
from pathlib import Path
import sys

from .aggregate import summarize
from .parser import parse_records


def main(argv=None):
    argument_parser = argparse.ArgumentParser(prog="python -m logstats")
    argument_parser.add_argument("input", help="UTF-8 CSV event log")
    argument_parser.add_argument("--output", help="write JSON to this path instead of stdout")
    args = argument_parser.parse_args(argv)

    try:
        text = Path(args.input).read_text(encoding="utf-8")
        records = parse_records(text)
        result = summarize(records)
        rendered = json.dumps(result, ensure_ascii=False) + "\n"
        if args.output is None:
            sys.stdout.write(rendered)
        else:
            Path(args.output).write_text(rendered, encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
