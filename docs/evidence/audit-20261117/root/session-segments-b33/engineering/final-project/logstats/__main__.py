"""Command-line entry point for the logstats package."""

import argparse
import json
from pathlib import Path
import sys

from .aggregate import summarize
from .parser import parse_records


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m logstats")
    parser.add_argument("input", help="UTF-8 CSV event log to summarize")
    parser.add_argument("--output", help="write JSON output to this path instead of stdout")
    args = parser.parse_args(argv)

    try:
        text = Path(args.input).read_text(encoding="utf-8")
        records = parse_records(text)
        result = json.dumps(summarize(records), ensure_ascii=False) + "\n"
        if args.output is None:
            sys.stdout.write(result)
        else:
            Path(args.output).write_text(result, encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        message = str(exc).replace("\n", " ").strip()
        print(f"error: {message}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
