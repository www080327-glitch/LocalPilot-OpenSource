# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: audit-desktop.spec.ts >> pet settings save a quick reminder and cancelled dialogs retain the character
- Location: tests/ui/audit-desktop.spec.ts:43:1

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: locator.click: Test timeout of 30000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: '10 分钟后提醒' })

```

# Page snapshot

```yaml
- generic [ref=e1]:
  - generic [ref=e2]:
    - generic [ref=e3]:
      - generic [ref=e4]: ◉
      - strong [ref=e5]: 宠物设置
      - generic [ref=e6]: 仅 Companion
    - navigation [ref=e7]:
      - button "返回聊天" [ref=e8] [cursor=pointer]
      - button "宠物设置" [ref=e11] [cursor=pointer]
      - button "收起" [ref=e15] [cursor=pointer]
  - generic [ref=e19]:
    - button "导入个人角色素材" [ref=e20] [cursor=pointer]
    - heading "本机任务" [level=4] [ref=e21]
    - button "打开主窗口完成设置或查看任务" [ref=e22] [cursor=pointer]
    - button "重新连接 Core" [ref=e23] [cursor=pointer]
    - paragraph [ref=e24]: 已连接。任务与审批沿用主窗口，关闭气泡不会取消任务。
    - heading "边缘位置" [level=4] [ref=e25]
    - generic [ref=e26]:
      - button "左上探头" [ref=e27] [cursor=pointer]
      - button "右上探头" [ref=e28] [cursor=pointer]
      - button "左边探头" [ref=e29] [cursor=pointer]
      - button "右边探头" [ref=e30] [cursor=pointer]
      - button "左下探头" [ref=e31] [cursor=pointer]
      - button "右下探头" [ref=e32] [cursor=pointer]
    - button "导入当前角色探头姿态包" [ref=e33] [cursor=pointer]
    - heading "换个形象" [level=4] [ref=e34]
    - paragraph [ref=e35]: 可以导入你本机已有的透明角色图集。
    - generic [ref=e36]:
      - generic [ref=e37]: 偶尔碎碎念 · 哦鲸鲸
      - checkbox "偶尔碎碎念 · 哦鲸鲸" [checked] [ref=e38]
    - generic [ref=e39]:
      - generic [ref=e40]: 总在上方
      - checkbox "总在上方" [checked] [ref=e41]
    - generic [ref=e42]:
      - generic [ref=e43]: 轻柔动画
      - checkbox "轻柔动画" [checked] [ref=e44]
    - generic [ref=e45]:
      - generic [ref=e46]: 角色大小
      - slider "角色大小" [ref=e47]: "1"
    - generic [ref=e48]:
      - generic [ref=e49]: 安静模式
      - checkbox "安静模式" [ref=e50]
    - generic [ref=e51]:
      - generic [ref=e52]: 保护专注 · 暂停自动气泡
      - checkbox "保护专注 · 暂停自动气泡" [checked] [ref=e53]
    - generic [ref=e54]:
      - generic [ref=e55]: 允许主动提醒
      - checkbox "允许主动提醒" [ref=e56]
    - paragraph [ref=e57]: 默认不观察屏幕、不监听键盘。保护专注开启时，提醒保留在消息中，不自动弹出。
    - generic [ref=e58]:
      - generic [ref=e59]: 保存聊天记忆
      - checkbox "保存聊天记忆" [checked] [ref=e60]
    - button "查看、导出或清理记忆 ›" [ref=e61] [cursor=pointer]:
      - text: 查看、导出或清理记忆
      - generic [ref=e62]: ›
    - heading "给未来的自己留句话" [level=4] [ref=e63]
    - textbox "提醒内容" [active] [ref=e64]: 喝水测试
    - textbox "提醒时间" [ref=e65]
    - button "保存提醒" [disabled] [ref=e66]
    - button "高级设置 ›" [ref=e67] [cursor=pointer]:
      - text: 高级设置
      - generic [ref=e68]: ›
    - generic [ref=e69]:
      - button "隐藏角色" [ref=e70] [cursor=pointer]
      - button "退出宠物" [ref=e71] [cursor=pointer]
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
> 52  |   await page.getByRole("button", { name: "10 分钟后提醒" }).click();
      |                                                        ^ Error: locator.click: Test timeout of 30000ms exceeded.
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
```