"""Portable inference transport and host gates; HTTP replies are protocol fixtures."""
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from companion import cli
from companion.config import Config, PrivateData
from companion.model.backend import ModelManager
from companion.runtime.power import LowPowerPolicy, external_power, local_model_block_reason
from companion.runtime.system_resources import snapshot


class IntelModelGateTests(unittest.TestCase):
    def test_linux_launchd_operations_are_unavailable_without_writing_a_startup_item(self):
        from companion.runtime.launchd import manage
        with tempfile.TemporaryDirectory() as directory, patch("companion.runtime.launchd.sys.platform", "linux"):
            private = PrivateData(Path(directory) / "state")
            contents = sorted(private.root.iterdir())
            for action in ("install", "uninstall", "status"):
                with self.subTest(action=action):
                    self.assertEqual(manage(action, "unused.json", private, confirmed=True),
                        {"status":"unavailable", "reason":"macos_required", "installed":False})
                    self.assertEqual(sorted(private.root.iterdir()), contents)
            preview = manage("render", "unused.json", private)
            self.assertEqual(preview["status"], "preview")
            self.assertFalse(preview["installed"])
            self.assertTrue(Path(preview["path"]).is_file())

    def test_unsupported_mlx_hosts_do_not_start_worker_or_claim_availability(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Config(model_path=directory, low_power_policy="off", allow_local_on_battery=True)
            for host, machine in (("darwin", "x86_64"), ("linux", "x86_64"), ("linux", "aarch64")):
                with self.subTest(host=host, machine=machine), patch("companion.model.backend.sys.platform", host), patch(
                        "companion.model.backend.platform.machine", return_value=machine):
                    manager = ModelManager(config)
                    self.assertFalse(manager.available())
                    result = manager.complete([{"role":"user", "content":"synthetic protocol request"}])
                    self.assertEqual(result["error_stage"], "backend_platform")
                    self.assertFalse(result["model_called"])
                    self.assertIsNone(manager.child)
                    self.assertEqual(manager.inferences, 0)
                    self.assertEqual(manager.total_loads, 0)
                    self.assertFalse(manager.stats()["backend_platform_supported"])

    def test_apple_silicon_keeps_existing_mlx_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch("companion.model.backend.sys.platform", "darwin"), patch(
                "companion.model.backend.platform.machine", return_value="arm64"):
            manager = ModelManager(Config(model_path=directory))
            self.assertTrue(manager.available())
            self.assertTrue(manager.stats()["backend_platform_supported"])
            self.assertTrue(manager.stats()["owns_model_process"])
            self.assertIsNone(manager.child)

    def test_disable_thinking_is_explicit_and_boolean(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{}")
            self.assertFalse(Config.load(path).http_model_disable_thinking)
            for value in (True, False):
                path.write_text(json.dumps({"http_model_disable_thinking":value}))
                self.assertIs(Config.load(path).http_model_disable_thinking, value)
            for value in ("false", 0, 1, None):
                path.write_text(json.dumps({"http_model_disable_thinking":value}))
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "must be boolean"):
                    Config.load(path)


class PortableHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.requests = []
        self.response = {"model":"synthetic-cpu-fixture", "choices":[{
            "finish_reason":"stop", "message":{"role":"assistant", "content":"56"}}]}
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                test.requests.append({"path":self.path, "body":json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
                raw = json.dumps(test.response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.config = Config(data_dir=str(self.root / "state"), backend="local-http",
            low_power_policy="off", allow_local_on_battery=True,
            http_model_endpoint=f"http://127.0.0.1:{self.server.server_port}/v1",
            http_model_name="synthetic-cpu-fixture", http_model_host_local_only=True,
            localpilot_endpoint="", localpilot_auto_local=False,
            quiet_start_hour=0, quiet_end_hour=0, dnd=True)
        self.manager = ModelManager(self.config)

    def tearDown(self):
        self.manager.unload()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_local_http_without_mlx_preserves_unmanaged_server_across_unload(self):
        for _ in range(2):
            result = self.manager.complete([{"role":"user", "content":"7 * 8"}], max_tokens=32)
            self.assertEqual((result["status"], result["text"]), ("ok", "56"))
            self.assertEqual(result["reported_model"], "synthetic-cpu-fixture")
            self.assertIsNone(result["usage"])
            self.assertIsNone(self.manager.child)
            self.manager.unload()
        self.assertTrue(self.thread.is_alive())
        self.assertEqual(self.manager.total_loads, 0)
        self.assertEqual(self.manager.total_unloads, 0)
        self.assertFalse(self.manager.stats()["owns_model_process"])
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(row["path"] == "/v1/chat/completions" for row in self.requests))
        self.assertNotIn("chat_template_kwargs", self.requests[0]["body"])

    def test_non_thinking_request_is_sent_only_after_explicit_configuration(self):
        self.config.http_model_disable_thinking = True
        self.assertEqual(self.manager.complete([{"role":"user", "content":"7 * 8"}])["status"], "ok")
        self.assertEqual(self.requests[0]["body"]["chat_template_kwargs"], {"enable_thinking":False})
        self.assertEqual(len(self.requests), 1)

    def test_request_flag_does_not_strip_or_rewrite_visible_thinking(self):
        self.config.http_model_disable_thinking = True
        text = "<think>synthetic server did not honor template</think>56"
        self.response["choices"][0]["message"]["content"] = text
        result = self.manager.complete([{"role":"user", "content":"7 * 8"}])
        self.assertEqual(result["text"], text)
        self.assertEqual(len(self.requests), 1)

    def test_truncated_and_tool_bearing_replies_stay_failed_without_retry(self):
        for finish, calls in (("length", None), ("stop", [{"id":"synthetic-tool"}]), ("tool_calls", [])):
            self.response["choices"][0] = {"finish_reason":finish,
                "message":{"role":"assistant", "content":"UNACCEPTED_PARTIAL", "tool_calls":calls}}
            with self.subTest(finish=finish, calls=calls):
                before = len(self.requests)
                result = self.manager.complete([{"role":"user", "content":"synthetic request"}])
                self.assertEqual(result["status"], "unavailable")
                self.assertIn("Incomplete or tool-bearing", result["error"])
                self.assertNotIn("text", result)
                self.assertEqual(len(self.requests), before + 1)

    def test_low_power_block_is_explicit_and_does_not_send_http(self):
        self.config.low_power_policy = "always"
        result = self.manager.complete([{"role":"user", "content":"synthetic request"}])
        self.assertEqual(result["error_stage"], "power_policy")
        self.assertEqual(self.requests, [])
        self.assertEqual(self.manager.inferences, 0)

    def test_real_cli_uses_local_http_and_reports_unknown_usage(self):
        path = self.root / "config.json"
        path.write_text(json.dumps(asdict(self.config)))
        result = subprocess.run([sys.executable, "-m", "companion", "--config", str(path),
            "--json", "model-smoke", "--prompt", "7 * 8"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual((body["status"], body["backend"], body["text"]), ("ok", "local-http", "56"))
        self.assertIsNone(body["usage"])
        self.assertEqual(len(self.requests), 1)

    def test_real_service_keeps_source_memory_across_restart_without_native_mac_features(self):
        path = self.root / "config.json"
        path.write_text(json.dumps(asdict(self.config)))
        source = self.root / "rollout.jsonl"
        source.write_text(json.dumps({"timestamp":datetime.now().astimezone().isoformat(),
            "type":"event_msg", "payload":{"type":"user_message", "message":"检查 CPU 路由，尚未完成验证。"}}, ensure_ascii=False) + "\n")
        original = source.read_bytes()
        source_id = None
        for restart in (False, True):
            with (self.root / "service.log").open("a") as log:
                process = subprocess.Popen([sys.executable, "-m", "companion", "--config", str(path), "run"],
                    stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while True:
                    self.assertIsNone(process.poll(), (self.root / "service.log").read_text())
                    try:
                        status = cli.client(self.config, {"command":"status"}, timeout=1)
                        break
                    except (OSError, ValueError):
                        if time.monotonic() >= deadline:
                            self.fail((self.root / "service.log").read_text())
                        time.sleep(.05)
                self.assertEqual(status["status"], "running")
                self.assertEqual(status["model"]["backend"], "local-http")
                self.assertIsNone(status["model"]["worker_pid"])
                if not restart:
                    imported = cli.client(self.config, {"command":"source_connect", "kind":"codex", "path":str(source), "follow":False})
                    self.assertEqual(imported["sync"]["records"], 1)
                    source_id = imported["source"]["id"]
                else:
                    listed = cli.client(self.config, {"command":"source_list"})
                    self.assertIn(source_id, [row["id"] for row in listed["sources"]])
                answer = cli.client(self.config, {"command":"ask", "text":"我今天在 Codex 做了什么？"})
                self.assertIn("CPU 路由", answer["text"])
                self.assertIn("尚未完成验证", answer["text"])
                self.assertEqual(answer["items"][0]["source_path"], str(source))
                self.assertEqual(answer["model"]["status"], "not_called")
                if sys.platform != "darwin":
                    meeting = cli.client(self.config, {"command":"meeting_status"})
                    self.assertEqual(meeting['supported_host'], sys.platform.startswith('linux'))
                    if sys.platform.startswith('linux'):
                        self.assertFalse(meeting['capabilities']['model_available'])
                        self.assertEqual(meeting['meeting']['state'], 'idle')
                    self.assertNotEqual(status["native_observer"]["state"], "running")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self.assertEqual(process.returncode, 0, (self.root / "service.log").read_text())
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue((self.root / "state" / "memory.sqlite3").is_file())
        self.assertEqual(self.requests, [])


class IntelPowerTests(unittest.TestCase):
    # pmset syntax is from Apple's pinned source, documented in the companion Intel report.
    CAP = "Capabilities for AC Power:\n displaysleep\n disksleep\n sleep\n womp\n"
    CUSTOM = "AC Power:\n displaysleep 10\n disksleep 10\n sleep 1\n"

    def system_active(self, custom, cap=None, after="AC Power"):
        sequence = ["Now drawing from 'AC Power'\n", custom]
        if cap is not None:
            sequence.append(cap)
        sequence.append(f"Now drawing from '{after}'\n")
        with patch("companion.runtime.power.sys.platform", "darwin"), patch(
                "companion.runtime.power.subprocess.check_output", side_effect=sequence):
            return LowPowerPolicy(Config(low_power_policy="system")).active()

    def test_tristate_current_power_mode(self):
        for mode, expected in ((0, False), (1, True), (2, False)):
            with self.subTest(mode=mode):
                self.assertIs(self.system_active(self.CUSTOM + f" powermode {mode}\n"), expected)

    def test_unsupported_low_power_mode_is_proven_by_current_source_capabilities(self):
        self.assertFalse(self.system_active(self.CUSTOM, self.CAP))

    def test_missing_setting_does_not_imply_disabled_when_mode_is_supported(self):
        for feature in ("lowpowermode", "highpowermode", "powermode"):
            with self.subTest(feature=feature):
                self.assertTrue(self.system_active(self.CUSTOM, self.CAP + feature + "\n"))

    def test_unknown_mismatched_or_invalid_capabilities_remain_conservative(self):
        for cap in ("", "Capabilities for AC Power:\n", "unexpected output",
                    self.CAP.replace("AC Power", "Battery Power"), self.CAP + "invalid feature\n"):
            with self.subTest(cap=cap):
                self.assertTrue(self.system_active(self.CUSTOM, cap))

    def test_unsupported_mode_read_still_detects_power_source_change(self):
        self.assertTrue(self.system_active(self.CUSTOM, self.CAP, after="Battery Power"))

    def test_conflicting_or_malformed_modes_do_not_fall_back_to_unsupported(self):
        for extra in (" powermode 0\n lowpowermode 1\n", " powermode 3\n", " lowpowermode 2\n", " powermode unknown\n"):
            with self.subTest(extra=extra):
                self.assertTrue(self.system_active(self.CUSTOM + extra))

    def test_desktop_mac_without_battery_uses_confirmed_ac_for_inference_and_resources(self):
        with patch("companion.runtime.power.sys.platform", "darwin"), patch("psutil.sensors_battery", return_value=None), patch(
                "companion.runtime.power.subprocess.check_output", return_value="Now drawing from 'AC Power'\n"):
            self.assertTrue(external_power(None))
            self.assertIsNone(local_model_block_reason(Config()))
            resources = snapshot()
            self.assertIs(resources["on_ac_power"], True)
            self.assertIsNone(resources["battery_percent"])
            self.assertIsNone(resources["battery_discharge_watts"])
            self.assertEqual(resources["energy_source"], "UNAVAILABLE")

    def test_reported_battery_use_wins_and_unknown_power_is_not_assumed_ac(self):
        self.assertFalse(external_power(SimpleNamespace(power_plugged=False)))
        with patch("companion.runtime.power.sys.platform", "darwin"), patch(
                "companion.runtime.power.subprocess.check_output", return_value="unrecognized source"):
            self.assertIsNone(external_power(None))
        with patch("companion.runtime.power.sys.platform", "linux"):
            self.assertIsNone(external_power(None))
            self.assertTrue(LowPowerPolicy(Config(low_power_policy="system")).active())

    def test_failed_power_query_does_not_enable_local_inference(self):
        with patch("companion.runtime.power.sys.platform", "darwin"), patch("psutil.sensors_battery", return_value=None), patch(
                "companion.runtime.power.subprocess.check_output", side_effect=subprocess.TimeoutExpired("pmset", 2)):
            self.assertIsNone(external_power(None))
            self.assertIsNotNone(local_model_block_reason(Config()))


if __name__ == "__main__":
    unittest.main()
