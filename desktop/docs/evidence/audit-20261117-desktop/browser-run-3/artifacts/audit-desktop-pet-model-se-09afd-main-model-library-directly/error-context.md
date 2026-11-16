# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: audit-desktop.spec.ts >> pet model setup opens the main model library directly
- Location: tests/ui/audit-desktop.spec.ts:75:1

# Error details

```
Error: locator.click: Test ended.
Call log:
  - waiting for getByRole('button', { name: '打开模型库配置轻聊模型' })

```

# Test source

```ts
  1   | import { expect, test } from "@playwright/test";
  2   | import { auditBridge } from "./audit-bridge";
  3   | 
  4   | test("pet reconnects its service from chat without resubmitting a question", async ({
  5   |   page,
  6   | }) => {
  7   |   await auditBridge(page, true);
  8   |   await page.goto("/?pet=bubble");
  9   |   await page.getByRole("button", { name: "连接轻聊服务", exact: true }).click();
  10  |   await expect(page.getByText("轻聊服务未连接。", { exact: true })).toHaveCount(
  11  |     0,
  12  |   );
  13  |   const calls = await page.evaluate(() => (window as any).fixtureCalls);
  14  |   expect(calls.filter((call: any) => call.command === "pet_runtime")).toEqual([
  15  |     { command: "pet_runtime", args: { action: "start" } },
  16  |   ]);
  17  |   expect(calls.filter((call: any) => call.command === "pet_chat")).toHaveLength(
  18  |     0,
  19  |   );
  20  | });
  21  | 
  22  | test("explicit pet opening focuses input and clearing a multiline draft shrinks it", async ({
  23  |   page,
  24  | }) => {
  25  |   await auditBridge(page);
  26  |   await page.goto("/?pet=bubble");
  27  |   const input = page.getByRole("textbox", { name: "回复 DeepSeek 娘" });
  28  |   await expect(input).toBeVisible();
  29  |   await page.evaluate(() =>
  30  |     (window as any).emitFixture("pet-state", { expanded: true, focus: true }),
  31  |   );
  32  |   await expect(input).toBeFocused();
  33  |   await input.fill("第一行\n第二行\n第三行\n第四行");
  34  |   const tall = (await input.boundingBox())!.height;
  35  |   await page.getByRole("button", { name: "发送消息", exact: true }).click();
  36  |   await expect(input).toHaveValue("");
  37  |   await expect
  38  |     .poll(async () => (await input.boundingBox())!.height)
  39  |     .toBeLessThan(tall);
  40  |   await expect(page.getByText("测试回复", { exact: true })).toBeVisible();
  41  | });
  42  | 
  43  | test("pet settings save a quick reminder and cancelled dialogs retain the character", async ({
  44  |   page,
  45  | }) => {
  46  |   await auditBridge(page);
  47  |   await page.goto("/?pet=bubble");
  48  |   await page.getByTitle("宠物设置", { exact: true }).click();
  49  |   await page.getByRole("button", { name: "导入个人角色素材" }).click();
  50  |   await page.getByRole("textbox", { name: "提醒内容" }).fill("喝水测试");
  51  |   const started = Date.now() / 1000;
  52  |   await page.getByRole("button", { name: "10 分钟后提醒" }).click();
  53  |   await expect(page.getByText("提醒已保存。", { exact: true })).toBeVisible();
  54  |   const writes = await page.evaluate(() =>
  55  |     (window as any).fixtureCalls.filter(
  56  |       (call: any) =>
  57  |         call.command === "pet_service" &&
  58  |         call.args.payload.command === "set_reminder",
  59  |     ),
  60  |   );
  61  |   expect(writes).toHaveLength(1);
  62  |   expect(writes[0].args.payload).toMatchObject({
  63  |     text: "喝水测试",
  64  |     confirmed: true,
  65  |   });
  66  |   expect(writes[0].args.payload.due_at).toBeGreaterThanOrEqual(started + 600);
  67  |   expect(writes[0].args.payload.due_at).toBeLessThan(started + 605);
  68  |   await page.getByRole("button", { name: /查看、导出或清理记忆/ }).click();
  69  |   await page.getByRole("button", { name: "导出数据" }).click();
  70  |   await expect(page.getByText(/已导出/)).toHaveCount(0);
  71  |   await page.getByTitle("返回聊天", { exact: true }).click();
  72  |   await expect(page.locator(".pet-header strong")).toHaveText("测试角色");
  73  | });
  74  | 
  75  | test("pet model setup opens the main model library directly", async ({
  76  |   page,
  77  | }) => {
  78  |   await auditBridge(page);
  79  |   await page.goto("/?pet=bubble");
  80  |   await page.getByTitle("宠物设置", { exact: true }).click();
  81  |   await page.getByRole("button", { name: /高级设置/ }).click();
> 82  |   await page.getByRole("button", { name: "打开模型库配置轻聊模型" }).click();
      |                                                           ^ Error: locator.click: Test ended.
  83  |   const calls = await page.evaluate(() =>
  84  |     (window as any).fixtureCalls.filter(
  85  |       (call: any) =>
  86  |         call.command === "pet_core" && call.args.action === "models",
  87  |     ),
  88  |   );
  89  |   expect(calls).toHaveLength(1);
  90  | });
  91  | 
  92  | test("system reduced motion changes propagate to the native animator live", async ({
  93  |   page,
  94  | }) => {
  95  |   await auditBridge(page);
  96  |   await page.emulateMedia({ reducedMotion: "reduce" });
  97  |   await page.goto("/?pet=character");
  98  |   await expect(page.locator(".edge-viewport")).toHaveAttribute(
  99  |     "data-reduce",
  100 |     "true",
  101 |   );
  102 |   await expect
  103 |     .poll(() =>
  104 |       page.evaluate(
  105 |         () =>
  106 |           (window as any).fixtureCalls
  107 |             .filter(
  108 |               (call: any) =>
  109 |                 call.command === "pet_action" &&
  110 |                 call.args.action === "motion_preference",
  111 |             )
  112 |             .at(-1)?.args.value,
  113 |       ),
  114 |     )
  115 |     .toBe(true);
  116 |   await page.emulateMedia({ reducedMotion: "no-preference" });
  117 |   await expect(page.locator(".edge-viewport")).toHaveAttribute(
  118 |     "data-reduce",
  119 |     "false",
  120 |   );
  121 |   await expect
  122 |     .poll(() =>
  123 |       page.evaluate(
  124 |         () =>
  125 |           (window as any).fixtureCalls
  126 |             .filter(
  127 |               (call: any) =>
  128 |                 call.command === "pet_action" &&
  129 |                 call.args.action === "motion_preference",
  130 |             )
  131 |             .at(-1)?.args.value,
  132 |       ),
  133 |     )
  134 |     .toBe(false);
  135 | });
  136 | 
  137 | test("cloud provider form submits OpenAI options and keeps credentials out of preferences", async ({
  138 |   page,
  139 | }) => {
  140 |   await auditBridge(page);
  141 |   await page.goto("/");
  142 |   await page.getByRole("button", { name: "设置", exact: true }).click();
  143 |   await page.getByText("连接云端模型", { exact: true }).first().click();
  144 |   const form = page.getByRole("region", { name: "连接云端模型" });
  145 |   await form.getByLabel("提供商", { exact: true }).selectOption("openai");
  146 |   await expect(form.getByLabel("模型", { exact: true })).toHaveValue(
  147 |     "gpt-6-luna",
  148 |   );
  149 |   const key = form.getByLabel("OpenAI API 密钥", { exact: true });
  150 |   await key.fill("fixture-only-not-a-secret-key");
  151 |   await form.getByRole("button", { name: "保存并连接" }).click();
  152 |   await expect(key).toHaveValue("");
  153 |   const calls = await page.evaluate(() =>
  154 |     (window as any).fixtureCalls.filter(
  155 |       (call: any) => call.command === "configure_cloud_key",
  156 |     ),
  157 |   );
  158 |   expect(calls).toEqual([
  159 |     {
  160 |       command: "configure_cloud_key",
  161 |       args: {
  162 |         key: "fixture-only-not-a-secret-key",
  163 |         provider: "openai",
  164 |         model: "gpt-6-luna",
  165 |         confirmed: true,
  166 |       },
  167 |     },
  168 |   ]);
  169 |   expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
  170 |     "fixture-only-not-a-secret-key",
  171 |   );
  172 |   await expect(form.getByRole("status")).toContainText("OpenAI 配置已保存");
  173 | });
  174 | 
  175 | test("long task selection sends an explicit deadline and a separate extended budget", async ({
  176 |   page,
  177 | }) => {
  178 |   await auditBridge(page);
  179 |   await page.goto("/");
  180 |   await page
  181 |     .getByRole("combobox", { name: "下次任务时限" })
  182 |     .selectOption("86400");
```