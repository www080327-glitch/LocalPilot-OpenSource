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


def _row_error(row_number: int, message: str) -> ValueError:
    return ValueError(f"row {row_number}: {message}")


def _invalid_quote_syntax(raw_record: str) -> bool:
    """Reject quotes in unquoted fields while leaving CSV parsing to csv.reader."""
    field_start = True
    in_quotes = False
    after_quote = False
    index = 0
    while index < len(raw_record):
        char = raw_record[index]
        if in_quotes:
            if char == '"':
                if index + 1 < len(raw_record) and raw_record[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = False
                after_quote = True
        elif char in "\r\n":
            field_start = True
            after_quote = False
        elif after_quote:
            if char == ",":
                field_start = True
                after_quote = False
            else:
                return True
        elif field_start:
            if char == '"':
                in_quotes = True
                field_start = False
            elif char == ",":
                field_start = True
            else:
                field_start = False
        elif char == ",":
            field_start = True
        elif char == '"':
            return True
        index += 1
    return False


def parse_records(text: str) -> list[Record]:
    """Parse CSV event records, reporting errors at their physical ending line."""
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    physical_lines = text.splitlines(keepends=True)
    records: list[Record] = []
    previous_line = 0
    header_seen = False

    while True:
        try:
            fields = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise _row_error(max(reader.line_num, 1), f"invalid CSV: {exc}") from None

        row_number = max(reader.line_num, 1)
        raw_record = "".join(physical_lines[previous_line:reader.line_num])
        previous_line = reader.line_num
        if _invalid_quote_syntax(raw_record):
            raise _row_error(row_number, "invalid CSV quoting")

        # csv.reader returns [] for a physically empty row and a one-field value
        # for a whitespace-only row. Do not discard quoted whitespace fields.
        if not fields or (len(fields) == 1 and not raw_record.strip()):
            continue

        if not header_seen:
            header_seen = True
            header = [field.strip() for field in fields]
            if header != ["timestamp", "category", "value"]:
                raise _row_error(row_number, "expected header timestamp,category,value")
            continue

        if len(fields) != 3:
            raise _row_error(row_number, "record must contain exactly three fields")

        timestamp_text, category, value_text = (field.strip() for field in fields)
        if not category:
            raise _row_error(row_number, "category must not be empty")

        if not _TIMESTAMP_RE.fullmatch(timestamp_text):
            raise _row_error(row_number, "timestamp must include a timezone and seconds")
        try:
            timestamp = datetime.strptime(timestamp_text, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise _row_error(row_number, "invalid timestamp") from None
        timestamp = timestamp.astimezone(timezone.utc)

        if not _VALUE_RE.fullmatch(value_text):
            raise _row_error(row_number, "value must be a decimal with at most two fractional digits")
        try:
            value = Decimal(value_text)
        except Exception:
            raise _row_error(row_number, "invalid decimal value") from None

        records.append(Record(timestamp, category, value))

    if not header_seen:
        raise _row_error(max(reader.line_num, 1), "missing header")
    return records
