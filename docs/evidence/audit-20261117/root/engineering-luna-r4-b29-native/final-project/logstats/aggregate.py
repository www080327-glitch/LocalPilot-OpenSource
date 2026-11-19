from collections.abc import Sequence
from datetime import timezone
from decimal import Decimal

from .parser import Record


def _decimal_parts(value: Decimal) -> tuple[int, int]:
    """Return an exact signed coefficient and exponent for a finite Decimal."""
    sign, digits, exponent = value.as_tuple()
    coefficient = int("".join(map(str, digits)) or "0")
    if sign:
        coefficient = -coefficient
    return coefficient, exponent


def _decimal_string(coefficient: int, exponent: int) -> str:
    """Format a decimal represented as coefficient * 10**exponent to cents."""
    value = Decimal((1 if coefficient < 0 else 0,
                     tuple(int(digit) for digit in str(abs(coefficient))) or (0,),
                     exponent))
    return format(value, ".2f")


def summarize(records: Sequence[Record]) -> dict:
    """Summarize records by exact category without changing the input."""
    groups = {}
    record_count = 0

    for record in records:
        record_count += 1
        group = groups.get(record.category)
        coefficient, exponent = _decimal_parts(record.value)
        if group is None:
            groups[record.category] = {
                "count": 1,
                "coefficient": coefficient,
                "exponent": exponent,
                "first": record.timestamp,
                "last": record.timestamp,
            }
            continue

        # Align integer coefficients to a common exponent, avoiding Decimal's
        # precision context so totals remain exact even for very large values.
        common_exponent = min(group["exponent"], exponent)
        group["coefficient"] = (
            group["coefficient"] * 10 ** (group["exponent"] - common_exponent)
            + coefficient * 10 ** (exponent - common_exponent)
        )
        group["exponent"] = common_exponent
        group["count"] += 1
        if record.timestamp < group["first"]:
            group["first"] = record.timestamp
        if record.timestamp > group["last"]:
            group["last"] = record.timestamp

    result_groups = []
    for category in sorted(groups):
        group = groups[category]
        first = group["first"].astimezone(timezone.utc)
        last = group["last"].astimezone(timezone.utc)
        result_groups.append({
            "category": category,
            "count": group["count"],
            "total": _decimal_string(group["coefficient"], group["exponent"]),
            "first": first.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last": last.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    return {"record_count": record_count, "groups": result_groups}
