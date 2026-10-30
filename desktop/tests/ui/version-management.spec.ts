import { evidence } from "./evidence";
import { test, expect } from "@playwright/test";
test("browser exposes manual guide but cannot check, scan, or delete real files", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page
    .getByText("高级设置 · 服务、API、路由与诊断", { exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "版本更新与存储管理" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "检查 GUI 更新", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", {
      name: "扫描历史版本与重复 APP（只读）",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    page.getByText("UNKNOWN · 尚未检查", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "手动更新指引", exact: true }).click();
  await expect(
    page.getByText("不要替换 Core/Companion/Suite", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /删除/ })).toHaveCount(0);
  await page.screenshot({
    path: evidence("settings-browser.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 620, height: 820 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
