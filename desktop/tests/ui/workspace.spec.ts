import { evidence } from "./evidence";
import { test, expect } from "@playwright/test";
test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
});
test("honest browser preview and a single Aurora effort popover", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page
    .getByText("高级设置 · 服务、API、路由与诊断", { exact: true })
    .click();
  await page.getByRole("button", { name: "查看模拟工作区" }).click();
  await expect(page.getByText("模拟数据", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "一个更清晰的开始" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "调整思考强度" }).click();
  const sliders = page.getByRole("slider", { name: "思考强度", exact: true });
  expect(await sliders.count()).toBe(1);
  await sliders.nth(0).focus();
  await page.keyboard.press("Home");
  await expect(sliders.nth(0)).toHaveValue("0");
  await page.keyboard.press("End");
  await expect(sliders.nth(0)).toHaveValue("4");
  await page.screenshot({
    path: evidence("design-comparison-dark.png"),
  });
});
test("preview has separated verification, resizable columns, no real execution", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page
    .getByText("高级设置 · 服务、API、路由与诊断", { exact: true })
    .click();
  await page.getByRole("button", { name: "查看模拟工作区" }).click();
  const separator = page.getByRole("separator", { name: "调整侧栏宽度" });
  await separator.focus();
  await page.keyboard.press("ArrowRight");
  await expect(separator).toHaveAttribute("aria-valuenow", "270");
  await page.getByRole("tab", { name: "证据", exact: true }).click();
  await expect(
    page.getByText("Verification summary", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: evidence("workspace-dark-preview.png"),
  });
  await page.getByRole("button", { name: "切换浅色或深色主题" }).click();
  await page.screenshot({
    path: evidence("workspace-light-preview.png"),
  });
  await page
    .getByRole("textbox", { name: "给 LocalPilot 发送消息" })
    .fill("模拟消息不会执行");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "设计预览不会执行模型或工具",
  );
  await page.setViewportSize({ width: 1100, height: 940 });
  const handle = page.getByRole("separator", { name: "调整侧栏宽度" });
  const box = await handle.boundingBox();
  await page.mouse.move(box!.x + 3, box!.y + 100);
  await page.mouse.down();
  await page.mouse.move(box!.x + 800, box!.y + 100);
  await page.mouse.up();
  expect(
    await page
      .locator("main")
      .evaluate((el) => el.getBoundingClientRect().width),
  ).toBeGreaterThanOrEqual(420);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("narrow window reflows and reduced motion is respected", async ({
  page,
}) => {
  await page.setViewportSize({ width: 620, height: 820 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "切换左侧栏" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "今天，想完成什么？" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "切换左侧栏" }).click();
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page
    .getByText("高级设置 · 服务、API、路由与诊断", { exact: true })
    .click();
  await page.getByRole("button", { name: "查看模拟工作区" }).click();
  await page.getByRole("button", { name: "关闭任务详情" }).click();
  await page.getByRole("button", { name: "切换左侧栏" }).click();
  await page.screenshot({
    path: evidence("narrow-preview.png"),
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
