# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: audit-desktop.spec.ts >> explicit pet opening focuses input and clearing a multiline draft shrinks it
- Location: tests/ui/audit-desktop.spec.ts:22:1

# Error details

```
Error: expect(locator).toBeFocused() failed

Locator:  getByRole('textbox', { name: '回复 DeepSeek 娘' })
Expected: focused
Received: inactive
Timeout:  5000ms

Call log:
  - Expect "toBeFocused" getByRole('textbox', { name: '回复 DeepSeek 娘' }) with timeout 5000ms
  - waiting for getByRole('textbox', { name: '回复 DeepSeek 娘' })
    14 × locator resolved to <textarea rows="1" maxlength="4000" aria-label="回复 DeepSeek 娘" placeholder="和 DeepSeek 娘说句话…"></textarea>
       - unexpected value "inactive"

```

```yaml
- textbox "回复 DeepSeek 娘":
  - /placeholder: 和 DeepSeek 娘说句话…
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
> 32  |   await expect(input).toBeFocused();
      |                       ^ Error: expect(locator).toBeFocused() failed
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
  82  |   await page.getByRole("button", { name: "打开模型库配置轻聊模型" }).click();
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
```