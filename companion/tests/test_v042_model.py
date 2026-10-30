"""Protocol/lifecycle controls with fake generation; real trials live in validation/."""
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from companion.model.worker import main, validate_request


def request(content="hello", **updates):
    return {"messages": [{"role": "user", "content": content}], "max_tokens": 64, "schema": None} | updates


class RequestContractTests(unittest.TestCase):
    def test_valid_multi_turn_text(self):
        data = request(messages=[{"role": "system", "content": "readonly"},
                                 {"role": "user", "content": "alpha"},
                                 {"role": "assistant", "content": "received"},
                                 {"role": "user", "content": "what was it?"}])
        self.assertIs(validate_request(data), data)

    def test_execution_and_multimodal_fields_rejected(self):
        for data in (request(tools=[]), request(messages=[{"role": "tool", "content": "data"}]),
                     request(messages=[{"role": "user", "content": [{"type": "text", "text": "data"}]}]),
                     request(messages=[{"role": "assistant", "content": "data", "tool_calls": []}])):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_request(data)

    def test_invalid_budgets_and_schemas_rejected(self):
        for budget in (0, -1, True, 64.0, 8193, None):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                validate_request(request(max_tokens=budget))
        with self.assertRaises(ValueError):
            validate_request(request(schema="commands"))

    def test_missing_user_and_late_system_rejected(self):
        for messages in ([], [{"role": "system", "content": "policy"}],
                         [{"role": "user", "content": "data"}, {"role": "system", "content": "policy"}]):
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                validate_request(request(messages=messages))

    def test_message_count_bound(self):
        with self.assertRaises(ValueError):
            validate_request(request(messages=[{"role": "user", "content": "data"}] * 129))


class WorkerLifecycleTests(unittest.TestCase):
    def simulate(self, requests, *, generation_error=False, context=8192):
        loads, caches, calls = [], [], []
        mx = types.ModuleType("mlx.core")
        mx.reset_peak_memory = lambda: None
        mx.get_active_memory = lambda: 32
        mx.get_peak_memory = lambda: 64
        mlx = types.ModuleType("mlx")
        mlx.core = mx
        lm = types.ModuleType("mlx_lm")
        tokenizer = types.SimpleNamespace(chat_template="test-chat-template")
        tokenizer.apply_chat_template = lambda messages, **kwargs: json.dumps(messages, sort_keys=True)
        tokenizer.encode = lambda text: list(range(len(text)))

        def load(*args, **kwargs):
            loads.append((args, kwargs))
            return object(), tokenizer

        def new_cache(model):
            cache = [object()]
            caches.append(cache)
            return cache

        def stream(model, tokenizer, prompt, **kwargs):
            calls.append((prompt, kwargs))
            if generation_error:
                raise RuntimeError("synthetic generation failure")
            yield types.SimpleNamespace(text="generated", finish_reason="stop", generation_tokens=1)

        lm.load, lm.stream_generate = load, stream
        sample = types.ModuleType("mlx_lm.sample_utils")
        sample.make_sampler = lambda **kwargs: kwargs
        cache_module = types.ModuleType("mlx_lm.models.cache")
        cache_module.make_prompt_cache = new_cache
        stdout = io.StringIO()
        modules = {"mlx": mlx, "mlx.core": mx, "mlx_lm": lm, "mlx_lm.sample_utils": sample,
                   "mlx_lm.models.cache": cache_module}
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "config.json").write_text("{}")
            with patch.dict(sys.modules, modules), patch("companion.model.worker.watch_parent"), \
                 patch.object(sys, "argv", ["worker", temporary, str(context)]), \
                 patch.object(sys, "stdin", io.StringIO("".join(json.dumps(r) + "\n" for r in requests))), \
                 patch.object(sys, "stdout", stdout):
                main()
        return [json.loads(line) for line in stdout.getvalue().splitlines()], loads, caches, calls

    def test_invalid_first_request_does_not_load_weights(self):
        results, loads, _, calls = self.simulate([request(max_tokens=0)])
        self.assertEqual(loads, [])
        self.assertEqual(calls, [])
        self.assertEqual(results[0]["error_stage"], "request_validation")
        self.assertEqual(results[0]["status"], "unavailable")

    def test_distinct_requests_have_distinct_cache_and_prompt_identity(self):
        results, loads, caches, calls = self.simulate([request("alpha"), request("beta")])
        self.assertEqual(len(loads), 1)
        self.assertEqual(len(calls), 2)
        self.assertIsNot(caches[0], caches[1])
        self.assertIs(calls[0][1]["prompt_cache"], caches[0])
        self.assertIs(calls[1][1]["prompt_cache"], caches[1])
        self.assertNotEqual(results[0]["prompt_sha256"], results[1]["prompt_sha256"])
        self.assertEqual(results[0]["chat_template_sha256"], results[1]["chat_template_sha256"])
        self.assertEqual([r["worker_request_number"] for r in results], [1, 2])
        self.assertTrue(all(r["cache_policy"] == "fresh_per_request" for r in results))

    def test_request_after_invalid_input_is_first_actual_generation(self):
        results, loads, caches, calls = self.simulate([request(max_tokens=0), request("hello")])
        self.assertEqual([r["status"] for r in results], ["unavailable", "ok"])
        self.assertEqual(len(loads), 1)
        self.assertEqual(len(caches), 1)
        self.assertEqual(len(calls), 1)

    def test_context_overflow_does_not_generate(self):
        results, _, caches, calls = self.simulate([request("x" * 500)], context=100)
        self.assertEqual(results[0]["error_stage"], "token_budget")
        self.assertEqual(caches, [])
        self.assertEqual(calls, [])

    def test_generation_exception_is_attributed(self):
        results, _, _, _ = self.simulate([request()], generation_error=True)
        self.assertEqual(results[0]["status"], "unavailable")
        self.assertEqual(results[0]["error_stage"], "generation")
        self.assertIn("RuntimeError", results[0]["error"])


if __name__ == "__main__":
    unittest.main()
