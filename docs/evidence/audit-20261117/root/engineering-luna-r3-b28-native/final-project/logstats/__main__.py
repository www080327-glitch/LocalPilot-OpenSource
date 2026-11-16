"""Command-line interface for the logstats package."""

import argparse
import json
import sys
from pathlib import Path

from .aggregate import summarize
from .parser import parse_records


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m logstats")
    parser.add_argument("input", help="UTF-8 CSV event log")
    parser.add_argument("--output", help="write JSON to this path instead of stdout")
    args = parser.parse_args(argv)

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
        message = str(exc).replace("\r", " ").replace("\n", " ")
        sys.stderr.write(f"error: {message}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
