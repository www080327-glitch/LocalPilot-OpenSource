"""Control parsing must fail before runtime dispatch on malformed input."""
import unittest
from unittest.mock import Mock

from computer.cli import control, normalize_input, render_result


class CLIInputTests(unittest.TestCase):
    def test_takeover_is_host_action_and_never_parses_tool_parameters(self):
        runtime = Mock()
        runtime.take_over.return_value = {"status": "ok", "state": "human_controlling", "quiescent": True}
        registry = Mock()
        result = control(runtime, registry, "/takeover", {"call": ("old", {})})
        self.assertTrue(result["quiescent"])
        registry.metadata.assert_not_called()
        registry.call.assert_not_called()
        runtime.take_over.assert_called_once()

    def test_duplicate_or_extra_control_input_fails_before_dispatch(self):
        for line in ["/takeover/takeover", "/takeover /takeover", "/takeover junk", "/takeover\n/done"]:
            runtime, registry = Mock(), Mock()
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "控制命令必须单独"):
                control(runtime, registry, line, {})
            runtime.take_over.assert_not_called()
            runtime.resume.assert_not_called()
            registry.call.assert_not_called()

    def test_terminal_outer_paste_markers_and_whitespace(self):
        runtime = Mock()
        control(runtime, Mock(), " \x1b[200~/takeover\x1b[201~\n", {})
        runtime.take_over.assert_called_once()
        self.assertIn('"value":"\\u001b[200~"', normalize_input(' set_value {"value":"\\u001b[200~"} '))

    def test_malformed_tool_json_has_actionable_message(self):
        registry = Mock()
        with self.assertRaisesRegex(ValueError, "参数需要完整 JSON"):
            control(Mock(), registry, "inspect_tree not-json", {})
        registry.call.assert_not_called()

    def test_human_takeover_and_tree_output_are_concise(self):
        self.assertIn("电脑操作已暂停", render_result({"status": "ok", "state": "human_controlling", "quiescent": True}))
        tree = {"status": "ok", "window_title": "test", "nodes": [{"role": "AXWindow"}], "native_node_count": 12}
        output = render_result(tree)
        self.assertIn("12 项控件", output)
        self.assertNotIn('"nodes"', output)
        self.assertIn('"nodes"', render_result(tree, raw_json=True))

    def test_unknown_resume_baseline_does_not_claim_change(self):
        result = {"status": "ok", "state": "agent_controlling", "changes": [{"changed": None}]}
        self.assertIn("尚不能确认", render_result(result))
