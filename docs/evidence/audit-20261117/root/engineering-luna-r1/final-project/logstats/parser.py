import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import io
import re


@dataclass(frozen=True)
class Record:
    timestamp: datetime
    category: str
    value: Decimal


_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
_VALUE_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]{1,2})?\Z")


def parse_records(text: str) -> list[Record]:
    """Parse CSV event records, reporting all input errors with physical row numbers."""
    lines = text.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    records: list[Record] = []
    header_seen = False
    previous_line = 0

    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            line_number = reader.line_num or 1
            raise ValueError(f"row {line_number}: invalid CSV: {exc}") from exc

        line_number = reader.line_num or 1
        physical_lines = lines[previous_line:line_number]
        previous_line = line_number

        # csv.reader represents a physically blank line as [] and a whitespace-
        # only line as one whitespace field. Ignore those only when they are
        # standalone physical lines, not when they occur inside a quoted record.
        if (not row or (len(row) == 1 and row[0].strip() == "")) and physical_lines and all(
            line.strip() == "" for line in physical_lines
        ):
            continue

        if not header_seen:
            if [field.strip() for field in row] != ["timestamp", "category", "value"]:
                raise ValueError(f"row {line_number}: expected header timestamp,category,value")
            header_seen = True
            continue

        if len(row) != 3:
            raise ValueError(f"row {line_number}: expected exactly three fields")
        timestamp_text, category, value_text = (field.strip() for field in row)
        if not category:
            raise ValueError(f"row {line_number}: category must not be empty")

        if not _TIMESTAMP_RE.fullmatch(timestamp_text):
            raise ValueError(f"row {line_number}: invalid timestamp")
        try:
            parsed_timestamp = datetime.strptime(timestamp_text, "%Y-%m-%dT%H:%M:%S%z")
            parsed_timestamp = parsed_timestamp.astimezone(timezone.utc)
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"row {line_number}: invalid timestamp") from exc

        if not _VALUE_RE.fullmatch(value_text):
            raise ValueError(f"row {line_number}: invalid decimal value")
        try:
            value = Decimal(value_text)
        except Exception as exc:
            raise ValueError(f"row {line_number}: invalid decimal value") from exc

        records.append(Record(parsed_timestamp, category, value))

    if not header_seen:
        raise ValueError("row 1: missing header")
    return records
