from collections.abc import Sequence
from datetime import timezone
from decimal import Decimal

from .parser import Record


def _decimal_parts(value):
    """Return a Decimal as an exact signed integer coefficient and exponent."""
    sign, digits, exponent = value.as_tuple()
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
    return (-coefficient if sign else coefficient), exponent


def _add_scaled(total, total_exponent, value, value_exponent):
    """Add coefficient/exponent pairs without Decimal context rounding."""
    if value_exponent < total_exponent:
        total *= 10 ** (total_exponent - value_exponent)
        total_exponent = value_exponent
    else:
        value *= 10 ** (value_exponent - total_exponent)
    return total + value, total_exponent


def _format_total(coefficient, exponent):
    sign = 1 if coefficient < 0 else 0
    digits = tuple(int(digit) for digit in str(abs(coefficient)))
    if not digits:
        digits = (0,)
    return format(Decimal((sign, digits, exponent)), ".2f")


def _utc_string(timestamp):
    timestamp = timestamp.astimezone(timezone.utc)
    return (f"{timestamp.year:04d}-{timestamp.month:02d}-{timestamp.day:02d}T"
            f"{timestamp.hour:02d}:{timestamp.minute:02d}:{timestamp.second:02d}Z")


def summarize(records: Sequence[Record]) -> dict:
    """Summarize records by exact category without modifying the input."""
    groups = {}
    record_count = 0

    for record in records:
        record_count += 1
        timestamp = record.timestamp.astimezone(timezone.utc)
        coefficient, exponent = _decimal_parts(record.value)
        group = groups.get(record.category)
        if group is None:
            groups[record.category] = [1, coefficient, exponent, timestamp, timestamp]
        else:
            group[0] += 1
            group[1], group[2] = _add_scaled(
                group[1], group[2], coefficient, exponent
            )
            if timestamp < group[3]:
                group[3] = timestamp
            if timestamp > group[4]:
                group[4] = timestamp

    summaries = []
    for category in sorted(groups):
        count, coefficient, exponent, first, last = groups[category]
        summaries.append({
            "category": category,
            "count": count,
            "total": _format_total(coefficient, exponent),
            "first": _utc_string(first),
            "last": _utc_string(last),
        })

    return {"record_count": record_count, "groups": summaries}
