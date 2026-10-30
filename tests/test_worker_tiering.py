"""Offline cloud tier routing, budget, and provenance checks."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent.backends import BackendCapabilities, BackendResponse, Message, ModelInfo, ToolCall
from agent.openai_backend import OpenAIWorkerBackend
from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from agent.worker_tiers import WorkerModel, configure_workers


def reply(text=None, tool=None, model=None):
    return BackendResponse(Message("assistant", text, [tool] if tool else []), model=model)


class ScriptBackend:
    capabilities = BackendCapabilities(supports_tool_calling=True)
    is_local = False

    def __init__(self, *responses, provider="fake", model="fake-model"):
        self.responses = list(responses)
        self.calls = []
        self.provider = provider
        self.model_info = ModelInfo(model, "cloud", 131072)

    def request(self, messages, **kwargs):
        self.calls.append(deepcopy(messages))
        return self.responses.pop(0)


class WorkerTierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def session(self, main, tiers=None, **kwargs):
        return AgentSession(create_default_registry(self.root), cloud_backend=main,
            cloud_worker_backends=tiers, **kwargs)

    def test_mapping_has_no_implicit_api_access(self):
        with patch.dict("os.environ", {}, clear=True):
            backends, availability = configure_workers()
        self.assertIsNone(backends["LIGHT"])
        self.assertIsNone(backends["STRONG"])
        self.assertEqual(availability["LIGHT"]["configured_model"], "gpt-6-luna")
        self.assertFalse(availability["LIGHT"]["verified_api_access"])
        self.assertEqual(WorkerModel.parse("deepseek:deepseek-flash").provider, "deepseek")
        with self.assertRaises(ValueError):
            WorkerModel.parse("unknown:model")
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "fake"}, clear=True):
            backends, availability = configure_workers({
                "LIGHT": "deepseek:deepseek-flash", "STRONG": "deepseek:deepseek-flash"})
        self.assertEqual(backends["LIGHT"].provider, "deepseek")
        self.assertTrue(availability["LIGHT"]["available"])
        self.assertFalse(availability["LIGHT"]["verified_api_access"])

    def test_openai_payload_uses_documented_function_call_mode(self):
        backend = OpenAIWorkerBackend(model="gpt-6-luna", api_key="fake")
        payload = backend._payload([Message("user", "hi")], tools=[{"type": "function"}],
                                   thinking="none", max_tokens=64, stream=True)
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["max_completion_tokens"], 64)
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertTrue(payload["stream"])
        with self.assertRaisesRegex(ValueError, "does not support"):
            backend._payload([Message("user", "hi")], tools=[{"type": "function"}], thinking="high")
        with self.assertRaises(ValueError):
            OpenAIWorkerBackend(model="unverified-model", api_key="fake")

    def test_tier_worker_requires_approval_and_reports_actual_backend(self):
        delegate = ToolCall("d1", "delegate", json.dumps({"task": "focused task",
            "backend_preference": "cloud", "tier": "LIGHT", "budget": {"steps": 20, "tools": 20, "tokens": 90000}}))
        main = ScriptBackend(reply(tool=delegate), reply("integrated"))
        worker = ScriptBackend(reply("finding", model="provider-returned-model"),
                               provider="openai", model="gpt-6-luna")
        session = self.session(main, {"LIGHT": worker},
            budgets=SessionBudgets(max_worker_steps=2, max_worker_tool_calls=1,
                                   max_worker_token_units=20000))
        self.assertEqual(session.run_turn("main task").status, "approval_required")
        self.assertFalse(worker.calls)
        self.assertEqual(session.pending_approval["tier"], "LIGHT")
        self.assertEqual(session.approve().text, "integrated")
        self.assertEqual(len(worker.calls), 1)
        self.assertTrue(any(m.content == "focused task" or '"original_task": "focused task"' in (m.content or "") for m in worker.calls[0]))
        self.assertEqual(session.subagents[0]["provider"], "openai")
        self.assertEqual(session.subagents[0]["configured_model"], "gpt-6-luna")
        self.assertEqual(session.subagents[0]["reported_models"], ["provider-returned-model"])
        tool_result = json.loads(main.calls[-1][-1].content)["result"]
        self.assertEqual(tool_result["reported_models"], ["provider-returned-model"])
        self.assertEqual(Path(session.subagents[0]["workspace"]), self.root.resolve())

    def test_unavailable_tier_returns_error_without_silent_fallback(self):
        delegate = ToolCall("d1", "delegate", json.dumps({"task": "work", "backend_preference": "cloud", "tier": "STRONG"}))
        main = ScriptBackend(reply(tool=delegate), reply("handled unavailable"))
        session = self.session(main, {"STRONG": None})
        self.assertEqual(session.run_turn("task").status, "completed")
        self.assertEqual(session.tool_history[0]["payload"]["error"]["type"], "unavailable")
        self.assertFalse(session.subagents)

    def test_local_only_blocks_tier_even_if_backend_supplied(self):
        delegate = ToolCall("d1", "delegate", json.dumps({"task": "secret", "backend_preference": "cloud", "tier": "LIGHT"}))
        class Local(ScriptBackend):
            is_local = True
            def health_check(self):
                return True
        local = Local(reply(tool=delegate), reply("blocked"), model="local")
        local.model_info = ModelInfo("local", "27B", 131072)
        worker = ScriptBackend(reply("never"))
        session = AgentSession(create_default_registry(self.root, data_policy=DataPolicy(local_only=True)),
            local_backend=local, cloud_worker_backends={"LIGHT": worker}, policy="local-only",
            data_policy=DataPolicy(local_only=True))
        self.assertEqual(session.run_turn("task").text, "blocked")
        self.assertFalse(worker.calls)


if __name__ == "__main__":
    unittest.main()
