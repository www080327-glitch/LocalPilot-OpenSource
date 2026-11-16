from collections.abc import Sequence
from datetime import timezone
from decimal import Decimal, localcontext

from .parser import Record


def _utc_string(timestamp) -> str:
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize(records: Sequence[Record]) -> dict:
    """Summarize records by category without changing the input sequence."""
    grouped: dict[str, list[Record]] = {}
    record_count = 0
    for record in records:
        record_count += 1
        grouped.setdefault(record.category, []).append(record)

    groups = []
    for category in sorted(grouped):
        category_records = grouped[category]

        # Decimal arithmetic obeys the active context. Choose enough precision
        # for exact addition, including alignment of the input exponents and the
        # extra digits needed when summing multiple records.
        min_exponent = min(record.value.as_tuple().exponent for record in category_records)
        max_adjusted = max(record.value.adjusted() for record in category_records)
        precision = max(28, max_adjusted - min_exponent + len(str(len(category_records))) + 2)
        with localcontext() as context:
            context.prec = precision
            total = sum((record.value for record in category_records), Decimal(0))
            if total == 0:
                total = Decimal(0)
            total_text = format(total.quantize(Decimal("0.01")), ".2f")

        timestamps = [record.timestamp for record in category_records]
        first = min(timestamps).astimezone(timezone.utc)
        last = max(timestamps).astimezone(timezone.utc)
        groups.append({
            "category": category,
            "count": len(category_records),
            "total": total_text,
            "first": _utc_string(first),
            "last": _utc_string(last),
        })

    return {"record_count": record_count, "groups": groups}
