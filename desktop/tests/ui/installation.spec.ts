import { test, expect } from "@playwright/test";

test("native contract: first completion requires a healthy Core and failed setup can retry", async ({
  page,
}) => {
  page.on("pageerror", (error) => console.log("Page error:", error.stack));
  await page.addInitScript(() => {
    const state = { prepared: false, attempts: 0, granted: false };
    (window as any).isTauri = true;
    (window as any).__TAURI_EVENT_PLUGIN_INTERNALS__ = {
      unregisterListener: () => {},
    };
    (window as any).__TAURI_INTERNALS__ = {
      metadata: {
        currentWindow: { label: "main" },
        currentWebview: { label: "main" },
      },
      transformCallback: () => 1,
      invoke: async (command: string, args: any = {}) => {
        if (command === "global_preferences")
          return (
            args.value || {
              version: 1,
              completed: false,
              defaults: {
                source: "local_first",
                objective: "balanced",
                effort: null,
              },
            }
          );
        if (command === "profile")
          return {
            home: state.prepared ? "/scripted/home" : "",
            cli: state.prepared ? "/scripted/localpilot" : "",
            origin: "http://127.0.0.1:8765",
            workspace: "/scripted/workspace",
          };
        if (command === "bootstrap_product") {
          state.attempts++;
          if (state.attempts === 1) throw "服务启动失败，配置保留。请重试。";
          state.prepared = true;
          return { setup: { companion_ready: true } };
        }
        if (command === "product_control") {
          if (args.operation === "workspace_grants")
            return {
              grants: state.granted
                ? [
                    {
                      id: "grant_fixture",
                      path: "/fixture-workspace",
                      usable: true,
                    },
                  ]
                : [],
            };
          if (args.operation === "inspect")
            return {
              installation: "first_launch",
              core_configured: state.prepared,
              omlx_installed: false,
              hardware: {
                chip: "Scripted Mac fixture",
                memory_bytes: 16 * 1024 ** 3,
                available_memory_bytes: 8 * 1024 ** 3,
                free_disk_bytes: 0,
                backends: [],
                models: [],
              },
              recommendation: null,
            };
          return {};
        }
        if (command === "pick_workspace") {
          state.granted = true;
          return { id: "grant_fixture" };
        }
        if (command === "api") {
          if (args.path === "/healthz") {
            if (!state.prepared) throw "尚未初始化";
            return {
              status: "ready",
              persistence: true,
              client_subject: "fixture",
              compatibility: {
                agent_service_api: "1.0",
                companion_client_contract: "1.0",
                capabilities: [
                  "durable_tasks",
                  "durable_idempotency",
                  "sse_cursor",
                  "verification_dimensions",
                  "model_registry",
                ],
              },
            };
          }
          return { models: [], tasks: [] };
        }
        if (command === "discover_suites") return { installations: [] };
        if (["pending_submissions", "submission_history"].includes(command))
          return [];
        if (command === "appearance") return { active: false };
        return {};
      },
    };
  });
  await page.goto("/");
  const finish = page.getByRole("button", { name: "完成设置，开始使用" });
  await expect(finish).toHaveCount(0);
  await page.getByRole("button", { name: "开始准备 Agent" }).click();
  const prepare = page.getByRole("button", {
    name: "一键准备 Core、Companion 与 Suite",
  });
  await prepare.click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "服务启动失败",
  );
  await expect(
    page.getByRole("button", { name: "继续 · 连接消息平台" }),
  ).toBeDisabled();
  await prepare.click();
  await expect(
    page.getByRole("button", { name: "继续 · 连接消息平台" }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "选择工作文件夹…", exact: true })
    .click();
  await page.getByRole("button", { name: "继续 · 连接消息平台" }).click();
  await page.getByRole("button", { name: "继续 · 核对完成状态" }).click();
  await finish.click();
  await expect(
    page.getByRole("dialog", { name: "让 LocalPilot 按你的习惯开始" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "授权文件夹", exact: true }),
  ).toContainText("fixture-workspace");
  await expect(
    page.getByText("标准 Agent", { exact: true }).first(),
  ).toBeVisible();
});
