"""Command-line interface for the logstats CSV summarizer."""

import argparse
import json
import sys

from .aggregate import summarize
from .parser import parse_records


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m logstats")
    parser.add_argument("input", help="UTF-8 CSV event log")
    parser.add_argument("--output", help="write JSON to this path instead of stdout")
    args = parser.parse_args(argv)

    try:
        with open(args.input, "r", encoding="utf-8", newline="") as source:
            records = parse_records(source.read())
        result = summarize(records)
        text = json.dumps(result, ensure_ascii=False) + "\n"
        if args.output is None:
            sys.stdout.write(text)
        else:
            with open(args.output, "w", encoding="utf-8", newline="") as destination:
                destination.write(text)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
