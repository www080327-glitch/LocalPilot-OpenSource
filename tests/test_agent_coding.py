"""Real temporary-workspace operations; only the model backend is faked."""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from agent.__main__ import main
from agent.commands import execute
from agent.loop import Agent
from agent.patches import apply_patch
from agent.registry import create_default_registry as make_registry
from agent.safety import PermissionGateway, CapabilityPolicy
from agent.tool_budget import measure_tool_budget
from tests.test_agent_loop import FakeBackend, assistant_message, tool_call


def create_default_registry(*args, **kwargs):
    # These tests intentionally exercise trusted synthetic host programs.
    kwargs.setdefault("capabilities", CapabilityPolicy(execute=True))
    return make_registry(*args, **kwargs)


def call(call_id, name, arguments):
    return tool_call(call_id, name, json.dumps(arguments))


class CodingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.outside_directory = tempfile.TemporaryDirectory()
        self.outside = Path(self.outside_directory.name).resolve()
        (self.root / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.registry = create_default_registry(self.root, permission_mode="permissive")

    def tearDown(self):
        self.directory.cleanup()
        self.outside_directory.cleanup()

    def patch_value(self, registry=None, new="2"):
        return (registry or self.registry).call("apply_patch", {"changes": [
            {"path": "value.py", "operation": "update", "old_text": "VALUE = 1", "new_text": "VALUE = " + new}
        ]})

    def test_read_patch_execute_real_unittest_closed_loop_in_both_profiles(self):
        (self.root / "test_value.py").write_text(
            "import unittest\nfrom value import VALUE\nclass ValueTest(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(VALUE, 2)\n", encoding="utf-8")
        for profile in ("standard", "minimal"):
            with self.subTest(profile=profile):
                (self.root / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
                registry = create_default_registry(self.root, profile=profile, permission_mode="permissive")
                reading = call("read", "read_file", {"path": "value.py"}) if profile == "standard" else call("read", "execute", {"argv": ["cat", "value.py"]})
                backend = FakeBackend(
                    assistant_message(tool_calls=[reading]),
                    assistant_message(tool_calls=[call("patch", "apply_patch", {"changes": [
                        {"path": "value.py", "operation": "update", "old_text": "VALUE = 1", "new_text": "VALUE = 2"}]} )]),
                    assistant_message(tool_calls=[call("test", "execute", {"argv": [sys.executable, "-m", "unittest", "test_value", "-v"]})]),
                    assistant_message("Changed VALUE to 2 and the test passed."),
                )
                result = Agent(backend, registry).run("Fix VALUE and test")
                payloads = [json.loads(m["content"]) for m in result.messages if m["role"] == "tool"]
                self.assertTrue(all(p["ok"] for p in payloads), payloads)
                self.assertEqual(payloads[-1]["result"]["exit_code"], 0)
                self.assertIn("OK", payloads[-1]["result"]["stderr"])
                self.assertEqual((self.root / "value.py").read_text(), "VALUE = 2\n")
                self.assertEqual(result.total_steps, 4)
                self.assertEqual(result.usage_summary()["tool_budget"]["tool_count"], 6)

    def test_create_update_and_hash_diff_audit_receipts(self):
        created = self.registry.call("apply_patch", {"changes": [{"path": "new.txt", "operation": "create", "content": "one\n"}]})
        self.assertEqual(created["status"], "ok")
        updated = self.registry.call("apply_patch", {"changes": [{"path": "new.txt", "operation": "update", "old_text": "one", "new_text": "two", "expected_sha256": hashlib.sha256(b"one\n").hexdigest()}]})
        receipt = updated["changes"][0]
        self.assertIn("+two", receipt["diff"])
        self.assertEqual(receipt["after_sha256"], hashlib.sha256(b"two\n").hexdigest())
        self.assertEqual((self.root / "new.txt").read_text(), "two\n")
        self.assertNotIn("+two", json.dumps(self.registry.gateway.audit))

    def test_preflight_rejects_entire_batch_without_partial_edits(self):
        with self.assertRaises(ValueError):
            self.registry.call("apply_patch", {"changes": [
                {"path": "new.txt", "operation": "create", "content": "valid"},
                {"path": "value.py", "operation": "update", "old_text": "absent", "new_text": "bad"},
            ]})
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual((self.root / "value.py").read_text(), "VALUE = 1\n")

    def test_existing_create_duplicate_paths_and_ambiguous_updates_are_rejected(self):
        for changes in (
            [{"path": "value.py", "operation": "create", "content": "overwrite"}],
            [{"path": "new.txt", "operation": "create", "content": "a"}] * 2,
            [{"path": "value.py", "operation": "update", "old_text": "", "new_text": "a"}],
        ):
            with self.subTest(changes=changes), self.assertRaises((ValueError, FileExistsError)):
                self.registry.call("apply_patch", {"changes": changes})
        (self.root / "repeated.txt").write_text("a a")
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.registry.call("apply_patch", {"changes": [{"path": "repeated.txt", "operation": "update", "old_text": "a", "new_text": "b"}]})

    def test_hash_conflict_and_unknown_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.registry.call("apply_patch", {"changes": [{"path": "value.py", "operation": "update", "old_text": "1", "new_text": "2", "expected_sha256": "wrong"}]})
        with self.assertRaisesRegex(ValueError, "fields"):
            self.registry.call("apply_patch", {"changes": [{"path": "new", "operation": "create", "content": "a", "approved": True}]})

    def test_delete_needs_hash_and_approval_except_explicit_full(self):
        delete = {"path": "value.py", "operation": "delete"}
        with self.assertRaisesRegex(ValueError, "expected_sha256"):
            self.registry.call("apply_patch", {"changes": [delete]})
        delete["expected_sha256"] = hashlib.sha256(b"VALUE = 1\n").hexdigest()
        result = self.registry.call("apply_patch", {"changes": [delete]})
        self.assertEqual(result["status"], "approval_required")
        self.assertTrue((self.root / "value.py").exists())
        full = create_default_registry(self.root, permission_mode="full")
        self.assertEqual(full.call("apply_patch", {"changes": [delete]})["status"], "ok")
        self.assertFalse((self.root / "value.py").exists())

    def test_four_permission_modes_share_hard_rules(self):
        expectations = {"all_confirm": ("approval_required", "approval_required"),
                        "cautious": ("ok", "approval_required"),
                        "permissive": ("ok", "ok"), "full": ("ok", "ok")}
        for mode, (read_status, patch_status) in expectations.items():
            with self.subTest(mode=mode):
                registry = create_default_registry(self.root, permission_mode=mode)
                self.assertEqual(registry.call("execute", {"argv": ["echo", "safe"]})["status"], read_status)
                (self.root / "value.py").write_text("VALUE = 1\n")
                self.assertEqual(self.patch_value(registry)["status"], patch_status)
                denied = registry.call("execute", {"argv": ["sudo", "echo", "unsafe"]})
                self.assertEqual(denied["status"], "denied")
                self.assertEqual(denied["risk_summary"]["level"], "high")

    def test_cautious_approval_contains_preview_but_does_not_write(self):
        registry = create_default_registry(self.root)
        result = self.patch_value(registry)
        self.assertEqual(result["status"], "approval_required")
        self.assertIn("+VALUE = 2", result["changes"][0]["diff"])
        self.assertEqual((self.root / "value.py").read_text(), "VALUE = 1\n")
        with patch("agent.commands.subprocess.Popen") as spawn:
            request = registry.call("execute", {"argv": [sys.executable, "-m", "unittest"]})
            self.assertEqual(request["status"], "approval_required")
            spawn.assert_not_called()

    def test_all_confirm_read_returns_approval_instead_of_contents(self):
        registry = create_default_registry(self.root, permission_mode="all_confirm")
        self.assertEqual(registry.call("read_file", {"path": "value.py"})["status"], "approval_required")

    def test_path_escape_for_read_patch_and_command(self):
        for escaped in ("../missing.txt", str(self.outside / "new.txt"), "folder/../../x"):
            with self.subTest(path=escaped):
                with self.assertRaises(ValueError):
                    self.registry.call("read_file", {"path": escaped})
                with self.assertRaises(ValueError):
                    self.registry.call("apply_patch", {"changes": [{"path": escaped, "operation": "create", "content": "bad"}]})
                self.assertEqual(self.registry.call("execute", {"argv": ["cat", escaped]})["status"], "denied")
        result = self.registry.call("execute", {"argv": ["tee", "--output=/etc/profile"]})
        self.assertEqual(result["status"], "denied")

    def test_symlink_file_directory_and_dangling_escape(self):
        (self.outside / "secret.txt").write_text("outside")
        try:
            (self.root / "link").symlink_to(self.outside, target_is_directory=True)
            (self.root / "dangling").symlink_to(self.outside / "not-yet-created")
        except (OSError, NotImplementedError) as error:
            self.skipTest(str(error))
        for path in ("link/secret.txt", "link/new.txt", "dangling"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.registry.call("read_file", {"path": path})
                with self.assertRaises(ValueError):
                    self.registry.call("apply_patch", {"changes": [{"path": path, "operation": "create", "content": "bad"}]})
                self.assertEqual(self.registry.call("execute", {"argv": ["cat", path]})["status"], "denied")
        self.assertEqual((self.outside / "secret.txt").read_text(), "outside")
        self.assertFalse((self.outside / "new.txt").exists())

    def test_internal_symlink_is_readable_but_not_writable(self):
        (self.root / "internal").symlink_to(self.root / "value.py")
        self.assertEqual(self.registry.call("read_file", {"path": "internal"}), "VALUE = 1\n")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.registry.call("apply_patch", {"changes": [{"path": "internal", "operation": "update", "old_text": "1", "new_text": "2"}]})

    def test_hardlink_patch_and_protected_metadata_writes_are_rejected(self):
        os.link(self.root / "value.py", self.outside / "hardlink.py")
        with self.assertRaisesRegex(ValueError, "hard links"):
            self.patch_value()
        for path in (".git/config", ".env"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.registry.call("apply_patch", {"changes": [{"path": path, "operation": "create", "content": "bad"}]})

    def test_dangerous_commands_never_spawn_even_with_full_permissions(self):
        registry = create_default_registry(self.root, permission_mode="full")
        commands = [
            ["sudo", "true"], ["rm", "-rf", "."], ["dd", "if=value.py", "of=/dev/disk0"],
            ["chmod", "777", "value.py"], ["sh", "-c", "echo bad"], ["env", "sh"],
            [sys.executable, "-c", "print(1)"], [sys.executable, "-Ic", "print(1)"],
            [sys.executable, "-mpip", "install", "bad"], [sys.executable, "-m", "http.server"],
            ["git", "reset", "--hard"], ["git", "clean", "-fd"], ["git", "push"],
            ["git", "diff", "--output=escaped.txt"], ["echo", "safe; rm"], ["curl", "example.com"],
        ]
        with patch("agent.commands.subprocess.Popen") as spawn:
            for argv in commands:
                with self.subTest(argv=argv):
                    self.assertEqual(registry.call("execute", {"argv": argv})["status"], "denied")
            spawn.assert_not_called()

    def test_fixed_cwd_and_no_environment_secret_inheritance(self):
        (self.root / "envcheck.py").write_text(
            "import os\nprint(os.getcwd())\nprint(os.getenv('LOCALPILOT_TEST_SECRET', 'absent'))\nprint(os.getenv('DEEPSEEK_API_KEY', 'absent'))\n")
        with patch.dict(os.environ, {"LOCALPILOT_TEST_SECRET": "secret", "DEEPSEEK_API_KEY": "secret"}):
            result = self.registry.call("execute", {"argv": [sys.executable, "envcheck.py"]})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["stdout"].splitlines(), [str(self.root), "absent", "absent"])
        self.assertEqual(self.registry.call("execute", {"argv": ["pwd"]})["stdout"].strip(), str(self.root))

    def test_nonzero_exit_and_bounded_stdout_stderr(self):
        (self.root / "output.py").write_text("import sys\nprint('a' * 50000)\nprint('b' * 50000, file=sys.stderr)\nraise SystemExit(7)\n")
        result = self.registry.call("execute", {"argv": [sys.executable, "output.py"], "output_limit": 321})
        self.assertEqual(result["status"], "nonzero_exit")
        self.assertEqual(result["exit_code"], 7)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len((result["stdout"] + result["stderr"]).encode()), 321)
        self.assertGreater(result["output_bytes_seen"], 90000)

    def test_timeout_kills_workspace_script(self):
        (self.root / "wait.py").write_text("import time\ntime.sleep(2)\nopen('too-late.txt', 'w').write('bad')\n")
        result = self.registry.call("execute", {"argv": [sys.executable, "wait.py"], "timeout": 0.1})
        self.assertEqual(result["status"], "timeout")
        self.assertNotEqual(result["exit_code"], 0)
        self.assertFalse((self.root / "too-late.txt").exists())

    def test_timeout_even_when_script_closes_both_output_pipes(self):
        (self.root / "closed.py").write_text("import os,time\nos.close(1)\nos.close(2)\ntime.sleep(2)\n")
        result = self.registry.call("execute", {"argv": [sys.executable, "closed.py"], "timeout": 0.1})
        self.assertEqual(result["status"], "timeout")

    def test_normal_child_process_groups_are_cleaned_up(self):
        (self.root / "child.py").write_text("import time\ntime.sleep(0.4)\nopen('child-done.txt', 'w').write('bad')\n")
        (self.root / "parent.py").write_text("import subprocess,sys\nsubprocess.Popen([sys.executable, 'child.py'])\n")
        result = self.registry.call("execute", {"argv": [sys.executable, "parent.py"], "timeout": 0.1})
        self.assertEqual(result["status"], "timeout")
        time.sleep(0.5)
        self.assertFalse((self.root / "child-done.txt").exists())

    def test_invalid_argv_bounds_and_policy_override_rejected(self):
        for args in ({"argv": "echo safe"}, {"argv": []}, {"argv": ["echo", "\0"]},
                     {"argv": ["echo"], "timeout": float("nan")}, {"argv": ["echo"], "timeout": 31},
                     {"argv": ["echo"], "output_limit": 16001}, {"argv": ["echo"], "timeout": True},
                     {"argv": ["echo"], "cwd": "/"}, {"argv": ["echo"], "approved": True},
                     {"argv": ["echo"], "gateway": None}, {"argv": ["echo"], "workspace_root": "/"}):
            with self.subTest(args=args), self.assertRaises((ValueError, TypeError)):
                self.registry.call("execute", args)

    def test_executable_cannot_be_shadowed_by_workspace_or_environment_path(self):
        fake = self.root / "echo"
        fake.write_text("not a real executable")
        fake.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(self.root)}):
            self.assertEqual(self.registry.call("execute", {"argv": ["echo", "safe"]})["stdout"].strip(), "safe")
        with self.assertRaises(ValueError):
            self.registry.call("execute", {"argv": ["./echo", "safe"]})

    def test_gateway_workspace_mismatch_rejected_for_direct_tools(self):
        with self.assertRaises(ValueError):
            execute(self.root, ["echo"], gateway=PermissionGateway(self.outside))
        with self.assertRaises(ValueError):
            apply_patch(self.root, [{"path": "new", "operation": "create", "content": "a"}], gateway=PermissionGateway(self.outside))

    def test_profile_schemas_and_run_command_compatibility(self):
        minimal = create_default_registry(self.root, profile="minimal")
        self.assertEqual(len(minimal.schemas()), 6)
        self.assertEqual(minimal.call("read_file", {"path": "value.py"}), "VALUE = 1\n")
        self.assertEqual(minimal.call("run_command", {"argv": ["cat", "value.py"]})["status"], "ok")
        schema = minimal.schemas()
        schema[0]["function"]["name"] = "mutated"
        self.assertEqual(minimal.schemas()[0]["function"]["name"], "read_file")

    def test_read_output_and_large_file_limits(self):
        (self.root / "medium.txt").write_text("x" * 30000)
        result = self.registry.call("read_file", {"path": "medium.txt"})
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(json.dumps(result).encode()), 16000)
        (self.root / "large.txt").write_bytes(b"x" * 1000001)
        with self.assertRaises(ValueError):
            self.registry.call("read_file", {"path": "large.txt"})

    def test_agent_recovers_from_bad_patch_and_nonzero_command(self):
        backend = FakeBackend(
            assistant_message(tool_calls=[call("bad", "apply_patch", {"changes": [{"path": "value.py", "operation": "update", "old_text": "missing", "new_text": "2"}]})]),
            assistant_message(tool_calls=[call("fail", "execute", {"argv": ["false"]})]),
            assistant_message(tool_calls=[call("read", "read_file", {"path": "value.py"})]),
            assistant_message("The patch and command failed; original file remains."),
        )
        result = Agent(backend, self.registry).run("Try and recover")
        payloads = [json.loads(m["content"]) for m in result.messages if m["role"] == "tool"]
        self.assertFalse(payloads[0]["ok"])
        self.assertEqual(payloads[1]["error"]["type"], "nonzero_exit")
        self.assertTrue(payloads[2]["ok"])
        self.assertEqual((self.root / "value.py").read_text(), "VALUE = 1\n")

    def test_agent_stops_for_approval_and_skips_remaining_batch(self):
        backend = FakeBackend(assistant_message(tool_calls=[
            call("approval", "apply_patch", {"changes": [{"path": "new", "operation": "create", "content": "bad"}]}),
            call("later", "execute", {"argv": ["echo", "should-not-run"]}),
        ]))
        registry = create_default_registry(self.root)
        with patch("agent.commands.subprocess.Popen") as spawn:
            result = Agent(backend, registry).run("Need approval")
            spawn.assert_not_called()
        self.assertEqual(result.status, "approval_required")
        self.assertEqual(len(backend.calls), 1)
        self.assertFalse((self.root / "new").exists())
        self.assertEqual(json.loads(result.messages[-1]["content"])["error"]["type"], "skipped_pending_approval")
        self.assertEqual(result.approvals[0]["status"], "approval_required")

    def test_trace_and_audit_omit_patch_and_command_content(self):
        secret = "not-for-logs"
        backend = FakeBackend(
            assistant_message(tool_calls=[call("patch", "apply_patch", {"changes": [{"path": "new", "operation": "create", "content": secret}]}), call("echo", "execute", {"argv": ["echo", secret]})]),
            assistant_message("Done"),
        )
        trace = []
        Agent(backend, self.registry, trace=trace.append).run("Create")
        self.assertNotIn(secret, json.dumps(trace))
        self.assertNotIn(secret, json.dumps(self.registry.gateway.audit))

    def test_cli_returns_approval_exit_code_and_writes_metadata(self):
        backend = FakeBackend(assistant_message(tool_calls=[call("patch", "apply_patch", {"changes": [{"path": "new", "operation": "create", "content": "secret-code"}]})]))
        audit_path, usage_path = self.root / "audit.jsonl", self.root / "usage.jsonl"
        with patch("agent.__main__.DeepSeekBackend", return_value=backend), patch("sys.stdout", new_callable=io.StringIO) as out:
            status = main(["--workspace", str(self.root), "--minimal-mode", "--audit-log", str(audit_path), "--usage-log", str(usage_path), "create file"])
        self.assertEqual(status, 3)
        self.assertIn("approval_required", out.getvalue())
        self.assertNotIn("secret-code", audit_path.read_text())
        usage = json.loads(usage_path.read_text())
        self.assertEqual(usage["status"], "approval_required")
        self.assertEqual(usage["tool_budget"]["tool_count"], 6)
        self.assertFalse((self.root / "new").exists())

    def test_io_failure_reports_partial_batch_and_cleans_temporary_file(self):
        with patch("agent.patches.os.replace", side_effect=OSError("simulated disk failure")):
            result = self.registry.call("apply_patch", {"changes": [
                {"path": "new", "operation": "create", "content": "already-created"},
                {"path": "value.py", "operation": "update", "old_text": "1", "new_text": "2"},
            ]})
        self.assertEqual(result["status"], "error")
        self.assertEqual([item["path"] for item in result["applied"]], ["new"])
        self.assertEqual((self.root / "value.py").read_text(), "VALUE = 1\n")
        self.assertEqual(list(self.root.glob(".localpilot-*")), [])

    def test_large_structured_outputs_keep_failure_status_and_are_bounded(self):
        (self.root / "control.py").write_text("import os\nos.write(1, bytes([1]) * 30000)\nraise SystemExit(4)\n")
        result = self.registry.call("execute", {"argv": [sys.executable, "control.py"]})
        self.assertEqual(result["status"], "nonzero_exit")
        self.assertEqual(result["exit_code"], 4)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 16000)

    def test_attached_absolute_path_options_are_rejected(self):
        for argv in (["cp", "-t/etc", "value.py"], ["cat", "--file=/etc/passwd"]):
            self.assertEqual(self.registry.call("execute", {"argv": argv})["status"], "denied")

    def test_approval_exposes_exact_command_without_putting_arguments_in_audit(self):
        registry = create_default_registry(self.root)
        argv = [sys.executable, "value.py", "review-this-argument"]
        result = registry.call("execute", {"argv": argv})
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(result["request"]["argv"], argv)
        self.assertNotIn("review-this-argument", json.dumps(registry.gateway.audit))

    def test_git_path_separator_cannot_hide_helper_disabling_flags(self):
        for args in (["init", "-q"], ["config", "diff.probe.textconv", sys.executable + " helper.py"]):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)
        (self.root / "helper.py").write_text("open('helper-ran', 'w').write('bad')\nprint('converted')\n")
        (self.root / ".gitattributes").write_text("*.txt diff=probe\n")
        (self.root / "file.txt").write_text("before\n")
        subprocess.run(["git", "add", "file.txt", ".gitattributes"], cwd=self.root, check=True, capture_output=True)
        (self.root / "file.txt").write_text("after\n")
        result = self.registry.call("execute", {"argv": ["git", "diff", "--", "file.txt"]})
        self.assertEqual(result["status"], "ok", result)
        self.assertIn("+after", result["stdout"])
        self.assertFalse((self.root / "helper-ran").exists())

    def test_tool_budget_distinguishes_estimates_from_exact_tokens(self):
        report = measure_tool_budget(self.registry.schemas(), "prompt")
        self.assertEqual(report["tool_count"], 6)
        self.assertIsNone(report["schema_tokens"])
        self.assertIn("estimate_only", report["token_count_status"])


if __name__ == "__main__":
    unittest.main()
