"""Offline checks for the persistent CLI and its entry points."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.backends import BackendCapabilities, LocalBackend
from agent.cli import EventRenderer, command, interactive
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionState


def assistant_message(content):
    return {"role": "assistant", "content": content, "tool_calls": []}


class FakeBackend:
    capabilities = BackendCapabilities(supported_thinking_efforts=("none", "low", "high", "max"),
        default_thinking_effort="high")
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append([dict(message) for message in messages])
        answer = self.answers.pop(0)
        return {"choices": [{"message": answer}], "usage": {}}


class RuntimeCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_session(self, *answers):
        backend = FakeBackend(*(assistant_message(answer) for answer in answers))
        registry = create_default_registry(self.root)
        session = AgentSession(registry, cloud_backend=backend, local_backend=LocalBackend(),
                               policy="balanced", streaming=False)
        return session, backend

    def run_cli(self, session, lines):
        iterator = iter(lines)
        prompts = []

        def input_fn(prompt):
            prompts.append(prompt)
            try:
                return next(iterator)
            except StopIteration:
                raise EOFError

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = interactive(session, EventRenderer(output=lambda *args, **kwargs: print(*args, **kwargs)),
                                 input_fn=input_fn)
        return status, output.getvalue(), prompts

    def test_two_turns_keep_context_and_exit(self):
        session, backend = self.make_session("first answer", "second answer")
        status, output, _ = self.run_cli(session, ["first task", "second task", "/exit"])
        self.assertEqual(status, 0)
        self.assertEqual(session.state, SessionState.SESSION_FINISHED)
        self.assertEqual(len(backend.calls), 2)
        second_roles_and_text = [(item["role"], item.get("content")) for item in backend.calls[1]]
        self.assertIn(("user", "first task"), second_roles_and_text)
        self.assertIn(("assistant", "first answer"), second_roles_and_text)
        self.assertIn("second answer", output)

    def test_quit_and_eof_close_the_session(self):
        for ending in ("/quit", None):
            with self.subTest(ending=ending):
                session, _ = self.make_session()
                lines = [ending] if ending else []
                self.run_cli(session, lines)
                self.assertEqual(session.state, SessionState.SESSION_FINISHED)

    def test_setting_commands_are_reachable_through_interactive_cli(self):
        session, _ = self.make_session()
        self.run_cli(session, ["/policy local-only", "/policy balanced", "/thinking high",
                               "/permissions approve-all", "/plan on", "/plan off", "/exit"])
        settings = session.settings()
        self.assertEqual(settings["policy"], "balanced")
        self.assertEqual(settings["thinking"], "high")
        self.assertEqual(settings["permissions"], "approve-all")
        self.assertFalse(settings["plan_mode"])

    def test_thinking_and_reasoning_commands_show_native_values(self):
        session, _ = self.make_session()
        info = json.loads(command(session, "/thinking"))
        self.assertEqual(info["supported_thinking_efforts"], ["none", "low", "high", "max"])
        self.assertEqual(info["default_thinking_effort"], "high")
        command(session, "/thinking none")
        command(session, "/reasoning hidden")
        self.assertEqual(session.settings()["thinking"], "none")
        self.assertEqual(session.settings()["reasoning"], "hidden")
        with self.assertRaisesRegex(ValueError, "does not support"):
            command(session, "/thinking off")

    def test_all_permission_modes_remain_visible_in_settings(self):
        session, _ = self.make_session()
        for mode in ("approve-all", "approve-mutations", "local-judge-conservative",
                     "local-judge-permissive", "full-permission"):
            command(session, f"/permissions {mode}")
            self.assertEqual(json.loads(command(session, "/settings"))["permissions"], mode)

    def test_goal_panel_shows_on_every_prompt_and_disappears_when_complete(self):
        session, _ = self.make_session("working", "finished")
        goal = session.goals.create("Publish report")
        _, output, _ = self.run_cli(session, ["first", "second", "/exit"])
        self.assertGreaterEqual(output.count("○ Publish report"), 3)
        session, _ = self.make_session()
        goal = session.goals.create("Done already")
        session.goals.update(goal.id, status="done")
        _, output, _ = self.run_cli(session, ["/goals", "/exit"])
        self.assertNotIn("活动目标：", output)
        self.assertIn("Done already", output)

    def test_goal_add_update_and_cancel_commands_work(self):
        session, _ = self.make_session()
        from agent.cli import command

        command(session, "/goals add Draft a report")
        goal = session.goals.list()[0]
        updated = command(session, f"/goals update {goal.id} blocked Waiting for input")
        self.assertIn(goal.id, updated)
        command(session, f"/goals cancel {goal.id}")
        self.assertEqual(goal.status, "cancelled")
        self.assertEqual(goal.description, "Waiting for input")

    def test_missing_backends_stop_before_interactive_prompt(self):
        from agent import __main__ as agent_cli

        output = io.StringIO()
        from agent.cloud_credentials import CloudCredentialError
        with patch.object(agent_cli, "DeepSeekBackend", side_effect=CloudCredentialError('missing_credentials')), \
             patch("builtins.input", side_effect=AssertionError("should not enter session")), \
             patch.object(agent_cli, "interactive", side_effect=AssertionError("should not enter session")), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = agent_cli.main(["--workspace", str(self.root)])
        self.assertEqual(status, 1)
        self.assertIn("Missing Credentials", output.getvalue())
        self.assertIn("云端和本地后端均不可用", output.getvalue())
        self.assertIn("--local-base-url", output.getvalue())

    def test_supported_recommendation_enters_session_with_recommended_model(self):
        import main as app
        from agent import __main__ as agent_cli

        recommendation = {
            "model": {"name": "Example 12B", "parameters_b": 12},
            "model_id": "example/model-12b", "context_length": 65536,
            "context_k": 64, "quantization": "Q4", "backend": "mlx",
            "estimated_peak_memory_gb": 8, "system_reserve_gb": 4,
            "data_source": "test", "estimate_reason": "offline fixture", "reason": "test",
        }
        captured = {}

        def enter_session(argv, *, recommendation=None):
            captured["recommendation"] = recommendation
            return agent_cli.main(["--workspace", str(self.root)], recommendation=recommendation)

        def capture_interactive(session, renderer, on_result=None):
            captured["local_model"] = session.local_backend.model_info
            session.close()
            return 0

        inputs = iter(["4", "4", "3"])
        with patch.object(app, "get_hardware", return_value={"memory": 16, "chip": "M-test",
                "computer": "Test Mac", "os": "macOS", "arch": "arm64", "platform_status": "supported"}), \
             patch.object(app, "recommend", return_value=recommendation), \
             patch.object(app, "agent_main", side_effect=enter_session), \
             patch.object(agent_cli, "DeepSeekBackend", return_value=FakeBackend()), \
             patch("builtins.input", side_effect=lambda prompt: next(inputs)), \
             patch.object(agent_cli, "interactive", side_effect=capture_interactive), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            app.main()
        self.assertIs(captured["recommendation"], recommendation)
        self.assertEqual(captured["local_model"].name, "example/model-12b")
        self.assertEqual(captured["local_model"].size_class, "12B")
        self.assertEqual(captured["local_model"].effective_context, 65536)

    def test_recommendation_default_output_is_readable_and_verbose_shows_details(self):
        import main as app
        result = {"model": {"name": "Example MoE", "parameters_b": 35},
                  "model_id": "example/moe", "context_k": 192, "quantization": "4-bit",
                  "backend": "mlx-lm", "estimated_peak_memory_gb": 50,
                  "system_reserve_gb": 3, "data_source": "estimated",
                  "estimate_reason": "RSS/allocator debug detail", "reason": "综合能力与速度。"}
        outputs = []
        for args in ([], ["--verbose"]):
            stream = io.StringIO()
            with patch.object(app, "get_hardware", return_value={"memory": 64, "chip": "M-test",
                    "computer": "Test Mac", "os": "macOS", "arch": "arm64", "platform_status": "supported"}), \
                 patch.object(app, "recommend", return_value=result), \
                 patch.object(app, "agent_main", return_value=0) as enter_session, \
                 patch("builtins.input", side_effect=["2", "8", "3"]), \
                 contextlib.redirect_stdout(stream):
                self.assertEqual(app.main(args), 0)
            self.assertNotIn("--verbose", enter_session.call_args.args[0])
            outputs.append(stream.getvalue())
        self.assertIn("建议上下文：192K（请求 256K", outputs[0])
        self.assertIn("综合能力与速度", outputs[0])
        self.assertNotIn("RSS/allocator", outputs[0])
        self.assertNotIn("估算准入包络", outputs[0])
        self.assertIn("RSS/allocator", outputs[1])

    def test_thinking_diagnostics_go_only_to_trace_but_errors_remain_visible(self):
        backend = FakeBackend(assistant_message("answer"))
        backend.thinking_mapping = lambda thinking, has_tools=False: {
            "requested": thinking, "effective": thinking, "reason": None}
        output = io.StringIO()
        trace = []
        renderer = EventRenderer(output=lambda *args, **kwargs: print(*args, file=output, **kwargs))
        session = AgentSession(create_default_registry(self.root), cloud_backend=backend,
                               local_backend=LocalBackend(), policy="balanced", streaming=False,
                               event_callback=renderer, trace=trace.append)
        result = session.run_turn("hello")
        renderer.finish(result)
        self.assertEqual(result.status, "completed")
        self.assertNotIn("thinking_mode_mapped", output.getvalue())
        self.assertTrue(any(item.get("event") == "thinking_mode_mapped" and
                            item.get("effective") == "high"
                            for item in trace))
        renderer(type("Event", (), {"type": "ErrorEvent", "data": {"message": "fatal"}})())
        self.assertIn("Agent 错误：fatal", output.getvalue())

    def test_recommendation_entry_forwards_local_backend_configuration(self):
        import main as app
        recommendation = {"model": {"name": "Example", "parameters_b": 12},
                          "model_id": "example/model", "context_length": 65536,
                          "context_k": 64, "quantization": "Q4", "backend": "mlx",
                          "estimated_peak_memory_gb": 8, "system_reserve_gb": 4,
                          "data_source": "test", "estimate_reason": "fixture", "reason": "test"}
        forwarded = ["--local-base-url", "http://127.0.0.1:1234/v1",
                     "--local-model", "loaded/model", "--policy", "local-first"]
        with patch.object(app, "get_hardware", return_value={"memory": 16, "chip": "M-test",
                "computer": "Test Mac", "os": "macOS", "arch": "arm64", "platform_status": "supported"}), \
             patch.object(app, "recommend", return_value=recommendation), \
             patch.object(app, "agent_main", return_value=0) as enter_session, \
             patch("builtins.input", side_effect=["4", "4", "3"]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(forwarded), 0)
        self.assertEqual(enter_session.call_args.args[0], ["--workspace", ".", *forwarded])
        self.assertIs(enter_session.call_args.kwargs["recommendation"], recommendation)

    def test_one_shot_entry_point_finishes_once_and_emits_debug_trace(self):
        from agent import __main__ as agent_cli

        backend = FakeBackend(assistant_message("one-shot answer"))
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(agent_cli, "DeepSeekBackend", return_value=backend), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = agent_cli.main(["--workspace", str(self.root), "--debug-trace", "answer once"])
        self.assertEqual(status, 0)
        self.assertEqual(len(backend.calls), 1)
        self.assertIn("one-shot answer", stdout.getvalue())
        trace_events = [json.loads(line)["event"] for line in stderr.getvalue().splitlines()]
        self.assertIn("assistant_final", trace_events)


if __name__ == "__main__":
    unittest.main()
