from collections.abc import Sequence
from datetime import timezone
from decimal import Decimal

from .parser import Record


def _utc_string(timestamp):
    timestamp = timestamp.astimezone(timezone.utc)
    return (
        f"{timestamp.year:04d}-{timestamp.month:02d}-{timestamp.day:02d}T"
        f"{timestamp.hour:02d}:{timestamp.minute:02d}:{timestamp.second:02d}Z"
    )


def summarize(records: Sequence[Record]) -> dict:
    """Summarize records by category without changing the input sequence."""
    grouped = {}
    record_count = 0

    for record in records:
        record_count += 1
        value_tuple = record.value.as_tuple()
        coefficient = int("".join(map(str, value_tuple.digits)) or "0")
        if value_tuple.sign:
            coefficient = -coefficient
        exponent = value_tuple.exponent

        # Store each sum as an integer at a shared decimal scale. This avoids
        # Decimal context precision limits when summing large values.
        group = grouped.get(record.category)
        if group is None:
            scale = min(-2, exponent)
            total = coefficient * 10 ** (exponent - scale)
            timestamp = record.timestamp.astimezone(timezone.utc)
            grouped[record.category] = [1, total, scale, timestamp, timestamp]
            continue

        count, total, scale, first, last = group
        if exponent < scale:
            total *= 10 ** (scale - exponent)
            scale = exponent
        total += coefficient * 10 ** (exponent - scale)

        timestamp = record.timestamp.astimezone(timezone.utc)
        if timestamp < first:
            first = timestamp
        if timestamp > last:
            last = timestamp
        grouped[record.category] = [count + 1, total, scale, first, last]

    result_groups = []
    for category in sorted(grouped):
        count, total, scale, first, last = grouped[category]
        sign = int(total < 0)
        digits = tuple(int(digit) for digit in str(abs(total)))
        exact_total = Decimal((sign, digits, scale))
        result_groups.append(
            {
                "category": category,
                "count": count,
                "total": format(exact_total, ".2f"),
                "first": _utc_string(first),
                "last": _utc_string(last),
            }
        )

    return {"record_count": record_count, "groups": result_groups}
