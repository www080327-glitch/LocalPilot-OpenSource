import { expect, test } from "@playwright/test";
import { auditBridge } from "./audit-bridge";

test("pet reconnects its service from chat without resubmitting a question", async ({
  page,
}) => {
  await auditBridge(page, true);
  await page.goto("/?pet=bubble");
  await page.getByRole("button", { name: "连接轻聊服务", exact: true }).click();
  await expect(page.getByText("轻聊服务未连接。", { exact: true })).toHaveCount(
    0,
  );
  const calls = await page.evaluate(() => (window as any).fixtureCalls);
  expect(calls.filter((call: any) => call.command === "pet_runtime")).toEqual([
    { command: "pet_runtime", args: { action: "start" } },
  ]);
  expect(calls.filter((call: any) => call.command === "pet_chat")).toHaveLength(
    0,
  );
});

test("explicit pet opening focuses input and clearing a multiline draft shrinks it", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/?pet=bubble");
  const input = page.getByRole("textbox", { name: "回复 DeepSeek 娘" });
  await expect(input).toBeVisible();
  await page.evaluate(() =>
    (window as any).emitFixture("pet-state", { expanded: true, focus: true }),
  );
  await expect(input).toBeFocused();
  await input.fill("第一行\n第二行\n第三行\n第四行");
  const tall = (await input.boundingBox())!.height;
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(input).toHaveValue("");
  await expect
    .poll(async () => (await input.boundingBox())!.height)
    .toBeLessThan(tall);
  await expect(page.getByText("测试回复", { exact: true })).toBeVisible();
});

test("pet settings save a quick reminder and cancelled dialogs retain the character", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/?pet=bubble");
  await page.getByTitle("宠物设置", { exact: true }).click();
  await page.getByRole("button", { name: "导入个人角色素材" }).click();
  await page.getByRole("textbox", { name: "提醒内容" }).fill("喝水测试");
  const started = Date.now() / 1000;
  await page.getByRole("button", { name: "10 分钟后提醒" }).click();
  await expect(page.getByText("提醒已保存。", { exact: true })).toBeVisible();
  const writes = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (call: any) =>
        call.command === "pet_service" &&
        call.args.payload.command === "set_reminder",
    ),
  );
  expect(writes).toHaveLength(1);
  expect(writes[0].args.payload).toMatchObject({
    text: "喝水测试",
    confirmed: true,
  });
  expect(writes[0].args.payload.due_at).toBeGreaterThanOrEqual(started + 600);
  expect(writes[0].args.payload.due_at).toBeLessThan(started + 605);
  await page.getByRole("button", { name: /查看、导出或清理记忆/ }).click();
  await page.getByRole("button", { name: "导出数据" }).click();
  await expect(page.getByText(/已导出/)).toHaveCount(0);
  await page.getByTitle("返回聊天", { exact: true }).click();
  await expect(page.locator(".pet-header strong")).toHaveText("测试角色");
});

test("pet model setup opens the main model library directly", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/?pet=bubble");
  await page.getByTitle("宠物设置", { exact: true }).click();
  await page.getByRole("button", { name: /高级设置/ }).click();
  await page.getByRole("button", { name: "打开模型库配置轻聊模型" }).click();
  const calls = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (call: any) =>
        call.command === "pet_core" && call.args.action === "models",
    ),
  );
  expect(calls).toHaveLength(1);
});

test("system reduced motion changes propagate to the native animator live", async ({
  page,
}) => {
  await auditBridge(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/?pet=character");
  await expect(page.locator(".edge-viewport")).toHaveAttribute(
    "data-reduce",
    "true",
  );
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as any).fixtureCalls
            .filter(
              (call: any) =>
                call.command === "pet_action" &&
                call.args.action === "motion_preference",
            )
            .at(-1)?.args.value,
      ),
    )
    .toBe(true);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(page.locator(".edge-viewport")).toHaveAttribute(
    "data-reduce",
    "false",
  );
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as any).fixtureCalls
            .filter(
              (call: any) =>
                call.command === "pet_action" &&
                call.args.action === "motion_preference",
            )
            .at(-1)?.args.value,
      ),
    )
    .toBe(false);
});

test("cloud provider form submits OpenAI options and keeps credentials out of preferences", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByText("连接云端模型", { exact: true }).first().click();
  const form = page.getByRole("region", { name: "连接云端模型" });
  await form
    .getByRole("combobox", { name: "提供商", exact: true })
    .selectOption("openai");
  await expect(form.getByLabel("模型", { exact: true })).toHaveValue(
    "gpt-6-luna",
  );
  const key = form.getByLabel("OpenAI API 密钥", { exact: true });
  await key.fill("fixture-only-not-a-secret-key");
  await form.getByRole("button", { name: "保存并连接" }).click();
  await expect(key).toHaveValue("");
  const calls = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (call: any) => call.command === "configure_cloud_key",
    ),
  );
  expect(calls).toEqual([
    {
      command: "configure_cloud_key",
      args: {
        key: "fixture-only-not-a-secret-key",
        provider: "openai",
        model: "gpt-6-luna",
        confirmed: true,
      },
    },
  ]);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    "fixture-only-not-a-secret-key",
  );
  await expect(form.getByRole("status")).toContainText("OpenAI 配置已保存");
  await page.evaluate(() => {
    (window as any).fixtureCloudStatus = "already_configured";
  });
  await key.fill("fixture-second-unused-key");
  await form.getByRole("button", { name: "保存并连接" }).click();
  await expect(key).toHaveValue("");
  await expect(form.getByRole("status")).toContainText("保留原有密钥");
  await expect(form.getByRole("status")).not.toContainText("配置已保存");
});

test("long task selection sends an explicit deadline and a separate extended budget", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/");
  await page
    .getByRole("combobox", { name: "下次任务时限" })
    .selectOption("86400");
  await page
    .getByRole("textbox", { name: "给 LocalPilot 发送消息" })
    .fill("长任务预算测试");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByText("任务测试完成", { exact: true })).toBeVisible();
  const calls = await page.evaluate(() => (window as any).fixtureCalls);
  const session = calls.find(
    (call: any) =>
      call.command === "product_control" &&
      call.args.operation === "desktop_session",
  );
  const submit = calls.find((call: any) => call.command === "submit_task");
  expect(session.args.args).toMatchObject({
    execution_budget: "extended",
    permission_mode: "workspace",
  });
  expect(submit.args.timeoutSeconds).toBe(86400);
  await page
    .getByRole("combobox", { name: "下次任务时限" })
    .selectOption("600");
  await page
    .getByRole("textbox", { name: "给 LocalPilot 发送消息" })
    .fill("恢复普通预算");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as any).fixtureCalls.filter(
            (call: any) => call.command === "submit_task",
          ).length,
      ),
    )
    .toBe(2);
  const profile = await page.evaluate(() =>
    (window as any).fixtureCalls
      .filter(
        (call: any) =>
          call.command === "product_control" &&
          call.args.operation === "desktop_profile",
      )
      .at(-1),
  );
  expect(profile.args.args).toMatchObject({
    execution_budget: "standard",
    expected_execution_budget: "extended",
  });
});
