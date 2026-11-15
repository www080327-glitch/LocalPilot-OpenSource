"""Run the same public deterministic controls in the full regression suite."""
from tests.optional_benchmarks import require_benchmarks
require_benchmarks()

from benchmarks.runtime_control_cases import RuntimeStabilizationControls
