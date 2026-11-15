import { expect, test, type Page } from "@playwright/test";

// Only the native bridge is scripted. These checks exercise the real React
// controls; they cannot establish native capture or model training acceptance.
async function companionBridge(
  page: Page,
  active = false,
  maintenanceReturn = false,
) {
  await page.addInitScript(
    ({ active, maintenanceReturn }) => {
      const host = window as any;
      host.fixtureCalls = [];
      host.fixtureSourceRevoked = false;
      host.fixtureMeetingError = false;
      host.fixtureMeetingStatus = "error";
      host.fixtureMeetingStopStatus = null;
      const examples: any[] = [];
      let meeting = {
        state: active ? "starting" : "idle",
        label: "Fixture meeting",
        segments: 0,
        sources: { mic: { state: "starting" } },
      };
      host.isTauri = true;
      host.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: () => {} };
      host.__TAURI_INTERNALS__ = {
        metadata: {
          currentWindow: { label: "main" },
          currentWebview: { label: "main" },
        },
        transformCallback: () => 1,
        invoke: async (command: string, args: any = {}) => {
          host.fixtureCalls.push({ command, args });
          if (command === "global_preferences")
            return {
              version: 1,
              completed: true,
              defaults: {
                source: "local_first",
                objective: "balanced",
                effort: null,
              },
            };
          if (command === "profile")
            return {
              home: "/fixture/suite",
              cli: "/fixture/localpilot",
              origin: "http://127.0.0.1:9",
              workspace: "/fixture/work",
              maintenance_return: maintenanceReturn,
            };
          if (command === "product_control")
            return { grants: [] };
          if (command === "upgrade_plan")
            return {
              exit: 0,
              result: [
                {
                  upgrades: [
                    {
                      plan: {
                        id: "upgrade_fixture",
                        created_at: 1,
                        home: "/fixture/suite",
                        python: "/fixture/python",
                        components: [],
                      },
                      receipt: {
                        status: "completed",
                        finished_at: 2,
                        attempted: ["core"],
                      },
                      handoff_error: {
                        status: "handoff_failed",
                        at: 3,
                        error:
                          "Fixture helper could not restore the old version",
                      },
                      execution_allowed: true,
                    },
                  ],
                },
              ],
            };
          if (command === "api") throw Error("Fixture Core is stopped");
          if (command === "companion") {
            if (args.command === "meeting_status")
              return host.fixtureMeetingError
                ? { status: host.fixtureMeetingStatus }
                : { status: "ok", meeting };
            if (args.command === "meeting_stop") {
              if (host.fixtureMeetingStopStatus)
                return { status: host.fixtureMeetingStopStatus };
              meeting = { ...meeting, state: "stopped" };
              return { status: "ok", meeting };
            }
            if (args.command === "source_list")
              return { status: "ok", sources: [] };
            if (args.command === "training_candidates")
              return {
                status: "ok",
                candidates: [
                  {
                    answer_id: "answer_fixture",
                    question: "今天讨论了什么？",
                    answer: "原始回答",
                    purpose: "activity_qa",
                    source_count: 1,
                  },
                ],
              };
            if (args.command === "training_examples")
              return { status: "ok", examples };
            if (args.command === "training_review")
              return {
                status: "ok",
                candidate: {
                  answer_id: "answer_fixture",
                  question: "今天讨论了什么？",
                  answer: "原始回答",
                  purpose: "activity_qa",
                  observation_ids: ["observation_fixture"],
                  sources: [
                    {
                      id: "observation_fixture",
                      source_reference: "meeting-fixture.txt",
                      kind: "meeting",
                      summary: "讨论了发布计划",
                      evidence_type: "imported_text",
                      evidence_epistemic: "reported",
                      locator: "line 1",
                    },
                  ],
                },
              };
            if (args.command === "training_example_add") {
              if (host.fixtureSourceRevoked)
                return {
                  status: "unavailable",
                  text: "来源已撤销；请重新提问后再审阅。",
                };
              examples.push({
                id: "reviewed_fixture",
                ...args.args,
                available: true,
              });
              return {
                status: "ok",
                id: "reviewed_fixture",
                training: "NOT_RUN",
              };
            }
            if (args.command === "training_example_delete") {
              examples.splice(0);
              return { status: "ok", removed: 1 };
            }
          }
          return {};
        },
      };
    },
    { active, maintenanceReturn },
  );
}

async function openReview(page: Page) {
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByText("Companion 独立设置", { exact: true }).click();
  await page.getByText("人工审阅与训练样本", { exact: true }).click();
  await page
    .getByRole("button", { name: "读取可审阅回答与已保存样本" })
    .click();
  await page.getByRole("button", { name: "审阅这条回答" }).click();
  await expect(page.getByRole("textbox", { name: "训练样本回答" })).toHaveValue(
    "原始回答",
  );
}

