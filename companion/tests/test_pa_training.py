import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest

from companion.config import Config
from companion.model.finetune import prepare, execute, readiness
from companion.runtime.service import Companion


class ReviewedTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.app = Companion(Config(data_dir=str(self.root / "state"), backend="disabled",
                                   localpilot_endpoint="", low_power_policy="off"))

    def tearDown(self):
        self.app.native.stop()
        self.app.observer.stop()
        self.app.model.unload()
        self.app.channel.stop()
        self.app.store.close()
        self.app.lock.close()
        self.temp.cleanup()

    def source(self, name, text):
        path = self.root / (name + ".txt")
        path.write_text(text)
        connected = self.app.command({"command":"source_connect", "kind":"meeting", "path":str(path)})
        source_id = connected["source"]["id"]
        row = next(row for row in self.app.observation_memory.records() if row["object"]["source_id"] == source_id)
        return source_id, row["id"], path

    def add(self, question, answer, purpose="activity_qa", ids=None):
        return self.app.command({"command":"training_example_add", "question":question, "answer":answer,
                                 "purpose":purpose, "observation_ids":ids})

    def export_pair(self):
        for name, text in (("first", "First source: parser discussion."), ("second", "Second source: review schedule.")):
            _, mid, _ = self.source(name, text)
            self.add("这份记录提到什么？", text + "记录不足以证明已完成。", ids=[mid])
        return self.app.command({"command":"training_export"})

    def model(self, quantized=False):
        directory = self.root / "selected-model"
        directory.mkdir()
        (directory / "config.json").write_text(json.dumps({"model_type":"fixture", **({"quantization":{"bits":4}} if quantized else {})}))
        (directory / "tokenizer_config.json").write_text('{}')
        (directory / "model.safetensors").write_bytes(b"fixture file, not usable model weights")
        return directory

    def test_observation_and_conversation_never_automatically_become_training_labels(self):
        self.source("observed", "Only observed text")
        self.app.ask("早上好")
        self.assertEqual(self.app.command({"command":"training_examples"})["examples"], [])
        self.assertEqual(self.app.model.inferences, 0)

    def test_review_candidate_binds_exact_displayed_question_answer_and_sources(self):
        _, mid, _ = self.source('reviewed-dialogue', 'Review the parser, deployment is not verified.')
        response = self.app.ask('会议说了什么？')
        greeting = self.app.ask('晚上好')
        candidates = self.app.command({'command':'training_candidates'})['candidates']
        self.assertEqual({row['answer_id'] for row in candidates}, {response['answer_id'], greeting['answer_id']})
        review = self.app.command({'command':'training_review', 'answer_id':response['answer_id']})['candidate']
        self.assertEqual(review['question'], '会议说了什么？')
        self.assertEqual(review['answer'], response['text'])
        self.assertEqual(review['observation_ids'], [mid])
        self.assertEqual(review['sources'][0]['id'], mid)
        self.assertTrue(review['sources'][0]['locator'])
        self.assertEqual(self.app.training.list()['examples'], [])
        saved = self.app.command({'command':'training_example_add', 'answer_id':response['answer_id'],
            'purpose':review['purpose'], 'question':'这份来源提到什么？', 'answer':'记录提到讨论 parser，未证明部署完成。'})
        self.assertEqual(saved['status'], 'ok')
        example = self.app.training.list()['examples'][0]
        self.assertEqual(example['observation_ids'], [mid])
        self.assertEqual(example['answer'], '记录提到讨论 parser，未证明部署完成。')

    def test_reviewed_answer_cannot_be_saved_after_source_disable_or_file_change(self):
        source_id, _, path = self.source('review-window', 'Synthetic original text')
        response = self.app.ask('会议说了什么？')
        self.app.sources.set_enabled(source_id, False)
        for command in ('training_review', 'training_example_add'):
            value = self.app.command({'command':command, 'answer_id':response['answer_id'],
                'purpose':'activity_qa', 'question':'What was said?', 'answer':'Reviewed answer'})
            self.assertEqual(value['status'], 'unavailable')
        self.assertEqual(self.app.training.candidates()['candidates'], [])
        self.app.sources.set_enabled(source_id, True)
        path.write_text('Changed source')
        self.assertEqual(self.app.training.review(response['answer_id'])['status'], 'unavailable')
        self.assertEqual(self.app.training.list()['examples'], [])

    def test_gui_review_cannot_replace_original_source_ids_or_purpose(self):
        _, _, _ = self.source('bound', 'First original source')
        response = self.app.ask('会议说了什么？')
        _, other, _ = self.source('other', 'Other source')
        with self.assertRaisesRegex(ValueError, 'original source'):
            self.app.training.add('Question', 'Answer', 'activity_qa', [other], answer_id=response['answer_id'])
        with self.assertRaisesRegex(ValueError, 'purpose'):
            self.app.training.add('Question', 'Answer', 'greeting', answer_id=response['answer_id'])
        self.assertEqual(self.app.training.list()['examples'], [])

    def test_retention_never_exports_full_target_with_only_compressed_source_context(self):
        _, mid, _ = self.source('retained', 'Retained source body ' * 40)
        self.app.training.add('Source question', 'Explicitly reviewed target', 'activity_qa', [mid])
        self.app.observation_memory.retain(now=time.time()+86401, raw_ttl_days=1, ttl_days=30)
        self.assertEqual(self.app.observation_memory.get(mid)['raw_state'], 'compressed')
        self.assertFalse(self.app.training.list()['examples'][0]['available'])
        with self.assertRaisesRegex(ValueError, 'currently readable'):
            self.app.training.export()

    def test_memory_disabled_does_not_create_review_candidate(self):
        self.app.command({'command':'pet_memory', 'enabled':False})
        result = self.app.command({'command':'pet_ask', 'text':'早上好'})
        self.assertIsNone(result['answer_id'])
        self.assertEqual(self.app.training.candidates()['candidates'], [])

    def test_forgetting_question_removes_its_answer_from_review_and_conversation_recall(self):
        response = self.app.ask('早上好')
        rows = self.app.store.records(10, ['conversation'])
        question = next(row for row in rows if row['source'] == 'user_chat')
        answer = next(row for row in rows if row['id'] == response['answer_id'])
        self.app.command({'command':'forget', 'id':question['id']})
        self.assertEqual(self.app.training.review(response['answer_id'])['status'], 'unavailable')
        self.assertFalse(self.app.conversation_accessible(answer))

    def test_explicit_sample_is_idempotent_and_requires_current_sources(self):
        source_id, mid, _ = self.source("review", "Reviewed evidence")
        first = self.add("具体说了什么？", "来源提到 Reviewed evidence。", ids=[mid])
        again = self.add("具体说了什么？", "来源提到 Reviewed evidence。", ids=[mid])
        self.assertEqual(first["id"], again["id"])
        self.assertTrue(again["already_saved"])
        self.assertEqual(first["training"], "NOT_RUN")
        self.app.sources.set_enabled(source_id, False)
        with self.assertRaises(ValueError):
            self.add("新问题", "新答案", ids=[mid])
        saved = self.app.training.list()["examples"][0]
        self.assertFalse(saved["available"])
        self.assertIsNone(saved["answer"])

    def test_reviewed_data_rejects_credentials_and_reasoning_blocks(self):
        for answer in ("<think>hidden reasoning</think>final", "api_key=sk-abcdefghijk", '{"reasoning_content":"hidden"}'):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.add("你好", answer, purpose="greeting")
        with self.assertRaises(ValueError):
            self.add("今天做了什么", "我猜做过部署")
        self.assertEqual(self.app.training.list()["examples"], [])

    def test_export_requires_independent_groups(self):
        _, mid, _ = self.source("same-meeting", "One source")
        self.add("问题一", "答案一", ids=[mid])
        self.add("问题二", "答案二", ids=[mid])
        with self.assertRaisesRegex(ValueError, "independent"):
            self.app.training.export()

    def test_shared_and_duplicate_sources_never_cross_train_validation(self):
        _, first, _ = self.source("shared-a", "Same source text")
        _, duplicate, _ = self.source("shared-copy", "Same source text")
        _, separate, _ = self.source("separate", "Independent source text")
        one = self.add("问题一", "来源一", ids=[first])["id"]
        two = self.add("问题二", "来源二", ids=[duplicate])["id"]
        three = self.add("问题三", "来源三", ids=[separate])["id"]
        exported = self.app.training.export()
        manifest = json.loads(Path(exported["manifest"]).read_text())
        splits = {row["id"]:row["split"] for row in manifest["samples"]}
        self.assertEqual(splits[one], splits[two])
        self.assertNotEqual(splits[one], splits[three])
        self.assertEqual(manifest["source_group_count"], 2)

    def test_multisource_example_keeps_transitive_sources_in_one_group(self):
        mids = [self.source(str(n), f"Distinct source {n}")[1] for n in range(4)]
        ids = [self.add(f"问{n}", f"答{n}", ids=pair)["id"]
               for n, pair in enumerate(([mids[0]], [mids[1]], [mids[0], mids[1]], [mids[1], mids[2]], [mids[3]]))]
        manifest = json.loads(Path(self.app.training.export()["manifest"]).read_text())
        splits = {row["id"]:row["split"] for row in manifest["samples"]}
        self.assertEqual(len({splits[mid] for mid in ids[:4]}), 1)
        self.assertNotEqual(splits[ids[0]], splits[ids[4]])

    def test_export_is_reproducible_private_and_keeps_final_answer_targets_only(self):
        exported = self.export_pair()
        repeated = self.app.training.export()
        first, second = Path(exported["directory"]), Path(repeated["directory"])
        for split in ("train", "valid"):
            content = (first / (split + ".jsonl")).read_bytes()
            self.assertEqual(content, (second / (split + ".jsonl")).read_bytes())
            sample = json.loads(content)
            self.assertEqual([row["role"] for row in sample["messages"]], ["system", "user", "assistant"])
            self.assertIn("已授权来源", sample["messages"][1]["content"])
            self.assertIn("记录不足以证明", sample["messages"][-1]["content"])
            self.assertEqual((first / (split + ".jsonl")).stat().st_mode & 0o777, 0o600)
        manifest = json.loads(Path(exported["manifest"]).read_text())
        self.assertEqual(manifest["training"], "NOT_RUN")
        self.assertEqual(manifest["quality"], "NOT_EVALUATED")
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertEqual(self.app.model.inferences, 0)
        self.assertEqual(self.app.localpilot.network_calls, 0)

    def test_revoked_forgotten_and_cleared_memories_remove_bound_samples(self):
        source_id, mid, _ = self.source("one", "Source")
        self.add("问题", "答案", ids=[mid])
        result = self.app.command({"command":"source_revoke", "source_id":source_id})
        self.assertEqual(result["removed_training_examples"], 1)
        _, mid, _ = self.source("two", "Another source")
        self.add("问题", "答案", ids=[mid])
        self.app.command({"command":"forget_observation", "id":mid})
        self.assertEqual(self.app.training.list()["examples"], [])
        self.add("你好", "你好，需要时来找我。", purpose="greeting")
        self.app.command({"command":"clear", "confirmation":"DELETE_COMPANION_MEMORY"})
        self.assertEqual(self.app.training.list()["examples"], [])

    def test_export_rejects_stale_bound_source_and_invalid_split_options(self):
        self.export_pair()
        (self.root / "first.txt").write_text("Changed source")
        with self.assertRaisesRegex(ValueError, "currently readable"):
            self.app.training.export()
        for kwargs in ({"seed":True}, {"validation_fraction":float("nan")}, {"validation_fraction":.5}):
            with self.assertRaises(ValueError):
                self.app.training.export(**kwargs)

    def test_prepared_plan_uses_only_existing_local_inputs_and_exact_cli(self):
        exported, model = self.export_pair(), self.model()
        before = {path.name:path.read_bytes() for path in model.iterdir()}
        plan = prepare(model, exported["directory"], self.root / "plan")
        self.assertEqual(plan["command"][:4], [sys.executable, "-m", "mlx_lm", "lora"])
        self.assertEqual(plan["command"][4], "--config")
        config = json.loads(Path(plan["command"][-1]).read_text())
        self.assertTrue(config["mask_prompt"])
        self.assertEqual(config["lora_parameters"]["rank"], 8)
        self.assertNotIn("trust_remote_code", config)
        self.assertEqual(plan["requirements"], "mlx-lm[train]==0.31.3")
        self.assertEqual(plan["training"], "NOT_RUN")
        self.assertFalse(plan["model_weights_verified"])
        self.assertFalse(plan["model_promoted"])
        self.assertEqual(before, {path.name:path.read_bytes() for path in model.iterdir()})
        self.assertFalse((self.root / "plan" / "adapters").exists())

    def test_launcher_rejects_changed_data_output_overlap_and_custom_code(self):
        exported, model = self.export_pair(), self.model()
        with self.assertRaisesRegex(ValueError, "separate"):
            prepare(model, exported["directory"], model / "run")
        (model / "tokenizer_config.json").write_text('{"auto_map":{"AutoTokenizer":"custom.Tokenizer"}}')
        with self.assertRaisesRegex(ValueError, "auto_map"):
            prepare(model, exported["directory"], self.root / "custom")
        (model / "tokenizer_config.json").write_text('{}')
        path = Path(exported["directory"]) / "train.jsonl"
        path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, "hash"):
            prepare(model, exported["directory"], self.root / "modified")

    def test_full_training_requires_unquantized_weights_and_reports_actual_scope(self):
        exported, model = self.export_pair(), self.model(quantized=True)
        with self.assertRaisesRegex(ValueError, "unquantized"):
            prepare(model, exported["directory"], self.root / "full", method="full")
        (model / "config.json").write_text('{"model_type":"fixture"}')
        plan = prepare(model, exported["directory"], self.root / "full", method="full")
        self.assertEqual(plan["config"]["num_layers"], -1)
        self.assertIn("not_embedding_or_head", plan["training_scope"])

    def test_cli_plan_runs_without_optional_mlx_and_does_not_train(self):
        exported, model = self.export_pair(), self.model()
        result = subprocess.run([sys.executable, "-m", "companion.model.finetune", "--model", str(model),
            "--data", exported["directory"], "--output", str(self.root / "cli-plan")], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["training"], "NOT_RUN")
        self.assertFalse((self.root / "cli-plan" / "training.log").exists())

    def test_held_out_source_groups_never_enter_training_or_validation(self):
        from companion.model.reviewed_data import load_dataset
        for number in range(5):
            _, memory_id, _ = self.source(f'held-{number}', f'Unique reviewed record {number}')
            self.add(f'What does record {number} say?', f'Approved answer {number}', ids=[memory_id])
        exported = self.app.command({'command': 'training_export', 'test_fraction': .2})
        manifest, splits, _ = load_dataset(exported['directory'], require_test=True)
        self.assertEqual({name: len(rows) for name, rows in splits.items()}, {'train': 3, 'valid': 1, 'test': 1})
        owners = {}
        for row in manifest['samples']:
            for group in row['groups']:
                self.assertIn(owners.setdefault(group, row['split']), {row['split']})
        repeated = self.app.training.export(test_fraction=.2)
        for name in splits:
            first = Path(exported['directory']) / (name + '.jsonl')
            self.assertEqual(first.read_bytes(), (Path(repeated['directory']) / first.name).read_bytes())
        plan = prepare(self.model(), exported['directory'], self.root / 'held-out-plan')
        self.assertFalse(plan['config']['test'])
        self.assertEqual(plan['held_out_test'], 'reserved_not_used_by_trainer')

    def test_held_out_export_requires_three_independent_groups(self):
        self.export_pair()
        with self.assertRaisesRegex(ValueError, '3 independent'):
            self.app.training.export(test_fraction=.2)
        for fraction in (True, -.1, .5, float('nan')):
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                self.app.training.export(test_fraction=fraction)

    def test_final_evaluation_rejects_missing_changed_or_shared_test_sources(self):
        from companion.model.reviewed_data import load_dataset
        exported = self.export_pair()
        with self.assertRaisesRegex(ValueError, 'held-out test'):
            load_dataset(exported['directory'], require_test=True)
        _, mid, _ = self.source('third', 'Third independent fact')
        self.add('Third question', 'Third answer', ids=[mid])
        exported = self.app.training.export(test_fraction=.2)
        manifest_path = Path(exported['manifest'])
        manifest = json.loads(manifest_path.read_text())
        manifest['samples'][0]['groups'] = manifest['samples'][1]['groups']
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'crosses'):
            load_dataset(exported['directory'], require_test=True)
        exported = self.app.training.export(test_fraction=.2)
        test_path = Path(exported['directory']) / 'test.jsonl'
        test_path.write_text(test_path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'hash'):
            load_dataset(exported['directory'], require_test=True)

    def test_real_http_held_out_evaluation_omits_targets_and_preserves_errors(self):
        from companion.model.evaluation import evaluate, compare
        for number in range(3):
            _, mid, _ = self.source(f'eval-{number}', f'Public evaluation source {number}')
            self.add(f'Public evaluation question {number}', 'Approved concise target', ids=[mid])
        exported = self.app.training.export(test_fraction=.2)
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(request)
                if request['model'] == 'failure':
                    self.send_response(503)
                    self.end_headers()
                    return
                answer = 'Approved concise target' if request['model'] == 'candidate' else 'A different answer'
                payload = {'model': request['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': answer}}]}
                if request['model'] == 'candidate':
                    payload['usage'] = {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02))
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        endpoint = f'http://127.0.0.1:{server.server_port}/v1'
        reports = {model: evaluate(exported['directory'], endpoint, model, self.root / model)
                   for model in ('baseline', 'candidate', 'failure')}
        self.assertEqual(reports['candidate']['exact_matches'], 1)
        self.assertEqual(reports['baseline']['cases'][0]['usage'], 'UNKNOWN')
        self.assertEqual(reports['candidate']['cases'][0]['usage']['total_tokens'], 15)
        self.assertEqual(reports['failure']['status'], 'completed_with_errors')
        self.assertEqual(reports['failure']['errors'], 1)
        self.assertEqual(reports['failure']['exact_matches'], 0)
        self.assertEqual(len(requests), 3)
        for request in requests:
            self.assertEqual([message['role'] for message in request['messages']], ['system', 'user'])
            self.assertNotIn('Approved concise target', json.dumps(request))
        comparison = compare(self.root / 'baseline/evaluation.json', self.root / 'candidate/evaluation.json')
        self.assertEqual(comparison['improved_cases'], 1)
        self.assertEqual(comparison['regressed_cases'], 0)
        self.assertEqual(comparison['statistical_superiority'], 'NOT_ESTABLISHED')
        self.assertFalse(comparison['model_promoted'])
        candidate_path = self.root / 'candidate/evaluation.json'
        candidate = json.loads(candidate_path.read_text())
        candidate['max_tokens'] += 1
        candidate_path.write_text(json.dumps(candidate))
        with self.assertRaisesRegex(ValueError, 'conditions differ'):
            compare(self.root / 'baseline/evaluation.json', candidate_path)

    @unittest.skipIf(readiness()["ready"], "This check exercises genuinely unavailable training prerequisites")
    def test_execution_without_prerequisites_truthfully_stays_not_run(self):
        exported, model = self.export_pair(), self.model()
        plan = execute(prepare(model, exported["directory"], self.root / "missing-prerequisites"))
        self.assertEqual(plan["status"], "not_run")
        self.assertEqual(plan["training"], "NOT_RUN")
        self.assertFalse(plan["readiness"]["ready"])
        self.assertFalse((self.root / "missing-prerequisites" / "training.log").exists())


if __name__ == "__main__":
    unittest.main()
