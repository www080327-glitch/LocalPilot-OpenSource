from collections.abc import Sequence
from datetime import timezone
from decimal import Decimal

from .parser import Record


def _format_utc(timestamp):
    # isoformat keeps the required four-digit year even for years below 1000.
    return timestamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _decimal_from_parts(coefficient: int, exponent: int) -> Decimal:
    """Build a Decimal without applying the current decimal context."""
    digits = tuple(int(digit) for digit in str(abs(coefficient)))
    return Decimal((1 if coefficient < 0 else 0, digits, exponent))


def summarize(records: Sequence[Record]) -> dict:
    groups = {}

    for record in records:
        timestamp = record.timestamp.astimezone(timezone.utc)
        value_tuple = record.value.as_tuple()
        coefficient = int("".join(str(digit) for digit in value_tuple.digits) or "0")
        if value_tuple.sign:
            coefficient = -coefficient
        exponent = value_tuple.exponent

        group = groups.get(record.category)
        if group is None:
            groups[record.category] = {
                "count": 1,
                "coefficient": coefficient,
                "exponent": exponent,
                "first": timestamp,
                "last": timestamp,
            }
            continue

        # Align the integer coefficients instead of using Decimal addition, which
        # can round large exact totals under the process-wide decimal context.
        if exponent < group["exponent"]:
            group["coefficient"] *= 10 ** (group["exponent"] - exponent)
            group["exponent"] = exponent
        else:
            coefficient *= 10 ** (exponent - group["exponent"])
        group["coefficient"] += coefficient
        group["count"] += 1
        if timestamp < group["first"]:
            group["first"] = timestamp
        if timestamp > group["last"]:
            group["last"] = timestamp

    result_groups = []
    for category in sorted(groups):
        group = groups[category]
        total = _decimal_from_parts(group["coefficient"], group["exponent"])
        result_groups.append({
            "category": category,
            "count": group["count"],
            "total": format(total, ".2f"),
            "first": _format_utc(group["first"]),
            "last": _format_utc(group["last"]),
        })

    return {"record_count": len(records), "groups": result_groups}
