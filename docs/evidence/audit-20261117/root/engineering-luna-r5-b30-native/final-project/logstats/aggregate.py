from collections.abc import Sequence
from datetime import timezone
from decimal import Decimal

from .parser import Record


def _utc_string(timestamp) -> str:
    """Format a timestamp in UTC with a fixed-width, seconds-only representation."""
    utc = timestamp.astimezone(timezone.utc)
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T"
        f"{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}Z"
    )


def _coefficient(digits: tuple[int, ...]) -> int:
    """Convert Decimal digits without relying on Python's integer-string limit."""
    value = 0
    for start in range(0, len(digits), 9):
        chunk = digits[start : start + 9]
        value = value * 10 ** len(chunk) + int("".join(map(str, chunk)))
    return value


def _add_exact(total: tuple[int, int], value: Decimal) -> tuple[int, int]:
    """Add a finite Decimal as an integer coefficient and a base-10 exponent."""
    coefficient, exponent = total
    parts = value.as_tuple()
    value_coefficient = _coefficient(parts.digits)
    if parts.sign:
        value_coefficient = -value_coefficient

    common_exponent = min(exponent, parts.exponent)
    coefficient = coefficient * 10 ** (exponent - common_exponent)
    value_coefficient *= 10 ** (parts.exponent - common_exponent)
    return coefficient + value_coefficient, common_exponent


def _int_digits(value: int) -> tuple[int, ...]:
    """Return an integer's decimal digits without converting a huge int to text."""
    if value == 0:
        return (0,)
    chunks = []
    while value:
        value, chunk = divmod(value, 1_000_000_000)
        chunks.append(chunk)
    digits = list(map(int, str(chunks.pop())))
    for chunk in reversed(chunks):
        digits.extend(map(int, f"{chunk:09d}"))
    return tuple(digits)


def _decimal_string(coefficient: int, exponent: int) -> str:
    """Render a total with exactly two fractional digits without float conversion."""
    total = Decimal((int(coefficient < 0), _int_digits(abs(coefficient)), exponent))
    return format(total, ".2f")


def summarize(records: Sequence[Record]) -> dict:
    groups = {}
    record_count = 0

    for record in records:
        record_count += 1
        group = groups.get(record.category)
        if group is None:
            group = {
                "count": 0,
                "coefficient": 0,
                "exponent": 0,
                "first": record.timestamp,
                "last": record.timestamp,
            }
            groups[record.category] = group

        group["count"] += 1
        group["coefficient"], group["exponent"] = _add_exact(
            (group["coefficient"], group["exponent"]), record.value
        )
        if record.timestamp < group["first"]:
            group["first"] = record.timestamp
        if record.timestamp > group["last"]:
            group["last"] = record.timestamp

    result_groups = []
    for category in sorted(groups):
        group = groups[category]
        result_groups.append(
            {
                "category": category,
                "count": group["count"],
                "total": _decimal_string(group["coefficient"], group["exponent"]),
                "first": _utc_string(group["first"]),
                "last": _utc_string(group["last"]),
            }
        )

    return {"record_count": record_count, "groups": result_groups}
