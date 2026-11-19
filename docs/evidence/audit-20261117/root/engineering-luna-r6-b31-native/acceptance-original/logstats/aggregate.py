from collections.abc import Sequence
from .parser import Record


def summarize(records: Sequence[Record]) -> dict:
    raise NotImplementedError("Implement exact aggregation")
