"""Independent verifier qualification; never counted as real-model success."""
import json
from pathlib import Path
import tempfile
import unittest
from benchmarks.v48_tasks import build,corpus,verify_artifacts,code_good

class V48BenchmarkTests(unittest.TestCase):
    def test_corpus_split_and_scope(self):
        rows=corpus()
        self.assertEqual(len(rows),40)
        self.assertEqual(len({s['id'] for s in rows}),40)
        self.assertEqual(sum(s['split']=='final_evaluation' for s in rows),20)
        for s in rows:
            self.assertEqual(set(s['oracle']),set(s['output_paths']))
            self.assertIn('TASK.txt',s['public_files'])
            self.assertTrue(all('..' not in Path(p).parts for p in s['public_files']))

    def test_all_family_oracles_and_input_integrity(self):
        sources={'units.py':'def to_seconds(minutes):\n    return minutes * 60\n',
            'billing.py':'def net_cents(gross_cents, discount_cents):\n    return max(0, gross_cents - discount_cents)\n',
            'stats.py':'def median(values):\n    ordered = sorted(values)\n    n = len(ordered)\n    if n % 2:\n        return ordered[n // 2]\n    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2\n'}
        for spec in corpus():
            with self.subTest(task=spec['id']),tempfile.TemporaryDirectory() as d:
                root=Path(d)
                for p,t in spec['public_files'].items():(root/p).write_text(t)
                for p,answer in spec['oracle'].items():
                    if 'text' in answer:text=answer['text']
                    elif 'functions' in answer:
                        n=spec['seed']%19+3
                        more={'shipping.py':f'def shipping_cents(weight_grams):\n    return {n*100} + max(0, (weight_grams - 1000 + 999) // 1000) * {n*7}\n',
                            'eligibility.py':f'def eligible(age, score):\n    return age >= {18+spec["seed"]%3} and score >= {50+n}\n',
                            'ranges.py':'def contains(start, end, timestamp):\n    return start <= timestamp < end\n',
                            'clamp.py':'def clamp(value, low, high):\n    return max(low, min(high, value))\n'}
                        text={**sources,**more}[p]
                    elif 'review' in answer:text=json.dumps({'issues':[{'function':f,**v,'reason':'The boundary violates the declared contract.'} for f,v in answer['review'].items()]})
                    else:text=json.dumps(answer['json'])
                    (root/p).write_text(text)
                self.assertTrue(all(verify_artifacts(spec,root).values()))
                (root/'TASK.txt').write_text('changed')
                self.assertFalse(verify_artifacts(spec,root)['input:TASK.txt'])
                (root/'unexpected.txt').write_text('extra')
                self.assertFalse(verify_artifacts(spec,root)['scope'])

    def test_wrong_code_and_unsafe_code_rejected_without_execution(self):
        expected={'f':[[[2],4],[[0],0],[[-3],-6]]}
        self.assertTrue(code_good('def f(x):\n    return x * 2\n',expected))
        self.assertFalse(code_good('def f(x):\n    return x + 2\n',expected))
        self.assertFalse(code_good('import os\ndef f(x):\n    return x * 2\n',expected))
        with self.assertRaises(ValueError):code_good('def f(x):\n    return open("outside")\n',expected)

    def test_python_list_constructor_and_short_circuit_operand_semantics(self):
        vectors={'rotate_right':[[[v],v[-1:]+v[:-1]] for v in [[],[1],[1,2],[1,2,3]]]}
        self.assertTrue(code_good('def rotate_right(values):\n    if len(values) < 2:\n        return list(values)\n    return [values[-1]] + list(values[:-1])\n',vectors))
        self.assertTrue(code_good('def rotate_right(values):\n    return values and values[-1:] + values[:-1]\n',vectors))
        self.assertTrue(code_good('def f(x):\n    return x and 10 / x\n',{'f':[[[0],0],[[2],5]]}))
        self.assertFalse(code_good('def f(x):\n    return x > 0 and x\n',{'f':[[[2],True],[[-1],False]]}))

    def test_long_project_behavior_and_boundary_counterexample(self):
        from benchmarks.v48_long import behavior,qualify
        sources={
            'normalize.py':'def clean_label(label):\n    return label.strip().lower()\n',
            'window.py':'def contains(start, end, timestamp):\n    return start <= timestamp < end\n',
            'aggregate.py':'def weighted_average(rows):\n    total = sum(weight for value, weight in rows)\n    return sum(value * weight for value, weight in rows) / total if total else None\n',
            'quantile.py':'def percentile(values, p):\n    if not values:\n        return None\n    ordered = sorted(values)\n    rank = p * (len(ordered) - 1)\n    low = int(rank)\n    high = min(low + 1, len(ordered) - 1)\n    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)\n',
            'pipeline.py':'from normalize import clean_label\nfrom window import contains\nfrom aggregate import weighted_average\nfrom quantile import percentile\ndef summarize(rows, start, end):\n    groups = {}\n    count = 0\n    for row in rows:\n        if contains(start, end, row["timestamp"]) and row["weight"] > 0:\n            groups.setdefault(clean_label(row["label"]), []).append(row)\n            count += 1\n    result = {}\n    for label, group in groups.items():\n        pairs = [(r["value"], r["weight"]) for r in group]\n        result[label] = {"weight":sum(r["weight"] for r in group), "mean":weighted_average(pairs), "p50":percentile([r["value"] for r in group], 0.5)}\n    return {"count":count,"groups":result}\n'}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for p,t in sources.items():(root/p).write_text(t)
            self.assertTrue(behavior(root)[0])
            self.assertFalse((root/'__pycache__').exists())
            (root/'window.py').write_text(sources['window.py'].replace('timestamp < end','timestamp <= end'))
            self.assertFalse(behavior(root)[0])
        self.assertFalse(qualify('import os\nos.remove("outside")\n'))
        self.assertFalse(qualify('def f():\n    return open("outside").read()\n'))
        self.assertFalse(qualify('def f():\n    handlers = {"writer":open}\n    handlers["writer"]("outside", "w")\n'))

    def test_unseen_worker_bound_corpus_oracles(self):
        from benchmarks.v48_qualified_corpus import definitions
        data=definitions(corpus())
        self.assertEqual(len(data),20)
        for spec in data:
            with self.subTest(task=spec['id']),tempfile.TemporaryDirectory() as d:
                root=Path(d);n=spec['seed']%19+3
                sources={'shipping.py':f'def shipping_cents(weight_grams):\n    return {n*100} + max(0, (weight_grams - 1000 + 999) // 1000) * {n*7}\n',
                    'eligibility.py':f'def eligible(age, score):\n    return age >= {18+spec["seed"]%3} and score >= {50+n}\n',
                    'limits.py':'def within_limit(value, limit):\n    return 0 <= value <= limit\n',
                    'distance.py':'def manhattan(a, b):\n    return abs(a[0] - b[0]) + abs(a[1] - b[1])\n'}
                for p,t in spec['public_files'].items():(root/p).write_text(t)
                for p,a in spec['oracle'].items():
                    if 'text' in a:text=a['text']
                    elif 'functions' in a:text=sources[p]
                    elif 'review' in a:text=json.dumps({'issues':[{'function':f,**v,'reason':'The declared boundary or absolute-distance contract is violated.'} for f,v in a['review'].items()]})
                    else:text=json.dumps(a['json'])
                    (root/p).write_text(text)
                self.assertTrue(all(verify_artifacts(spec,root).values()))

    def test_unseen_confirmation_oracles_reject_initial_states(self):
        from benchmarks.v48_confirmation_corpus import definitions
        data=definitions();self.assertEqual(len(data),20)
        self.assertEqual(len({s['id'] for s in data}),20)
        for spec in data:
            with self.subTest(task=spec['id']),tempfile.TemporaryDirectory() as d:
                root=Path(d);n=7+spec['seed']%13
                sources={'tax.py':f'def tax_cents(subtotal_cents):\n    return (subtotal_cents * {n+3} + 99) // 100\n',
                    'ratio.py':'def percentage(part, whole):\n    return 100 * part / whole\n',
                    'magnitude.py':'def clipped_magnitude(value, cap):\n    return min(abs(value), cap)\n',
                    'rotation.py':'def rotate_right(values):\n    return values[-1:] + values[:-1]\n'}
                for p,t in spec['public_files'].items():(root/p).write_text(t)
                self.assertFalse(all(verify_artifacts(spec,root).values()))
                for p,a in spec['oracle'].items():
                    if 'text' in a:text=a['text']
                    elif 'functions' in a:text=sources[p]
                    elif 'review' in a:text=json.dumps({'issues':[{'function':f,**v,'reason':'The supplied witness violates the public boundary or capping contract.'} for f,v in a['review'].items()]})
                    else:text=json.dumps(a['json'])
                    (root/p).write_text(text)
                self.assertTrue(all(verify_artifacts(spec,root).values()))
                (root/'TASK.txt').write_text('changed')
                self.assertFalse(verify_artifacts(spec,root)['input:TASK.txt'])

    def test_second_confirmation_public_subset_and_oracles(self):
        from benchmarks.v48_second_confirmation import definitions
        data=definitions();self.assertEqual(len(data),20)
        sources={'blocks.py':'def started_blocks(count, block_size):\n    return (count + block_size - 1) // block_size\n',
            'temperature.py':'def to_celsius(fahrenheit):\n    return (fahrenheit - 32) * 5 / 9\n',
            'box.py':'def inside_box(point, low, high):\n    return low[0] <= point[0] <= high[0] and low[1] <= point[1] <= high[1]\n',
            'sign.py':'def sign(value):\n    return -1 if value < 0 else 1 if value > 0 else 0\n'}
        for spec in data:
            with self.subTest(task=spec['id']),tempfile.TemporaryDirectory() as d:
                root=Path(d)
                for p,t in spec['public_files'].items():(root/p).write_text(t)
                self.assertFalse(all(verify_artifacts(spec,root).values()))
                for p,a in spec['oracle'].items():
                    if 'text' in a:text=a['text']
                    elif 'functions' in a:text=sources[p]
                    elif 'review' in a:text=json.dumps({'issues':[{'function':f,**v,'reason':'The public boundary or clipping contract is violated.'} for f,v in a['review'].items()]})
                    else:text=json.dumps(a['json'])
                    (root/p).write_text(text)
                self.assertTrue(all(verify_artifacts(spec,root).values()))

if __name__=='__main__':unittest.main()
