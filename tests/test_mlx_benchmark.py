import unittest
from unittest.mock import Mock, patch
import io
import json
import sys
import types

from benchmarks.mlx_context import _abort_reason
from benchmarks.mlx_worker import _contextual_prompt, _mlx_peak_over_limit
from benchmarks import mlx_worker


class FakeTokenizer:
    def encode(self, text, add_special_tokens=False):
        return [1] * text.count(" x")

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        body = messages[0]["content"]
        return f"<user>{body}</user><assistant>"


class MlxPromptTests(unittest.TestCase):
    def test_synthetic_prompt_is_tokenized_near_the_requested_context(self):
        prompt, count = _contextual_prompt(FakeTokenizer(), 1)
        self.assertEqual(count, 1024)
        self.assertTrue(prompt.startswith("<user>"))
        self.assertTrue(prompt.endswith("<assistant>"))

    def test_prompt_builder_rejects_a_short_payload(self):
        class ShortTokenizer(FakeTokenizer):
            def encode(self, text, add_special_tokens=False):
                return [1] * min(text.count(" x"), 100)

        with self.assertRaisesRegex(RuntimeError, "only reached"):
            _contextual_prompt(ShortTokenizer(), 1)


class MlxMemoryGuardTests(unittest.TestCase):
    def test_default_runner_does_not_consult_system_memory_or_process_rss(self):
        with patch("benchmarks.mlx_context._system_memory", side_effect=AssertionError):
            with patch("benchmarks.mlx_context._process_rss_gb", side_effect=AssertionError):
                self.assertIsNone(_abort_reason({}, pid=123))

    def test_mlx_guard_stops_only_after_strictly_exceeding_limit(self):
        limit = 64 * 1024**3
        self.assertFalse(_mlx_peak_over_limit(limit, 64))
        self.assertTrue(_mlx_peak_over_limit(limit + 1, 64))


class MlxBackendCompatibilityTests(unittest.TestCase):
    def test_worker_uses_backend_specific_greedy_arguments_without_loading_mlx(self):
        for backend_name in ('mlx-lm', 'mlx-vlm'):
            with self.subTest(backend=backend_name):
                mlx = types.ModuleType('mlx')
                core = types.ModuleType('mlx.core')
                mlx.core = core
                core.get_peak_memory = lambda: 1024**3
                core.get_active_memory = lambda: 1024**3
                core.clear_cache = Mock()
                backend = types.ModuleType(backend_name.replace('-', '_'))
                backend.load = Mock(return_value=(object(), FakeTokenizer()))
                backend.stream_generate = Mock(return_value=iter([
                    types.SimpleNamespace(prompt_tokens=1024, generation_tokens=1)]))
                sampler = types.ModuleType('mlx_lm.sample_utils')
                sampler.make_sampler = Mock(return_value='synthetic-greedy-sampler')
                modules = {'mlx': mlx, 'mlx.core': core, backend.__name__: backend,
                           'mlx_lm.sample_utils': sampler}
                argv = ['mlx_worker', '--repo', 'synthetic/model', '--backend', backend_name,
                        '--context-k', '1', '--max-new-tokens', '16']
                with patch.dict(sys.modules, modules), patch.object(sys, 'argv', argv), \
                        patch.object(mlx_worker, '_start_mlx_peak_guard', return_value=Mock()), \
                        patch.object(mlx_worker, '_versions', return_value={}), \
                        patch('sys.stdout', new_callable=io.StringIO) as output:
                    mlx_worker.main()
                kwargs = backend.stream_generate.call_args.kwargs
                self.assertEqual(kwargs['max_tokens'], 16)
                if backend_name == 'mlx-lm':
                    self.assertNotIn('temperature', kwargs)
                    self.assertEqual(kwargs['sampler'], 'synthetic-greedy-sampler')
                    sampler.make_sampler.assert_called_once_with(temp=0.0)
                else:
                    self.assertEqual(kwargs['temperature'], 0.0)
                    self.assertNotIn('sampler', kwargs)
                record = json.loads(output.getvalue())
                self.assertEqual(record['actual_input_tokens'], 1024)
                self.assertEqual(record['max_new_tokens'], 16)


if __name__ == "__main__":
    unittest.main()
