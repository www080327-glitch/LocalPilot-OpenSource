from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Record:
    timestamp: datetime
    category: str
    value: Decimal


def parse_records(text: str) -> list[Record]:
    raise NotImplementedError("Implement the public parser contract")
