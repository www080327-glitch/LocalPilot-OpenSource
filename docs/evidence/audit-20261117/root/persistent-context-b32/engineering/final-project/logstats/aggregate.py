from collections.abc import Sequence
from datetime import timezone
from decimal import Decimal, localcontext

from .parser import Record


def _decimal_from_parts(coefficient: int, exponent: int) -> Decimal:
    """Build a Decimal without applying the active decimal context."""
    sign = int(coefficient < 0)
    digits = tuple(int(digit) for digit in str(abs(coefficient)))
    return Decimal((sign, digits, exponent))


def _format_total(coefficient: int, exponent: int) -> str:
    total = _decimal_from_parts(coefficient, exponent)
    # Give quantize enough precision for the whole-number portion, even when
    # the input contains values far larger than the default Decimal context.
    precision = max(28, len(total.as_tuple().digits), total.adjusted() + 4)
    with localcontext() as context:
        context.prec = precision
        return format(total.quantize(Decimal("0.01")), "f")


def _utc_string(timestamp) -> str:
    utc_timestamp = timestamp.astimezone(timezone.utc)
    return utc_timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def summarize(records: Sequence[Record]) -> dict:
    """Return exact per-category counts, totals, and timestamp ranges."""
    groups = {}

    for record in records:
        value = record.value
        parts = value.as_tuple()
        if not value.is_finite():
            raise ValueError("record values must be finite Decimals")

        coefficient = int("".join(str(digit) for digit in parts.digits) or "0")
        if parts.sign:
            coefficient = -coefficient

        group = groups.get(record.category)
        if group is None:
            groups[record.category] = {
                "count": 1,
                "coefficient": coefficient,
                "exponent": parts.exponent,
                "first": record.timestamp,
                "last": record.timestamp,
            }
            continue

        # Align integer coefficients to a shared decimal exponent. Integer
        # arithmetic avoids rounding from the process-wide Decimal context.
        exponent = min(group["exponent"], parts.exponent)
        group["coefficient"] = (
            group["coefficient"] * 10 ** (group["exponent"] - exponent)
            + coefficient * 10 ** (parts.exponent - exponent)
        )
        group["exponent"] = exponent
        group["count"] += 1
        if record.timestamp < group["first"]:
            group["first"] = record.timestamp
        if record.timestamp > group["last"]:
            group["last"] = record.timestamp

    result_groups = []
    for category in sorted(groups):
        group = groups[category]
        result_groups.append({
            "category": category,
            "count": group["count"],
            "total": _format_total(group["coefficient"], group["exponent"]),
            "first": _utc_string(group["first"]),
            "last": _utc_string(group["last"]),
        })

    return {"record_count": sum(group["count"] for group in groups.values()),
            "groups": result_groups}
