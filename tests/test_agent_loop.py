import json
import tempfile
import unittest
from pathlib import Path

from agent.loop import Agent, MaxStepsExceeded
from agent.registry import create_default_registry


def assistant_message(content=None, tool_calls=None):
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or []}


def tool_call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class FakeBackend:
    def __init__(self, *messages):
        self.messages = list(messages)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        next_message = self.messages.pop(0)
        return {
            "choices": [{"message": next_message}],
            "usage": {"prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 12},
        }


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "notes.txt").write_text("workspace fact", encoding="utf-8")
        self.registry = create_default_registry(self.root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_direct_answer(self):
        backend = FakeBackend(assistant_message("Hello"))
        result = Agent(backend, self.registry).run("Say hello")
        self.assertEqual(result.text, "Hello")
        self.assertEqual(result.total_steps, 1)
        self.assertEqual(result.total_tool_calls, 0)
        self.assertEqual(result.model_calls[0].prompt_cache_hit_tokens, 4)
        self.assertEqual(result.model_calls[0].prompt_cache_miss_tokens, 12)
        self.assertEqual(result.usage_summary()["cache"], {
            "status": "available", "hit_tokens": 4, "miss_tokens": 12, "hit_ratio": 0.25
        })
        self.assertEqual([m["role"] for m in result.messages], ["system", "user", "assistant"])

    def test_minimal_mode_does_not_inject_standard_system_prompt(self):
        backend = FakeBackend(assistant_message("Hello"))
        result = Agent(backend, self.registry, minimal_mode=True).run("Say hello")
        self.assertEqual([message["role"] for message in result.messages], ["user", "assistant"])
        self.assertEqual(backend.calls[0]["messages"][0], {"role": "user", "content": "Say hello"})
        self.assertEqual(result.usage_summary()["prompt_version"], "minimal_0-v0.1")

    def test_single_tool_call_returns_tool_result_to_model(self):
        backend = FakeBackend(
            assistant_message(tool_calls=[tool_call("call-1", "read_file", '{"path":"notes.txt"}')]),
            assistant_message("The file says workspace fact."),
        )
        result = Agent(backend, self.registry).run("Read notes.txt")
        self.assertEqual(result.text, "The file says workspace fact.")
        self.assertEqual(result.total_tool_calls, 1)
        tool_result = result.messages[-2]
        self.assertEqual(tool_result["role"], "tool")
        self.assertEqual(tool_result["tool_call_id"], "call-1")
        self.assertEqual(json.loads(tool_result["content"]), {"ok": True, "result": "workspace fact"})
        self.assertEqual(result.messages[-1]["role"], "assistant")

    def test_multi_step_tool_calls_keep_append_only_history(self):
        backend = FakeBackend(
            assistant_message(tool_calls=[tool_call("call-1", "list_directory", '{"path":"."}')]),
            assistant_message(tool_calls=[tool_call("call-2", "read_file", '{"path":"notes.txt"}')]),
            assistant_message("I listed the workspace and read the note."),
        )
        result = Agent(backend, self.registry).run("Inspect the note")
        self.assertEqual(result.total_steps, 3)
        self.assertEqual(result.total_tool_calls, 2)
        self.assertEqual(result.text, "I listed the workspace and read the note.")
        self.assertEqual([m["role"] for m in result.messages], [
            "system", "user", "assistant", "tool", "assistant", "tool", "assistant"
        ])
        self.assertEqual(len(backend.calls[-1]["messages"]), len(result.messages) - 1)

    def test_tool_exception_is_returned_and_model_can_recover(self):
        backend = FakeBackend(
            assistant_message(tool_calls=[tool_call("call-1", "read_file", '{"path":"missing.txt"}')]),
            assistant_message("The file is missing, so I cannot summarize it."),
        )
        result = Agent(backend, self.registry).run("Read missing.txt")
        error_result = json.loads(result.messages[-2]["content"])
        self.assertFalse(error_result["ok"])
        self.assertEqual(error_result["error"]["type"], "FileNotFoundError")
        self.assertIn("missing.txt", backend.calls[1]["messages"][-1]["content"])
        self.assertIn("cannot summarize", result.text)

    def test_optional_trace_summarizes_results_without_file_content(self):
        trace = []
        backend = FakeBackend(
            assistant_message(tool_calls=[tool_call("call-1", "read_file", '{"path":"notes.txt"}')]),
            assistant_message("Done."),
        )
        Agent(backend, self.registry, trace=trace.append).run("Read notes.txt")
        serialized = json.dumps(trace)
        self.assertIn("tool_result", serialized)
        self.assertIn("result_chars", serialized)
        self.assertNotIn("workspace fact", serialized)

    def test_cache_fields_are_unavailable_when_provider_omits_them(self):
        backend = FakeBackend(assistant_message("answer"))
        backend.chat = lambda messages, tools=None: {"choices": [{"message": assistant_message("answer")}], "usage": {}}
        result = Agent(backend, self.registry).run("Say hello")
        self.assertEqual(result.usage_summary()["cache"], {
            "status": "unavailable", "hit_tokens": None, "miss_tokens": None, "hit_ratio": None
        })

    def test_invalid_json_arguments_and_unknown_tool_are_recoverable(self):
        backend = FakeBackend(
            assistant_message(tool_calls=[
                tool_call("bad-json", "read_file", "{not json"),
                tool_call("unknown", "not_registered", "{}"),
            ]),
            assistant_message("I recovered from both tool errors."),
        )
        result = Agent(backend, self.registry).run("Try these calls")
        errors = [json.loads(message["content"]) for message in result.messages if message["role"] == "tool"]
        self.assertEqual(errors[0]["error"]["type"], "invalid_json_arguments")
        self.assertEqual(errors[1]["error"]["type"], "ValueError")
        self.assertEqual([m["tool_call_id"] for m in result.messages if m["role"] == "tool"], [
            "bad-json", "unknown"
        ])

    def test_max_steps_stops_before_unbounded_loop(self):
        backend = FakeBackend(
            assistant_message(tool_calls=[tool_call("call-1", "read_file", '{"path":"notes.txt"}')]),
            assistant_message(tool_calls=[tool_call("call-2", "read_file", '{"path":"notes.txt"}')]),
        )
        with self.assertRaisesRegex(MaxStepsExceeded, "max_steps=2") as raised:
            Agent(backend, self.registry, max_steps=2).run("Keep reading")
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(raised.exception.partial_result.total_tool_calls, 2)


if __name__ == "__main__":
    unittest.main()
