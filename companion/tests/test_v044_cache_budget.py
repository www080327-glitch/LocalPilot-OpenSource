"""Offline billing/circuit controls. These do not assert provider cache hits."""
from concurrent.futures import ThreadPoolExecutor
import tempfile
from pathlib import Path
import unittest

from companion.benchmark.cache_budget import CacheTestBudget
from companion.escalation.cache_usage import cache_usage


def usage(hit, miss):
    return cache_usage({"result":{"model_calls":[{"reported_model":"fixture", "input_tokens":hit+miss,
        "output_tokens":3,"prompt_cache_hit_tokens":hit,"prompt_cache_miss_tokens":miss}]}})


class CacheBudgetTests(unittest.TestCase):
    def test_usage_ratio_is_token_weighted_and_provider_owned(self):
        value=usage(9900,100)
        self.assertEqual(value["cache_hit_ratio"], .99)
        self.assertEqual(value["cache_miss_tokens"],100)

    def test_absent_inconsistent_or_fake_usage_is_unknown(self):
        for calls in (None,[],[{"input_tokens":100}], [{"input_tokens":5,"output_tokens":1,
                "prompt_cache_hit_tokens":100,"prompt_cache_miss_tokens":1}]):
            self.assertEqual(cache_usage({"result":{"model_calls":calls}})["status"],"UNKNOWN")

    def test_persisted_call_limit_survives_process_object_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"budget.json"
            CacheTestBudget(path).admit({"max_tokens":10,"messages":[]})
            CacheTestBudget(path).admit({"max_tokens":10,"messages":[]})
            with self.assertRaisesRegex(RuntimeError,"call_limit"):
                CacheTestBudget(path).admit({"max_tokens":10,"messages":[]})

    def test_below_99_percent_after_cold_request_halts_further_paid_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            budget=CacheTestBudget(Path(folder)/"budget.json",max_calls=10)
            budget.observe("cold",usage(0,100))
            reason=budget.observe("warm",usage(5000,5000))
            self.assertEqual(reason,"warm_cache_below_target")
            with self.assertRaisesRegex(RuntimeError,"warm_cache_below_target"):
                budget.admit({"max_tokens":10})

    def test_unknown_usage_halts_without_releasing_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            budget=CacheTestBudget(Path(folder)/"budget.json")
            budget.admit({"max_tokens":10})
            reserved=budget.state["reserved_bytes"]
            budget.observe("lost",{"status":"UNKNOWN"})
            self.assertEqual(budget.state["reserved_bytes"],reserved)
            with self.assertRaisesRegex(RuntimeError,"cache_usage_unknown"):
                CacheTestBudget(budget.path).admit({"max_tokens":10})

    def test_concurrent_admission_cannot_escape_hard_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"budget.json"
            def attempt(_):
                try:CacheTestBudget(path).admit({"max_tokens":10});return True
                except RuntimeError:return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(attempt,range(8))),2)

    def test_large_payload_is_denied_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            budget=CacheTestBudget(Path(folder)/"budget.json")
            with self.assertRaisesRegex(RuntimeError,"payload_byte_limit"):
                budget.admit({"max_tokens":10,"input":"x"*20000})
            self.assertEqual(budget.state["calls"],0)
