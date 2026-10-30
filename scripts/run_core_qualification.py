"""File-backed unittest entry point: macOS spawn workers can import __main__."""
import argparse
import json
from pathlib import Path
import sys
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    report = {'run': result.testsRun,
              'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': [{'test': str(test), 'reason': reason} for test, reason in result.skipped],
              'main_entry': str(Path(__file__).resolve()), 'spawn_safe_entry': True}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: len(value) if key == 'skipped' else value for key, value in report.items()}))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
