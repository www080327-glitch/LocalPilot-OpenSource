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
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_VALUE_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]{1,2})?")


class _TrackedLines:
    """Keep the physical source lines associated with each CSV record."""

    def __init__(self, text: str) -> None:
        self._stream = io.StringIO(text, newline="")
        self.consumed: list[str] = []

    def __iter__(self):
        return self

    def __next__(self) -> str:
        line = next(self._stream)
        self.consumed.append(line)
        return line


def _error(row_number: int, message: str) -> ValueError:
    return ValueError(f"row {row_number}: {message}")


def parse_records(text: str) -> list[Record]:
    lines = _TrackedLines(text)
    reader = csv.reader(lines, strict=True)

    def next_row() -> tuple[list[str] | None, int]:
        try:
            row = next(reader)
        except StopIteration:
            return None, max(reader.line_num, 1)
        except csv.Error as exc:
            raise _error(max(reader.line_num, 1), f"invalid CSV: {exc}") from exc
        return row, max(reader.line_num, 1)

    # Find the first nonblank CSV record to use as the header.
    header: list[str] | None = None
    while True:
        previous_line = reader.line_num
        row, row_number = next_row()
        if row is None:
            raise _error(row_number, "missing header")
        source_lines = lines.consumed[previous_line:reader.line_num]
        if not row or (source_lines and all(not line.strip() for line in source_lines)):
            continue
        header = [field.strip() for field in row]
        if header != ["timestamp", "category", "value"]:
            raise _error(row_number, "expected header timestamp,category,value")
        break

    records: list[Record] = []
    while True:
        previous_line = reader.line_num
        row, row_number = next_row()
        if row is None:
            return records
        source_lines = lines.consumed[previous_line:reader.line_num]
        if not row or (source_lines and all(not line.strip() for line in source_lines)):
            continue

        fields = [field.strip() for field in row]
        if len(fields) != 3:
            raise _error(row_number, "record must contain exactly three fields")

        timestamp_text, category, value_text = fields
        if not _TIMESTAMP_RE.fullmatch(timestamp_text):
            raise _error(row_number, "invalid timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(
                timestamp_text[:-1] + "+00:00" if timestamp_text.endswith("Z") else timestamp_text
            )
        except ValueError as exc:
            raise _error(row_number, "invalid timestamp") from exc
        if parsed_timestamp.tzinfo is None:
            raise _error(row_number, "timestamp must include a timezone")
        timestamp = parsed_timestamp.astimezone(timezone.utc)

        if not category:
            raise _error(row_number, "category must not be empty")
        if not _VALUE_RE.fullmatch(value_text):
            raise _error(row_number, "invalid decimal value")

        records.append(Record(timestamp, category, Decimal(value_text)))
