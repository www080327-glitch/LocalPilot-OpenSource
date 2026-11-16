import type { Page } from "@playwright/test";
import { defaults } from "../../src/pet/policy";

// Only native transport is substituted; the application and controls remain the
// production implementation. Native rendering is qualified separately on Linux.
export async function auditBridge(page: Page, offline = false) {
  await page.addInitScript(
    ({ defaults, offline }) => {
      const host = window as any;
      const callbacks = new Map<number, (event: unknown) => void>();
      const events = new Map<number, { name: string; callback: number }>();
      let id = 0;
      host.fixtureCalls = [];
      host.fixtureOffline = offline;
      host.fixtureChatFails = false;
      host.fixtureCloudStatus = "configured";
      host.fixtureTask = null;
      host.fixtureSession = null;
      host.emitFixture = (name: string, payload: unknown) => {
        for (const [id, event] of events)
          if (event.name === name)
            callbacks.get(event.callback)?.({ id, event: name, payload });
      };
      const image = {
        url: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="24" fill="teal"/></svg>',
        width: 64,
        height: 64,
      };
      const asset = {
        ...image,
        status: "ready",
        label: "测试角色",
        id: "fixture",
        edge: { ...image, status: "ready", extras: {} },
      };
      host.fixtureEdge = {
        anchor: "RIGHT_EDGE",
        mode: "IDLE_EDGE",
        direction: "LEFT",
        activity: "idle",
        motion: true,
        phase: 1,
        chat_box: [0, 0, 140, 104],
        mini_visible: true,
        mini_glass: false,
        thought_left: false,
        thought_up: false,
        render: {
          source: "edge",
          rect: [0, 0, 64, 64],
          box: [120, 100, 120, 120],
          opacity: 1,
          angle: 0,
          tail: null,
          water: 0,
          frame: [0, 0],
        },
      };
      const caps = [
        "durable_tasks",
        "durable_idempotency",
        "sse_cursor",
        "verification_dimensions",
        "model_registry",
        "desktop_session_v1",
        "desktop_session_idempotency_v1",
        "desktop_profile_switch_v1",
        "desktop_permissions_v3",
        "desktop_execution_budget_v1",
      ];
      const model = {
        id: "local",
        model: "Fixture local model",
        adapter: "local-openai",
        deployment_status: "ready",
        capabilities: ["tool_calling"],
        cloud_egress: "LOCAL_ONLY",
      };
      host.isTauri = true;
      host.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: () => {} };
      host.__TAURI_INTERNALS__ = {
        metadata: {
          currentWindow: { label: "main" },
          currentWebview: { label: "main" },
        },
        transformCallback(callback: (event: unknown) => void) {
          callbacks.set(++id, callback);
          return id;
        },
        invoke: async (command: string, args: any = {}) => {
          host.fixtureCalls.push({ command, args });
          if (command === "plugin:event|listen") {
            events.set(++id, { name: args.event, callback: args.handler });
            return id;
          }
          if (command === "plugin:event|unlisten") {
            events.delete(args.eventId);
            return;
          }
          if (command === "pet_action") {
            if (args.action === "state")
              return {
                settings: defaults,
                expanded: false,
                native_pointer: false,
                material: { material: "solid", reduce_motion: false },
              };
            if (args.action === "settings") {
              host.emitFixture("pet-settings", args.value);
              return args.value;
            }
            return {};
          }
          if (command === "pet_asset")
            return args.action === "catalog"
              ? { items: [] }
              : args.action === "import"
                ? { cancelled: true }
                : asset;
          if (command === "pet_edge") return host.fixtureEdge;
          if (command === "pet_core") return { connected: true };
          if (command === "pet_agent") return { status: "no_task" };
          if (command === "pet_runtime") {
            host.fixtureOffline = false;
            return { status: "running" };
          }
          if (command === "pet_chat") {
            if (host.fixtureChatFails) throw Error("Fixture chat unavailable");
            return { status: "ok", text: "测试回复" };
          }
          if (command === "pet_service") {
            if (host.fixtureOffline)
              throw Error("Fixture service disconnected");
            if (args.payload.command === "pet_memory") return { enabled: true };
            if (args.payload.command === "pet_export")
              return { cancelled: true };
            return { notices: [], reminders: [], memories: [], runtime: {} };
          }
          if (command === "global_preferences")
            return {
              version: 1,
              completed: true,
              defaults: {
                source: "local_only",
                objective: "balanced",
                effort: null,
              },
            };
          if (command === "profile")
            return {
              home: "/fixture/audit",
              cli: "/fixture/localpilot",
              origin: "http://127.0.0.1:9",
              workspace: "/fixture/work",
            };
          if (command === "api") {
            if (args.path === "/healthz")
              return {
                status: "ready",
                persistence: true,
                version: "fixture",
                client_subject: "fixture",
                compatibility: {
                  agent_service_api: "1.0",
                  companion_client_contract: "1.0",
                  capabilities: caps,
                },
              };
            if (args.path === "/localpilot/v1/model-registry")
              return { models: [model] };
            if (args.path === "/localpilot/v1/tasks")
              return { tasks: host.fixtureTask ? [host.fixtureTask] : [] };
            if (args.path.startsWith("/localpilot/v1/sessions/"))
              return host.fixtureSession;
            if (args.path.startsWith("/localpilot/v1/tasks/"))
              return host.fixtureTask;
          }
          if (command === "product_control") {
            if (args.operation === "workspace_grants") return { grants: [] };
            if (args.operation === "desktop_session") {
              host.fixtureSession = {
                id: "session_fixture",
                model: "local",
                desktop_options: args.args,
              };
              return host.fixtureSession;
            }
            if (args.operation === "desktop_profile")
              return host.fixtureSession;
            return {};
          }
          if (command === "submit_task") {
            host.fixtureTask = {
              id: "task_fixture",
              session_id: "session_fixture",
              status: "completed",
              quiescent: true,
              model: "local",
              session_model: "local",
              result: { text: "任务测试完成" },
              tools: [],
              last_event_id: 1,
              required_action: null,
              timeout_seconds: args.timeoutSeconds,
              desktop_options: host.fixtureSession.desktop_options,
            };
            return host.fixtureTask;
          }
          if (command === "pending_submissions") return [];
          if (command === "submission_history") return {};
          if (command === "session_preferences") return null;
          if (command === "configure_cloud_key")
            return {
              status: host.fixtureCloudStatus,
              provider: args.provider,
              model: args.model,
            };
          if (command === "companion")
            return { status: "unavailable", meeting: { state: "idle" } };
          return {};
        },
      };
    },
    { defaults, offline },
  );
}
