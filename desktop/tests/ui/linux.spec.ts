import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/src/bridge.ts", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `export const desktop=true;
      window.linuxCalls=[];
      export async function call(command,args={}) {
        window.linuxCalls.push({command,args});
        if(command==='desktop_installation') return {platform:'linux',version:'5.0.1-rc.8',desktop_upgrade:'system_package_manager'};
        if(command==='upgrade_plan') return {exit:0,result:[{upgrades:[]}]};
        if(command==='companion' && args.command==='training_export') return {
          status:'ok',counts:{train:6,valid:2,...(args.args.test_fraction ? {test:2}:{})},training:'NOT_RUN'
        };
        return {};
      }`,
    }),
  );
});

test("Linux offers component transactions and distribution package guidance", async ({
  page,
}) => {
  await page.goto("/tests/ui/linux-fixture.html");
  await expect(
    page.getByRole("button", { name: "升级独立组件", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "GUI 与四个组件一起升级" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "仅升级 GUI", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "手动更新指引" }).click();
  await expect(page.locator(".manual-update-guide")).toContainText(
    "系统包管理器",
  );
  await expect(page.locator(".manual-update-guide")).not.toContainText(
    "codesign",
  );
});

test("training export explicitly reserves an independent test set", async ({
  page,
}) => {
  await page.goto("/tests/ui/linux-fixture.html?training");
  await page.getByText("人工审阅与训练样本", { exact: true }).click();
  await page
    .getByRole("checkbox", { name: "保留独立测试集（至少 3 组来源）" })
    .check();
  await page
    .getByRole("button", { name: "导出已审阅样本", exact: true })
    .click();
  await expect(
    page.getByText("训练 6 条 · 验证 2 条 · 独立测试 2 条"),
  ).toBeVisible();
  const calls = await page.evaluate(() => (window as any).linuxCalls);
  expect(
    calls.filter((item: any) => item.args.command === "training_export"),
  ).toEqual([
    {
      command: "companion",
      args: { command: "training_export", args: { test_fraction: 0.2 } },
    },
  ]);
  await expect(
    page.getByText("已导出人工审阅样本；未启动模型训练。"),
  ).toBeVisible();
});
