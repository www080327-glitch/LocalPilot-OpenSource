import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from companion.config import Config
from companion.model.portable_training import execute, prepare, readiness
from companion.runtime.service import Companion


def tiny_local_model(directory):
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import WhitespaceSplit
    from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(17)
    words = ['<pad>', '<eos>', '<unk>', 'system', 'user', 'assistant', 'Source',
             'one', 'two', 'three', 'Evidence', 'Answer', 'Question', 'reviewed']
    backend = Tokenizer(WordLevel(dict(zip(words, range(len(words)))), unk_token='<unk>'))
    backend.pre_tokenizer = WhitespaceSplit()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=backend, pad_token='<pad>',
                                       eos_token='<eos>', unk_token='<unk>')
    tokenizer.chat_template = "{% for message in messages %}{{ message['role'] + ' ' + message['content'] + ' <eos> ' }}{% endfor %}{% if add_generation_prompt %}{{ 'assistant ' }}{% endif %}"
    tokenizer.save_pretrained(directory)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=len(words), hidden_size=32,
        intermediate_size=48, num_hidden_layers=2, num_attention_heads=2,
        num_key_value_heads=2, max_position_embeddings=1024, tie_word_embeddings=False,
        pad_token_id=0, eos_token_id=1))
    model.save_pretrained(directory, safe_serialization=True)
    return tokenizer


def reviewed_dataset(directory):
    app = Companion(Config(data_dir=str(directory / 'state'), backend='disabled',
                           localpilot_endpoint='', low_power_policy='off'))
    try:
        for name in ('one', 'two', 'three'):
            path = directory / (name + '.txt')
            path.write_text('Source ' + name)
            source = app.command({'command': 'source_connect', 'kind': 'meeting', 'path': str(path)})['source']['id']
            observation = next(row['id'] for row in app.observation_memory.records()
                               if row['object']['source_id'] == source)
            app.training.add('Question ' + name, 'Answer ' + name, 'activity_qa', [observation])
        return Path(app.training.export(test_fraction=.2)['directory'])
    finally:
        app.native.stop()
        app.observer.stop()
        app.model.unload()
        app.channel.stop()
        app.store.close()
        app.lock.close()


@unittest.skipUnless(readiness()['ready'], 'Optional pinned Linux Torch/Transformers/PEFT training environment is not installed')
class PortableTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.model = cls.root / 'model'
        cls.tokenizer = tiny_local_model(cls.model)
        cls.dataset = reviewed_dataset(cls.root)
        cls.base_hash = hashlib.sha256((cls.model / 'model.safetensors').read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def train(self, method):
        plan = prepare(self.model, self.dataset, self.root / method, method=method,
                       layers=-1, iterations=3, rank=2, learning_rate=.003, max_seq_length=1024)
        result = execute(plan)
        self.assertEqual(result['status'], 'completed', Path(result['log']).read_text())
        self.assertEqual(result['metrics']['device'], 'cpu')
        self.assertEqual(len(result['metrics']['steps']), 3)
        self.assertFalse(result['metrics']['held_out_test_used'])
        self.assertEqual(result['held_out_test'], 'reserved_not_used_by_trainer')
        self.assertEqual(result['quality'], 'NOT_EVALUATED')
        self.assertFalse(result['model_promoted'])
        self.assertEqual(hashlib.sha256((self.model / 'model.safetensors').read_bytes()).hexdigest(), self.base_hash)
        return result

    def test_real_cpu_lora_updates_adapter_and_loads_again(self):
        import torch
        from safetensors.torch import load_file
        from transformers import AutoModelForCausalLM
        from peft import PeftModel
        result = self.train('lora')
        weights = load_file(str(Path(result['candidate_directory']) / 'adapter_model.safetensors'))
        self.assertTrue(any(bool(torch.count_nonzero(value)) for key, value in weights.items() if 'lora_B' in key))
        self.assertFalse(result['metrics']['all_parameters_trainable'])
        loaded = PeftModel.from_pretrained(AutoModelForCausalLM.from_pretrained(self.model), result['candidate_directory'])
        self.assertTrue(torch.isfinite(loaded(input_ids=torch.tensor([[3, 6, 7]])).logits).all())

    def test_real_full_training_updates_embedding_and_head(self):
        import torch
        from safetensors.torch import load_file
        result = self.train('full')
        base = load_file(str(self.model / 'model.safetensors'))
        candidate = load_file(str(Path(result['candidate_directory']) / 'model.safetensors'))
        self.assertTrue(result['metrics']['all_parameters_trainable'])
        for name in ('model.embed_tokens.weight', 'lm_head.weight'):
            self.assertFalse(torch.equal(base[name], candidate[name]), name)

    def test_real_cpu_lora_updates_only_last_selected_transformer_layer(self):
        import torch
        from safetensors.torch import load_file
        plan = prepare(self.model, self.dataset, self.root / 'lora-last-layer', method='lora',
                       layers=1, iterations=3, rank=2, learning_rate=.003, max_seq_length=1024)
        result = execute(plan)
        self.assertEqual(result['status'], 'completed', Path(result['log']).read_text())
        candidate = Path(result['candidate_directory'])
        config = json.loads((candidate / 'adapter_config.json').read_text())
        self.assertEqual(config['layers_to_transform'], [1])
        weights = load_file(str(candidate / 'adapter_model.safetensors'))
        self.assertEqual(len(weights), 14)
        self.assertTrue(all('.layers.1.' in key and '.lora_' in key for key in weights))
        self.assertTrue(any(bool(torch.count_nonzero(value)) for key, value in weights.items() if 'lora_B' in key))
        self.assertEqual(hashlib.sha256((self.model / 'model.safetensors').read_bytes()).hexdigest(), self.base_hash)

    def test_only_answer_tokens_contribute_and_long_examples_are_not_truncated(self):
        from companion.model.torch_training_worker import _tokens, _batch
        messages = [{'role': 'system', 'content': 'reviewed'}, {'role': 'user', 'content': 'Question'},
                    {'role': 'assistant', 'content': 'Answer one'}]
        sample = _tokens(messages, self.tokenizer, 128)
        boundary = len(self.tokenizer.apply_chat_template(messages[:-1], add_generation_prompt=True))
        self.assertEqual(sample['labels'][:boundary], [-100] * boundary)
        self.assertEqual(sample['labels'][boundary:], sample['input_ids'][boundary:])
        short = _tokens(messages[:-1] + [{'role': 'assistant', 'content': 'Answer'}], self.tokenizer, 128)
        batch = _batch([sample, short], self.tokenizer.pad_token_id, 'cpu')
        self.assertEqual(int(batch['labels'][1, -1]), -100)
        with self.assertRaisesRegex(ValueError, 'does not fit'):
            _tokens(messages, self.tokenizer, len(sample['input_ids']) - 1)

    def test_full_training_rejects_partial_layers_and_unavailable_accelerator_is_explicit(self):
        import torch
        with self.assertRaisesRegex(ValueError, 'all parameters'):
            prepare(self.model, self.dataset, self.root / 'partial', method='full', layers=1)
        if not torch.cuda.is_available():
            plan = prepare(self.model, self.dataset, self.root / 'cuda', device='cuda', layers=1, iterations=1)
            result = execute(plan)
            self.assertEqual(result['training'], 'FAILED')
            self.assertIn('CUDA device is unavailable', Path(result['log']).read_text())
            self.assertFalse((self.root / 'cuda' / 'candidate').exists())


if __name__ == '__main__':
    unittest.main()
