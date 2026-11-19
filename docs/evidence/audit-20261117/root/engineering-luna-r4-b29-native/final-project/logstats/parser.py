import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
import re


@dataclass(frozen=True)
class Record:
    timestamp: datetime
    category: str
    value: Decimal


_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_VALUE_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]{1,2})?")
_HEADER = ["timestamp", "category", "value"]


def _bare_quote_record_ends(text: str) -> set[int]:
    """Find CSV records containing a quote inside an unquoted field.

    ``csv.reader(strict=True)`` rejects unmatched quotes and text after a closing
    quote, but accepts a quote embedded in an unquoted field as ordinary text.
    Such a quote is malformed CSV, so track quoting boundaries for this case.
    """
    bad_ends: set[int] = set()
    in_quotes = False
    field_start = True
    bad_record = False
    line = 1
    index = 0

    while index < len(text):
        char = text[index]
        if in_quotes:
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = False
            if char in "\r\n":
                if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                    index += 1
                line += 1
        elif char in "\r\n":
            if bad_record:
                bad_ends.add(line)
            bad_record = False
            field_start = True
            if char == "\\r" and index + 1 < len(text) and text[index + 1] == "\\n":
                index += 1
            line += 1
        elif char == ",":
            field_start = True
        elif char == '"':
            if field_start:
                in_quotes = True
            else:
                bad_record = True
        else:
            field_start = False
        index += 1

    if bad_record:
        bad_ends.add(line)
    return bad_ends


def parse_records(text: str) -> list[Record]:
    """Parse CSV event records, reporting errors at their ending physical line."""
    if not isinstance(text, str):
        raise ValueError("row 1: input must be text")

    bare_quote_ends = _bare_quote_record_ends(text)
    reader = csv.reader(StringIO(text, newline=""), strict=True)
    # csv.reader.line_num counts physical lines, including newlines in quoted fields.
    # Keep the source lines so whitespace-only physical lines can be distinguished
    # from quoted fields whose contents happen to be whitespace.
    physical_lines = text.splitlines()
    previous_line = 0
    header_seen = False
    records: list[Record] = []

    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            line = max(reader.line_num, 1)
            raise ValueError(f"row {line}: invalid CSV: {exc}") from exc

        line = max(reader.line_num, 1)
        if line in bare_quote_ends:
            raise ValueError(f"row {line}: invalid CSV quoting")

        # Ignore only actual blank/whitespace physical lines, never a quoted blank
        # field. Empty CSV records are returned as [] by csv.reader.
        physical_blank = (
            line == previous_line + 1
            and previous_line < len(physical_lines)
            and not physical_lines[previous_line].strip()
        )
        previous_line = line
        if not row or physical_blank:
            continue

        fields = [field.strip() for field in row]
        if not header_seen:
            if fields != _HEADER:
                raise ValueError(f"row {line}: expected header timestamp,category,value")
            header_seen = True
            continue

        if len(fields) != 3:
            raise ValueError(f"row {line}: expected exactly three fields")

        timestamp_text, category, value_text = fields
        if not _TIMESTAMP_RE.fullmatch(timestamp_text):
            raise ValueError(f"row {line}: invalid timestamp")
        try:
            timestamp = datetime.fromisoformat(
                timestamp_text[:-1] + "+00:00" if timestamp_text.endswith("Z") else timestamp_text
            ).astimezone(timezone.utc)
        except ValueError as exc:
            raise ValueError(f"row {line}: invalid timestamp") from exc

        if not category:
            raise ValueError(f"row {line}: category must not be empty")
        if not _VALUE_RE.fullmatch(value_text):
            raise ValueError(f"row {line}: invalid decimal value")

        # The regular expression excludes exponent and non-finite forms, so Decimal
        # preserves the input's exact decimal value without a float conversion.
        records.append(Record(timestamp, category, Decimal(value_text)))

    if not header_seen:
        raise ValueError("row 1: missing header")
    return records
