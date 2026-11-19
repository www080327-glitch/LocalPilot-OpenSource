# logstats public contract

Implement a Python standard-library CSV event-log summarizer. No external dependency.
There are three implementation modules and the existing package __init__.py.

## parser.py
Keep the frozen dataclass Record(timestamp: datetime, category: str, value: Decimal).
parse_records(text: str) -> list[Record] accepts CSV with header timestamp,category,value
in exactly that order. Trim surrounding whitespace from header names and field values.
Use real CSV rules: quoted commas, doubled quote characters, and quoted field newlines
must work. Ignore empty lines and lines containing only whitespace, before/after the
header or between records; a row containing delimiters but empty fields is invalid.
Header-only input yields an empty list; missing or incorrect headers are errors.

Timestamps have the form YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS+HH:MM / -HH:MM,
represent a valid calendar time with seconds precision, and must include a timezone.
Normalize Record.timestamp to timezone.utc. Category must be nonempty after trimming.
Value is a signed or unsigned decimal number with ASCII digits, an optional decimal
point and one or two fractional digits; no exponent, NaN, Infinity, or empty value.
Store it as Decimal, never float. A row must have exactly three fields.

Any invalid header/record/CSV quoting raises ValueError with a message starting
"row N:", where N is the physical line on which the CSV record ends (csv.reader.line_num).
For completely missing input use row 1. Do not silently skip an invalid record.

## aggregate.py
summarize(records: Sequence[Record]) -> dict does not mutate the input. Return exactly:
{"record_count": integer, "groups": [{"category": string, "count": integer,
 "total": decimal-string, "first": UTC-string, "last": UTC-string}, ...]}
Group by exact category after parsing, sum values exactly, and sort groups by Python's
case-sensitive Unicode string order. total always has two fractional digits, no exponent
or leading plus; a zero total is "0.00". first/last are the minimum/maximum timestamp in
the group, formatted YYYY-MM-DDTHH:MM:SSZ in UTC. Empty input gives record_count 0 and
groups []. Do not infer any financial meaning from these generic event values.

## __main__.py
python -m logstats INPUT [--output PATH] reads UTF-8 CSV and uses the two public functions.
On success, exit 0. Without --output, write one JSON object and a newline to stdout.
With --output, write that JSON plus a newline to PATH and leave stdout empty. Unicode
data must round-trip; directories for PATH may be assumed to exist.
Invalid input or an input/output file error exits 2, writes one useful "error: ..." line
to stderr, leaves stdout empty, and does not print a traceback. CSV errors include the
parser's row number. Parse before opening the output file so invalid input does not
truncate an existing output. The CLI must not call external services or install anything.

## Public acceptance
tests/test_acceptance.py and fixtures/ are the fixed contract examples. They are visible
to both children and parent; do not edit them. Additional tests are allowed in another
file but cannot replace the fixed tests. The external runner restores the original
acceptance files beside only the four delivered package modules before checking them.
