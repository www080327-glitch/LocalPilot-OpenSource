import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from logstats.parser import Record, parse_records
from logstats.aggregate import summarize

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'fixtures'


class ParserTests(unittest.TestCase):
    def test_quoting_blank_lines_and_utc(self):
        rows = parse_records((FIXTURES / 'basic.csv').read_text(encoding='utf-8'))
        self.assertEqual(rows, [
            Record(datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc), 'east, priority', Decimal('0.10')),
            Record(datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc), 'west "desk"', Decimal('-2.50')),
            Record(datetime(2026, 1, 1, 23, 45, tzinfo=timezone.utc), 'east, priority', Decimal('0.20'))])
        self.assertTrue(all(isinstance(row.value, Decimal) for row in rows))
        self.assertTrue(all(row.timestamp.tzinfo is timezone.utc for row in rows))

    def test_trim_fields_and_multiline_category(self):
        rows = parse_records('\n timestamp , category , value \n2026-01-01T00:00:00Z," line\nname ", +2.5 \n')
        self.assertEqual(rows, [Record(datetime(2026, 1, 1, tzinfo=timezone.utc), 'line\nname', Decimal('2.5'))])

    def test_header_only(self):
        self.assertEqual(parse_records('\n timestamp,category,value\n \n'), [])

    def test_header_errors(self):
        for text in ('', '\n\n', 'category,timestamp,value\n', 'timestamp,category,value,extra\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, r'^row \d+:'):
                parse_records(text)

    def test_invalid_values(self):
        for value in ('NaN', 'Infinity', '1e3', '1.234', '', '.', '1.', '１２'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, r'^row 2:'):
                parse_records('timestamp,category,value\n2026-01-01T00:00:00Z,a,' + value + '\n')

    def test_invalid_timestamp_and_category(self):
        for row in ('2026-01-01T00:00:00,a,1', '2026-02-30T00:00:00Z,a,1',
                    '2026-01-01T00:00:00.5Z,a,1', '2026-01-01T00:00:00Z,  ,1'):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, r'^row 2:'):
                parse_records('timestamp,category,value\n' + row + '\n')

    def test_field_counts_and_empty_fields(self):
        for row in ('2026-01-01T00:00:00Z,a', '2026-01-01T00:00:00Z,a,1,extra', ',,'):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, r'^row 2:'):
                parse_records('timestamp,category,value\n' + row + '\n')

    def test_row_number_after_blanks(self):
        with self.assertRaisesRegex(ValueError, r'^row 4:'):
            parse_records('timestamp,category,value\n\n \n2026-01-01T00:00:00Z,a,bad\n')

    def test_malformed_csv(self):
        with self.assertRaisesRegex(ValueError, r'^row 2:'):
            parse_records('timestamp,category,value\n2026-01-01T00:00:00Z,"unfinished,1')


class AggregateTests(unittest.TestCase):
    def test_exact_totals_and_sorting(self):
        rows = [Record(datetime(2026, 1, 2, tzinfo=timezone.utc), 'z', Decimal('9007199254740993.01')),
                Record(datetime(2026, 1, 1, tzinfo=timezone.utc), 'A', Decimal('0.10')),
                Record(datetime(2026, 1, 3, tzinfo=timezone.utc), 'z', Decimal('0.09')),
                Record(datetime(2026, 1, 4, tzinfo=timezone.utc), 'A', Decimal('0.20'))]
        self.assertEqual(summarize(rows), {'record_count': 4, 'groups': [
            {'category': 'A', 'count': 2, 'total': '0.30', 'first': '2026-01-01T00:00:00Z', 'last': '2026-01-04T00:00:00Z'},
            {'category': 'z', 'count': 2, 'total': '9007199254740993.10', 'first': '2026-01-02T00:00:00Z', 'last': '2026-01-03T00:00:00Z'}]})

    def test_order_independence_and_no_mutation(self):
        rows = [Record(datetime(2026, 1, 2, tzinfo=timezone.utc), 'b', Decimal('-1.25')),
                Record(datetime(2026, 1, 1, tzinfo=timezone.utc), 'b', Decimal('1.25'))]
        before = list(rows)
        expected = {'record_count': 2, 'groups': [
            {'category': 'b', 'count': 2, 'total': '0.00', 'first': '2026-01-01T00:00:00Z', 'last': '2026-01-02T00:00:00Z'}]}
        self.assertEqual(summarize(rows), expected)
        self.assertEqual(rows, before)
        self.assertEqual(summarize(tuple(reversed(rows))), expected)

    def test_empty(self):
        self.assertEqual(summarize([]), {'record_count': 0, 'groups': []})


class CLITests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, '-S', '-m', 'logstats', *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, timeout=10)

    def test_stdout_json(self):
        result = self.invoke(FIXTURES / 'basic.csv')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), json.loads((FIXTURES / 'basic.expected.json').read_text()))
        self.assertTrue(result.stdout.endswith('\n'))
        self.assertEqual(result.stderr, '')

    def test_precision_and_unicode_file_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            result = self.invoke(FIXTURES / 'precision.csv', '--output', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text(encoding='utf-8')
            self.assertEqual(json.loads(text), json.loads((FIXTURES / 'precision.expected.json').read_text(encoding='utf-8')))
            self.assertTrue(text.endswith('\n'))
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, '')

    def test_empty_input_dataset(self):
        result = self.invoke(FIXTURES / 'empty.csv')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'record_count': 0, 'groups': []})

    def test_invalid_row_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            output.write_text('existing output\n')
            result = self.invoke(FIXTURES / 'invalid.csv', '--output', output)
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r'^error: row 2:')
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(output.read_text(), 'existing output\n')

    def test_missing_file(self):
        result = self.invoke(FIXTURES / 'missing.csv')
        self.assertEqual(result.returncode, 2)
        self.assertRegex(result.stderr, r'^error: ')
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
