import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO


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
    """Parse the public CSV event-log format into immutable records."""
    reader = csv.reader(StringIO(text, newline=""), strict=True)
    records: list[Record] = []
    header_seen = False

    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            line = max(reader.line_num, 1)
            raise ValueError(f"row {line}: invalid CSV: {exc}") from exc

        line = max(reader.line_num, 1)
        # csv.reader represents physically empty lines as []; a whitespace-only
        # line is a one-field row and is ignored as well.
        if not row or (len(row) == 1 and not row[0].strip()):
            continue

        fields = [field.strip() for field in row]
        if not header_seen:
            if fields != ["timestamp", "category", "value"]:
                raise ValueError(
                    f"row {line}: expected header timestamp,category,value"
                )
            header_seen = True
            continue

        if len(fields) != 3:
            raise ValueError(f"row {line}: expected exactly three fields")

        timestamp_text, category, value_text = fields
        if not _TIMESTAMP_RE.fullmatch(timestamp_text):
            raise ValueError(f"row {line}: invalid timestamp {timestamp_text!r}")
        try:
            timestamp = datetime.fromisoformat(
                timestamp_text[:-1] + "+00:00"
                if timestamp_text.endswith("Z")
                else timestamp_text
            )
            timestamp = timestamp.astimezone(timezone.utc)
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"row {line}: invalid timestamp {timestamp_text!r}") from exc

        if not category:
            raise ValueError(f"row {line}: category must not be empty")
        if not _VALUE_RE.fullmatch(value_text):
            raise ValueError(f"row {line}: invalid value {value_text!r}")
        try:
            value = Decimal(value_text)
        except Exception as exc:
            # The regular expression already excludes Decimal's special values;
            # retain a row-numbered error if Decimal ever rejects a matched form.
            raise ValueError(f"row {line}: invalid value {value_text!r}") from exc

        records.append(Record(timestamp, category, value))

    if not header_seen:
        raise ValueError("row 1: missing CSV header")
    return records
