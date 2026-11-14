"""Optional historical benchmark tests are not public CI regressions."""
from importlib.util import find_spec
from unittest import SkipTest


def require_benchmarks():
    if find_spec("benchmarks") is None:
        raise SkipTest(
            "Historical benchmark implementation/fixtures are absent from the public source tree; NOT_RUN"
        )
