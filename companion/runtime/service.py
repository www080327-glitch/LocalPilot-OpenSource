"""Companion lifecycle and public facade over observation, dialogue and tasks."""
from collections import deque
from dataclasses import replace
from datetime import datetime
import fcntl
import json
import os
from queue import Empty, Full, Queue
import secrets
import signal
import time
import threading
from companion.config import PrivateData
from companion.memory import MemoryStore, LexicalRetriever, BM25Retriever
from companion.model import ModelManager
from companion.model.prompts import CHAT_SYSTEM
from companion.memory.verifier import SourceVerifier
from companion.observers import ReadScope, FileObserver
from companion.triggers import NoticePolicy
from companion.channels import LocalChannel
from companion.channels.notification import notify
from companion.escalation import OpenAICompatibleProvider
from companion.observers.events import ObservationPrivacy, redact_text
from companion.triggers.workflow import WorkflowSignals
from companion.runtime.observations import ObservationController
from companion.runtime.dialogue import DialogueController
from companion.runtime.tasks import TaskController
from companion.runtime.commands import CommandRouter

SYSTEM = CHAT_SYSTEM


class Companion:
    def __init__(self, config):
        self.config = config
        self.observations = ObservationController(self)
        self.dialogue = DialogueController(self)
        self.agent_tasks = TaskController(self)
        self.commands = CommandRouter(self)
        self.private = PrivateData(config.data_dir)
        self.lock = open(self.private.file("service.lock"), "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Companion already running for this data directory")
        try:
            self.initialize(config)
        except BaseException:
            if hasattr(self, "channel"):
                self.channel.stop()
            if hasattr(self, "store"):
                self.store.close()
            self.lock.close()
            raise

    def initialize(self, config):
        from companion.runtime.power import LowPowerPolicy
        self.power = LowPowerPolicy(config)
        self.store = MemoryStore(self.private.file("memory.sqlite3"))
        if self.private.file("observation-pause-intent.json").exists():
            self.store.set("observation_paused", True)
            self.private.file("observation-pause-intent.json").unlink()
        exclusions = self.store.get("ui_app_exclusions")
        if exclusions is not None:
            config.native_app_exclusions = tuple(exclusions)
        self.scope = ReadScope(config)
        from companion.memory.observations import ObservationMemory
        from companion.observers.native import native_observer
        self.observation_memory = ObservationMemory(self.store, aliases=config.project_aliases, source_allowed=self.observation_accessible)
        self.privacy = ObservationPrivacy(config, self.store, self.scope)
        self.workflow = WorkflowSignals(config.active_sustained_minutes)
        self.native = native_observer(config, self.enqueue_native)
        self.retriever = (BM25Retriever if config.retrieval_backend == "bm25" else LexicalRetriever)(self.store, source_allowed=self.legacy_memory_accessible, aliases=config.project_aliases)
        self.verifier = SourceVerifier(self.store, self.scope)
        self.model = ModelManager(config, self.store)
        self.secondary_model = None  # Strong reasoning belongs to the Agent Service.
        from companion.model.routing import TieredInference
        self.inference = TieredInference(self.model, self.secondary_model, config)
        self.policy = NoticePolicy(config, self.store)
        self.agent = OpenAICompatibleProvider(config)
        from companion.escalation.service_v491 import LocalPilotProvider
        self.localpilot = LocalPilotProvider(config)
        self.cloud_localpilot=LocalPilotProvider(replace(config,localpilot_host_local_only=False,localpilot_allow_cloud=True,localpilot_auto_local=False,localpilot_analysis_route=config.localpilot_cloud_analysis_route))
        self.task_monitors = {}
        self.monitor_stop = threading.Event()
        self.queue = Queue(maxsize=2048)
        # AX callbacks run on a reader thread. Keep their telemetry in memory;
        # the SQLite connection belongs exclusively to the service loop.
        self.native_metrics_lock = threading.Lock()
        self.native_metrics = {"enqueued": 0, "rejected": 0, "queue_full": 0,
                               "privacy_filtered": 0, "processed": 0,
                               "queue_high_water": 0, "processing_ms_total": 0.0,
                               "processing_ms_max": 0.0}
        self.pending = {}
        self.events = deque((r["metadata"] for r in reversed(self.store.records(200, ["computer_event"]))), maxlen=200)
        self.stopping = False
        self.observation_pause_requested = threading.Event()
        self.inference_cancel_requested = threading.Event()
        from companion.observers.sources import SourceRegistry
        self.sources = SourceRegistry(config, self.store, self.observation_memory,
            lambda: self.privacy.paused() or self.observation_pause_requested.is_set())
        from companion.memory.training import TrainingExamples
        self.training = TrainingExamples(self.store, self.observation_memory, self.private)
        from companion.observers.meeting import MeetingCapture
        self.meetings = MeetingCapture(self)
        self.started = time.time()
        self.loop_wakeups = 0
        self.observed_events = 0
        self.last_error = None
        self.rescan_required = False
        self.last_retention = time.monotonic()
        self.last_loop_wall = time.time()
        self.last_loop_mono = time.monotonic()
        self.last_candidate = self.store.get("candidate_times", {})
        self.native_restart_attempts = 0
        self.native_retry_at = None
        self.token = secrets.token_urlsafe(32)
        self.channel = LocalChannel(config.port, self.token, self.enqueue_command)
        self.observer = FileObserver(self.scope, self.enqueue_event)
        self.recover_submission_journal()
        from companion.runtime.system_resources import ResourceMonitor
        from companion.runtime.inference_controls import InferenceControls
        self.resources=ResourceMonitor(config)
        self.resource_alerts=[]
        self.controls=InferenceControls(self)
        from companion.runtime.model_collaboration import ModelCollaboration
        self.collaboration=ModelCollaboration(self)

    def recover_submission_journal(self):
        return self.agent_tasks.recover_submission_journal()

    def enqueue_command(self, command, future):
        if (command.get("command") == "meeting_stop"
                or (command.get("command") == "clear" and command.get("confirmation") == "DELETE_COMPANION_MEMORY")
                or (command.get("source_id") == self.meetings.state.get("source_id") and command.get("source_id")
                    and (command.get("command") == "source_revoke" or
                         (command.get("command") == "source_set_enabled" and command.get("enabled") is False)))):
            self.meetings.request_stop()
        if command.get("command")=="inference_stop":
            self.controls.stop_async(command.get("ticket_id"),future)
            return
        if self.stopping:
            future.set_result({"status":"stopping"})
            return
        if isinstance(command, dict) and command.get("command") == "pause_observation" and command.get("paused") is True:
            # Stop acquisition immediately even if a model occupies the service
            # loop. Persistent state is still written only on the owning thread.
            self.observation_pause_requested.set()
            self.inference_cancel_requested.set()
            self.meetings.request_stop()
            self.private.write("observation-pause-intent.json", '{"paused":true}')
            self.native.stop()
            for manager in (self.model, self.secondary_model):
                child = getattr(manager, "child", None)
                if child is not None and child.poll() is None:
                    child.terminate()
        try:
            self.queue.put_nowait(("command", command, future))
        except Full:
            future.set_result({"status":"busy"})

    def enqueue_event(self, filename, kind):
        if self.stopping:
            return
        try:
            self.queue.put_nowait(("event", filename, kind))
        except Full:
            self.rescan_required = True

    def enqueue_native(self, event):
        return self.observations.enqueue_native(event)

    def process_native(self, raw):
        return self.observations.process_native(raw)

    def _process_native(self, raw):
        return self.observations._process_native(raw)

    def stop_signal(self, *_):
        self.stopping = True
        self.meetings.request_stop()
        self.monitor_stop.set()
        self.model.request_stop()
        if self.secondary_model:
            self.secondary_model.request_stop()
        try:
            self.queue.put_nowait(("stop", None, None))
        except Full:
            pass

    def run(self):
        os.umask(0o077)
        signal.signal(signal.SIGTERM, self.stop_signal)
        signal.signal(signal.SIGINT, self.stop_signal)
        import psutil
        try:
            self.channel.start()
            self.private.write("runtime.json", json.dumps({"pid":os.getpid(), "created":psutil.Process().create_time(), "port":self.channel.port, "token":self.token}))
            self.observer.start()
            if self.privacy.native_allowed():
                self.native.start()
            # Restart never implies continuous work across the process boundary.
            self.events.clear()
            self.store.set("project_activity", {})
            self.retention()
            self.scan()
            self.sources.poll()
            for task_id, record in reversed(list(self.store.get("localpilot_tasks", {}).items())):
                last = record.get("last_status", {})
                if record.get("endpoint") == self.config.localpilot_endpoint and record.get("transport", {}).get("scope") == self.privacy.consent_id() and last.get("status") not in {"completed", "incomplete", "failed", "cancelled", "timed_out"}:
                    self.monitor_task(task_id, record.get("last_event_cursor", 0), record.get("cloud_approved") is True)
            if not self.stopping:
                hour = datetime.now().hour
                self.greet("morning" if 5 <= hour < 12 else "evening" if 18 <= hour < 24 else "startup")
            while not self.stopping:
                try:
                    item = self.queue.get(timeout=2 if self.pending else min(15, self.config.eco_unload_seconds) if self.power.active() and getattr(self.model, "child", None) else 30)
                    self.loop_wakeups += 1
                    if self.recover_gap():
                        self.rescan_required = False
                        self.scan()
                    if self.stopping:
                        if item[0] == "command" and not item[2].done():
                            item[2].set_result({"status":"stopping"})
                        break
                    if item[0] == "event":
                        if item[2] == "rescan":
                            self.rescan_required = True
                        else:
                            self.pending[item[1]] = (time.monotonic(), item[2])
                    elif item[0] == "native":
                        try:
                            self.process_native(item[1])
                        except Exception as exc:
                            self.record_error("native_observation", exc)
                    elif item[0] == "inference_control_stop":
                        self.controls.stopped(item[1],item[2])
                    elif item[0] == "meeting":
                        self.meetings.drain()
                    elif item[0] == "task_update":
                        self.receive_task_update(item[1], item[2])
                    elif item[0] == "command":
                        if not item[2].set_running_or_notify_cancel():
                            if item[1].get("command") == "meeting_stop" or (item[1].get("command") == "pause_observation" and item[1].get("paused") is True):
                                self.command(item[1])
                            continue
                        try:
                            item[2].set_result(self.command(item[1]))
                        except Exception as exc:
                            self.record_error("command", exc)
                            item[2].set_result({"status":"error", "error":str(exc)})
                except Empty:
                    self.loop_wakeups += 1
                    if self.recover_gap():
                        self.rescan_required = False
                        self.scan()
                if self.stopping:
                    break
                if len(self.pending) > 2048:
                    self.pending.clear()
                    self.rescan_required = True
                for filename, (at, kind) in list(self.pending.items()):
                    if time.monotonic() - at >= 1.5:
                        self.process_file(filename, kind)
                        del self.pending[filename]
                if self.rescan_required:
                    self.rescan_required = False
                    self.scan()
                self.model.tick()
                if self.secondary_model:
                    self.secondary_model.tick()
                self.resource_alerts=(self.resource_alerts+self.resources.poll())[-10:]
                if self.controls.current and self.controls.current.get("phase") in {"running","starting","cleanup_required"} and not self.controls.ui_live():
                    from concurrent.futures import Future
                    self.controls.stop_async(self.controls.current["id"],Future(),origin="owned_ui_lost:"+getattr(self.controls,"ui_identity_error","unknown"))
                self.due_reminders()
                self.maintain_native()
                self.meetings.drain()
                self.scheduled_greeting()
                self.sources.poll()
                if time.monotonic() - self.last_retention >= self.config.retention_interval_seconds:
                    self.retention()
        finally:
            self.stopping = True
            self.monitor_stop.set()
            while True:
                try:
                    queued = self.queue.get_nowait()
                    if queued[0] == "command" and not queued[2].done():
                        queued[2].set_result({"status":"stopping"})
                except Empty:
                    break
            # A failed cleanup step must not skip releasing the remaining resources.
            try:
                cleanups = [self.meetings.stop, self.stop_inference_on_exit, self.native.stop, self.observer.stop, self.model.unload, self.stop_popup, self.stop_ui, self.channel.stop]
                if self.secondary_model:
                    cleanups.insert(3, self.secondary_model.unload)
                for cleanup in cleanups:
                    try:
                        cleanup()
                    except Exception as exc:
                        try:
                            self.record_error("cleanup", exc)
                        except Exception:
                            pass  # Still attempt every remaining resource cleanup.
            finally:
                try:
                    self.store.close()
                finally:
                    self.private.file("runtime.json").unlink(missing_ok=True)
                    self.lock.close()

    def recover_gap(self, wall=None, monotonic=None):
        wall = time.time() if wall is None else wall
        monotonic = time.monotonic() if monotonic is None else monotonic
        dw, dm = wall-self.last_loop_wall, monotonic-self.last_loop_mono
        self.last_loop_wall, self.last_loop_mono = wall, monotonic
        if max(dw, dm) < 120 and abs(dw-dm) < 5:
            return False
        # This detects scheduling/clock gaps, not the physical cause of a sleep.
        self.pending.clear()
        self.events.clear()
        self.workflow.reset()
        self.store.set("project_activity", {})
        self.model.tick()
        self.rescan_required = True
        self.count("recovery_gaps")
        self.store.set("last_recovery", {"timestamp":wall, "wall_gap_seconds":dw, "monotonic_gap_seconds":dm, "cause":"scheduling_or_clock_gap"})
        return True

    def record_error(self, stage, error):
        self.last_error = redact_text(str(error))[:800]
        self.count("errors")
        errors = self.store.get("recent_errors", [])
        errors.append({"timestamp":time.time(), "stage":stage, "error":self.last_error})
        self.store.set("recent_errors", errors[-20:])

    def stop_inference_on_exit(self):
        current=self.controls.current
        if current and current.get("phase") in {"starting","running","stopping","draining","recovery_required","stop_unconfirmed","cleanup_required"}:
            self.controls.stop_event.set()
            result=self.controls.provider().emergency_stop(current.get("task_id"),drain=current["kind"]=="cloud",submission_id=current.get("submission_id"))
            self.controls.stopped(current["id"],result)

    def stop_popup(self):
        try:
            import psutil
            record = json.loads(self.private.file("popup.json").read_text())
            proc = psutil.Process(record["pid"])
            executable = str(self.private.root/"CompanionPopup.app/Contents/MacOS/CompanionPopup")
            if record.get("token") == self.token and proc.exe() == executable and str(self.private.file("runtime.json")) in proc.cmdline():
                proc.terminate()
                proc.wait(timeout=3)
            self.private.file("popup.json").unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, psutil.Error):
            pass

    def scan(self):
        return self.observations.scan()

    def process_file(self, filename, kind):
        return self.observations.process_file(filename,kind)

    def count(self, key, amount=1):
        totals = self.store.get("runtime_totals", {})
        totals[key] = totals.get(key, 0) + amount
        self.store.set("runtime_totals", totals)

    def record_event(self, filename, kind, project="", evidence=None):
        return self.observations.record_event(filename,kind,project,evidence)

    def consider_help(self, project):
        return self.observations.consider_help(project)

    def consider_event(self, event, now=None):
        return self.observations.consider_event(event,now)

    def emit_notice(self, kind, key, message, now=None):
        if not self.policy.allowed(kind, key, now):
            return None
        silent = self.store.get("proactive_delivery", self.config.proactive_delivery) == "silent"
        delivery = "silent_evaluation" if silent else notify(message) if self.config.notifications else "popup_available"
        nid = self.policy.record(kind, key, message, delivery, now)
        self.count("notifications")
        return nid

    def stop_ui(self):
        from companion.ui.build import stop_ui
        stop_ui(self.private, self.token)

    def recent_memories(self, limit=12):
        return self.observations.recent_memories(limit)

    def visible_context(self):
        return self.observations.visible_context()

    def due_reminders(self, now=None):
        now = time.time() if now is None else now
        reminders = self.store.get("explicit_reminders", [])
        changed = False
        for item in reminders:
            if item.get("delivered") or now < item["due_at"]:
                continue
            nid = self.emit_notice("explicit_reminder", "reminder:" + item["id"], "你设置的事项到了：" + item["text"][:300], now)
            if nid:
                item.update(delivered=True, notice_id=nid)
                changed = True
        if changed:
            self.store.set("explicit_reminders", reminders)

    def conversation_accessible(self, row):
        return self.dialogue.conversation_accessible(row)

    def greet(self, kind, now=None):
        now = time.time() if now is None else now
        key = f"greeting:{kind}:{datetime.fromtimestamp(now).date()}"
        if not self.policy.allowed("greeting", key, now):
            return
        fallback = {"startup":"你好，我是 Companion。需要时可以来找我。", "morning":"早上好，祝你今天顺利。", "evening":"晚上好，需要帮忙时可以来找我。"}[kind]
        return self.emit_notice("greeting", key, fallback, now)

    def scheduled_greeting(self, now=None):
        now = time.time() if now is None else now
        hour = datetime.fromtimestamp(now).hour
        if 5 <= hour < 12:
            return self.greet("morning", now)
        if 18 <= hour < 24:
            return self.greet("evening", now)

    def retrieve(self, question):
        return self.dialogue.retrieve(question)

    def legacy_memory_accessible(self, row):
        return self.dialogue.legacy_memory_accessible(row)

    def escalation(self, question, trigger, memories):
        return self.agent_tasks.escalation(question,trigger,memories)

    @staticmethod
    def review_digest(raw):
        return TaskController.review_digest(raw)

    def reconcile_closed_session_rejection(self):
        return self.agent_tasks.reconcile_closed_session_rejection()

    def prepare_escalation(self, request, mode="execution", automatic=False):
        return self.agent_tasks.prepare_escalation(request,mode,automatic)

    def automatic_local_task(self):
        return self.agent_tasks.automatic_local_task()

    def ask(self, question, force_help=False, context_rows=None):
        return self.dialogue.ask(question,force_help,context_rows)

    def retention(self):
        return self.observations.retention()

    def maintain_native(self, now=None):
        return self.observations.maintain_native(now)

    def status(self):
        import psutil
        p = psutil.Process()
        cpu = p.cpu_times()
        with self.native_metrics_lock:
            native_metrics = dict(self.native_metrics)
        from companion import __version__
        return {"status":"running", "package_version":__version__, "version":"Companion "+__version__, "low_power":self.power.snapshot(), "system_resources":self.resources.latest,"inference_options":self.controls.options(),"inference_control":self.controls.public(), "service_connection":self.localpilot.connection_state(), "mode":self.config.mode, "uptime_seconds":time.time()-self.started, "service_rss_bytes":p.memory_info().rss, "service_cpu_seconds":cpu.user+cpu.system, "loop_wakeups":self.loop_wakeups, "observer":type(self.observer.observer).__name__, "observed_events":self.observed_events, "pending_files":len(self.pending), "memory_count":self.store.db.execute("SELECT count(*) FROM memories").fetchone()[0], "indexing_paused":self.store.get("indexing_paused",False), "dnd":self.store.get("dnd", self.config.dnd), "quiet_now":self.policy.quiet(), "agent":"native_service_only", "model":self.model.stats(), "model_routing":self.inference.stats(), "proactive":self.policy.summary(), "last_error":self.last_error,
                "privacy":self.privacy.status(), "native_observer":self.native.status(), "observations":self.observation_memory.status(),
                "localpilot":self.localpilot.connection_state()["status"], "escalation_tasks":self.store.get("localpilot_tasks", {}),
                "recent_errors":self.store.get("recent_errors", []), "last_recovery":self.store.get("last_recovery"),
                "totals":self.store.get("runtime_totals", {}),
                "native_metrics":native_metrics,
                "notification_count":self.store.db.execute("SELECT count(*) FROM notices").fetchone()[0],
                "ignored_count":self.store.db.execute("SELECT count(*) FROM notices WHERE status IN ('ignored','ignore','not_needed')").fetchone()[0],
                "accepted_help_count":self.store.db.execute("SELECT count(*) FROM notices WHERE status='help'").fetchone()[0],
                "old_versions_retained":self.store.db.execute("SELECT count(*) FROM source_versions WHERE current=0").fetchone()[0],
                "queue_depth":self.queue.qsize(), "last_retention":self.store.get("last_retention"),
                "db_bytes":sum(f.stat().st_size for f in self.private.root.glob("memory.sqlite3*"))}

    def feedback_health(self):
        native = self.native.status()
        reads = native.get("metrics", {}).get("read_count", 0)
        blockers = []
        if self.privacy.paused():
            blockers.append("观察已暂停")
        elif not self.privacy.native_allowed():
            blockers.append("原生观察范围尚未确认")
        elif native.get("state") != "running":
            blockers.append("原生观察未运行")
        elif reads == 0:
            blockers.append("尚未读到获准窗口内容，正在等待范围内的窗口")
        elif native.get("metrics", {}).get("static_text_snapshots", 0) == 0:
            blockers.append("已读到窗口结构，但尚未读到可访问正文或静态文字")
        if not self.config.watch_dirs:
            blockers.append("未设置文件观察目录")
        if not self.localpilot.available():
            blockers.append("LocalPilot未连接，无法取得其任务进展")
        mode = self.policy.summary()["delivery"]
        if mode == "silent":
            blockers.append("主动建议处于静默评估")
        if self.policy.quiet():
            blockers.append("勿扰或夜间静音生效；面板仍显示近期观察")
        return {"native_state":native.get("state", "UNKNOWN"), "native_consent":self.privacy.status()["native_consent"],
                "ax_reads":reads, "all_apps":self.config.native_all_apps_enabled,
                "static_text_snapshots":native.get("metrics", {}).get("static_text_snapshots", 0),
                "allowed_apps":list(self.config.native_app_allowlist),
                "file_directory_count":len(self.config.watch_dirs), "localpilot_available":self.localpilot.available(),
                "delivery":mode, "blockers":blockers,
                "presentation":"native_in_app_banner_when_enabled; does not grant OS notification permission"}

    def command(self, data):
        return self.commands.dispatch(data)

    def observation_context(self, query):
        return self.observations.observation_context(query)

    def observation_accessible(self, row):
        return self.observations.observation_accessible(row)

    @staticmethod
    def task_summary(result):
        return TaskController.task_summary(result)

    def provider_for_task(self, task_id):
        return self.agent_tasks.provider_for_task(task_id)

    def task_command(self, cmd, data):
        return self.agent_tasks.task_command(cmd,data)

    def store_task_result(self, result):
        return self.agent_tasks.store_task_result(result)

    def receive_task_update(self, task_id, result):
        return self.agent_tasks.receive_task_update(task_id,result)

    def task_feedback(self, task_id, record, result):
        return self.agent_tasks.task_feedback(task_id,record,result)

    def monitor_task(self, task_id, after=0, cloud_approved=False, provider=None):
        return self.agent_tasks.monitor_task(task_id,after,cloud_approved,provider)
