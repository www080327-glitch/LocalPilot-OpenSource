import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class Record:
    timestamp: datetime
    category: str
    value: Decimal


_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_VALUE_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]{1,2})?")


def _row_error(number: int, message: str) -> ValueError:
    return ValueError(f"row {number}: {message}")


def parse_records(text: str) -> list[Record]:
    """Parse CSV event records, reporting errors with physical line numbers."""
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    physical_lines = text.splitlines(keepends=True)
    previous_end = 0
    header_seen = False
    records: list[Record] = []

    while True:
        try:
            fields = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise _row_error(max(reader.line_num, 1), f"invalid CSV: {exc}") from exc

        end_line = max(reader.line_num, 1)
        record_lines = physical_lines[previous_end:end_line]
        previous_end = end_line
        # csv.reader yields [] for empty lines and a single whitespace field for
        # whitespace-only lines. Only a physical blank line is ignorable; a CSV
        # record such as `,,` or `\"\"` remains an invalid record.
        if len(record_lines) == 1 and not record_lines[0].strip():
            continue

        if not header_seen:
            normalized = [field.strip() for field in fields]
            if normalized != ["timestamp", "category", "value"]:
                raise _row_error(end_line, "expected header timestamp,category,value")
            header_seen = True
            continue

        if len(fields) != 3:
            raise _row_error(end_line, "expected exactly three fields")
        timestamp_text, category, value_text = (field.strip() for field in fields)

        if not category:
            raise _row_error(end_line, "category must not be empty")
        if not _TIMESTAMP_RE.fullmatch(timestamp_text):
            raise _row_error(end_line, "invalid timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(
                timestamp_text[:-1] + "+00:00" if timestamp_text.endswith("Z") else timestamp_text
            )
            parsed_timestamp = parsed_timestamp.astimezone(timezone.utc)
        except ValueError as exc:
            raise _row_error(end_line, "invalid timestamp") from exc

        if not _VALUE_RE.fullmatch(value_text):
            raise _row_error(end_line, "invalid decimal value")
        records.append(Record(parsed_timestamp, category, Decimal(value_text)))

    if not header_seen:
        raise _row_error(1, "missing header")
    return records