test("Companion meeting status and stop remain available while Core is stopped", async ({
  page,
}) => {
  await companionBridge(page, true);
  await page.goto("/");
  const banner = page.locator(".meeting-capture-banner");
  await expect(banner).toContainText("会议转写正在启动");
  await page.evaluate(() => {
    (window as any).fixtureMeetingError = true;
  });
  await expect(banner).toContainText("会议采集状态待确认", { timeout: 7000 });
  await banner.getByRole("button", { name: "停止采集" }).click();
  await expect(banner).toHaveCount(0);
  const commands = await page.evaluate(() =>
    (window as any).fixtureCalls
      .filter((item: any) => item.command === "companion")
      .map((item: any) => item.args.command),
  );
  expect(
    commands.filter((name: string) => name === "meeting_stop"),
  ).toHaveLength(1);
  expect(commands).not.toContain("meeting_start");
});

for (const status of ["busy", "stopping", "UNKNOWN"]) {
  test(`meeting ${status} receipts retain the last active state and the stop control`, async ({
    page,
  }) => {
    await companionBridge(page, true);
    await page.goto("/");
    const banner = page.locator(".meeting-capture-banner");
    await expect(banner).toContainText("会议转写正在启动");
    await page.evaluate((status) => {
      (window as any).fixtureMeetingError = true;
      (window as any).fixtureMeetingStatus = status;
      (window as any).fixtureMeetingStopStatus = status;
    }, status);
    await expect(banner).toContainText("会议采集状态待确认", { timeout: 7000 });
    await banner.getByRole("button", { name: "停止采集" }).click();
    await expect(banner).toContainText("会议采集状态待确认");
    await expect(
      banner.getByRole("button", { name: "停止采集" }),
    ).toBeEnabled();
    const commands = await page.evaluate(() =>
      (window as any).fixtureCalls
        .filter((item: any) => item.command === "companion")
        .map((item: any) => item.args.command),
    );
    expect(
      commands.filter((name: string) => name === "meeting_stop"),
    ).toHaveLength(1);
    expect(commands).not.toContain("meeting_start");
  });
}

test("maintenance return opens receipts and does not hide a later helper error behind an old success", async ({
  page,
}) => {
  await companionBridge(page, false, true);
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "软件更新" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /有助手错误记录/ }).click();
  await expect(
    dialog.getByText("安装与组件验证通过", { exact: true }),
  ).toBeVisible();
  await expect(
    dialog
      .getByRole("alert")
      .filter({ hasText: "Fixture helper could not restore" }),
  ).toBeVisible();
  const executions = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (item: any) => item.command === "execute_upgrade",
    ),
  );
  expect(executions).toHaveLength(0);
});

test("reviewing a candidate does not save until the edited answer is explicitly submitted", async ({
  page,
}) => {
  await companionBridge(page);
  await page.goto("/");
  await openReview(page);
  const before = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (item: any) => item.args.command === "training_example_add",
    ),
  );
  expect(before).toHaveLength(0);
  await page
    .getByRole("textbox", { name: "训练样本回答" })
    .fill("我核对后的回答");
  await page
    .getByRole("button", { name: "保存已审阅样本", exact: true })
    .click();
  await expect(page.getByText("样本已保存；模型训练尚未运行。")).toBeVisible();
  const writes = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (item: any) => item.args.command === "training_example_add",
    ),
  );
  expect(writes).toHaveLength(1);
  expect(writes[0].args.args).toEqual({
    answer_id: "answer_fixture",
    question: "今天讨论了什么？",
    answer: "我核对后的回答",
    purpose: "activity_qa",
  });
  await page.getByRole("button", { name: "关闭审阅" }).click();
  await page.getByText("活动问答 · 今天讨论了什么？", { exact: true }).click();
  await page.getByRole("button", { name: "删除此审阅样本" }).click();
  await expect(
    page.getByText("已明确保存的样本（0）", { exact: true }),
  ).toBeVisible();
});

test("source revocation during review preserves the edited draft and does not report a saved sample", async ({
  page,
}) => {
  await companionBridge(page);
  await page.goto("/");
  await openReview(page);
  await page
    .getByRole("textbox", { name: "训练样本回答" })
    .fill("待保留的人工修改");
  await page.evaluate(() => {
    (window as any).fixtureSourceRevoked = true;
  });
  await page
    .getByRole("button", { name: "保存已审阅样本", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "来源已撤销" }),
  ).toBeVisible();
  await expect(page.getByRole("textbox", { name: "训练样本回答" })).toHaveValue(
    "待保留的人工修改",
  );
  await expect(page.getByText("样本已保存；模型训练尚未运行。")).toHaveCount(0);
});
