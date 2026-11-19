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
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})\Z"
)
_VALUE_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]{1,2})?\Z")


def _error(row_number: int, message: str) -> ValueError:
    return ValueError(f"row {row_number}: {message}")


def parse_records(text: str) -> list[Record]:
    # Keep the original physical lines so whitespace-only lines can be skipped
    # without mistaking whitespace inside a quoted, multiline field for a blank.
    physical_lines = list(StringIO(text, newline=""))
    reader = csv.reader(physical_lines, strict=True)
    previous_line = 0
    header_seen = False
    records: list[Record] = []

    try:
        for fields in reader:
            row_number = reader.line_num
            source_lines = physical_lines[previous_line:row_number]
            previous_line = row_number

            if all(not line.strip() for line in source_lines):
                continue

            if not header_seen:
                header_seen = True
                header = [field.strip() for field in fields]
                if header != ["timestamp", "category", "value"]:
                    raise _error(row_number, "expected header timestamp,category,value")
                continue

            if len(fields) != 3:
                raise _error(row_number, "record must have exactly three fields")

            timestamp_text, category, value_text = (field.strip() for field in fields)
            if not category:
                raise _error(row_number, "category must not be empty")
            if not _TIMESTAMP_RE.fullmatch(timestamp_text):
                raise _error(row_number, "invalid timestamp")
            try:
                timestamp = datetime.fromisoformat(
                    timestamp_text[:-1] + "+00:00" if timestamp_text.endswith("Z") else timestamp_text
                )
            except ValueError as exc:
                raise _error(row_number, "invalid timestamp") from exc
            if timestamp.tzinfo is None:
                raise _error(row_number, "timestamp must include a timezone")

            if not _VALUE_RE.fullmatch(value_text):
                raise _error(row_number, "invalid decimal value")
            records.append(Record(timestamp.astimezone(timezone.utc), category, Decimal(value_text)))
    except csv.Error as exc:
        row_number = max(reader.line_num, 1)
        raise _error(row_number, f"invalid CSV: {exc}") from exc

    if not header_seen:
        raise _error(1, "missing header")
    return records
