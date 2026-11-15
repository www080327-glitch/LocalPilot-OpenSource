"""Optional historical benchmark tests are not public CI regressions."""
from pathlib import Path
from unittest import SkipTest


def require_benchmarks():
    # Never satisfy an in-tree benchmark test with an unrelated site-package.
    if not (Path(__file__).resolve().parents[1] / "benchmarks" / "__init__.py").is_file():
        raise SkipTest(
            "Historical benchmark implementation/fixtures are absent from the public source tree; NOT_RUN"
        )
