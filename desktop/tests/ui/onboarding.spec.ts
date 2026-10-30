import { evidence } from "./evidence";
import { test, expect } from "@playwright/test";
test("fresh storage requires explicit onboarding, cancel never completes, survives reload", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("dialog", { name: "让 LocalPilot 按你的习惯开始" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => localStorage.getItem("lp.global.v1")),
  ).toBeNull();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("button", { name: "模型来源 完全本地", exact: true })
    .click();
  await page.screenshot({
    path: evidence("v020-first-launch-preview.png"),
  });
  await page.reload();
  await expect(
    page.getByRole("slider", { name: "模型来源", exact: true }),
  ).toHaveValue("1");
  await page
    .getByRole("button", { name: "模型来源 完全本地", exact: true })
    .click();
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  await expect(
    page.getByRole("button", { name: "调整本会话偏好" }),
  ).toContainText("完全本地");
  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "调整本会话偏好" }),
  ).toContainText("完全本地");
});
test("independent sessions snapshot defaults; settings affect only future sessions", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  await page.getByRole("button", { name: "新会话 ⌘ N", exact: true }).click();
  await page.getByRole("button", { name: "调整本会话偏好" }).click();
  await page
    .getByRole("button", { name: "模型来源 完全本地", exact: true })
    .click();
  await page.getByRole("button", { name: "新会话 ⌘ N", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "调整本会话偏好" }),
  ).toContainText("本地优先");
  const chats = page
    .getByRole("navigation", { name: "任务历史" })
    .getByRole("button");
  await chats.first().click();
  await expect(
    page.getByRole("button", { name: "调整本会话偏好" }),
  ).toContainText("完全本地");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page
    .getByText("高级设置 · 服务、API、路由与诊断", { exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "模型来源 完全云端", exact: true })
    .click();
  await dialog.getByRole("button", { name: "保存全局默认值" }).click();
  await dialog.getByRole("button", { name: "关闭对话框" }).click();
  await expect(
    page.getByRole("button", { name: "调整本会话偏好" }),
  ).toContainText("完全本地");
  await page.getByRole("button", { name: "新会话 ⌘ N", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "调整本会话偏好" }),
  ).toContainText("完全云端");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "调整本会话偏好" }),
  ).toContainText("完全云端");
});
test("system appearance, model library boundaries and reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "调整本会话偏好" }).click();
  const slider = page.getByRole("slider", { name: "模型来源", exact: true });
  await slider.focus();
  await page.keyboard.press("End");
  await expect(slider).toHaveValue("4");
  await expect(slider).toHaveAttribute("aria-valuetext", "完全云端");
  await page.screenshot({
    path: evidence("v020-preferences-light-preview.png"),
  });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.screenshot({
    path: evidence("v020-preferences-dark-preview.png"),
  });
  await page.getByRole("button", { name: "模型库", exact: false }).click();
  await expect(page.getByText("等待本地模型服务")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "下载", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: evidence("v020-model-library-preview.png"),
  });
  await page.getByRole("button", { name: "关闭对话框" }).click();
  await page.setViewportSize({ width: 620, height: 820 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("full legacy tools show parameter forms without granting execution", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page
    .getByText("高级设置 · 服务、API、路由与诊断", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "开发者工具 · 完整 CLI", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(
    page.getByRole("heading", { name: "开发者工具 · 完整 CLI" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "生成可信终端命令" }),
  ).toBeDisabled();
  const entries = page.getByRole("combobox", { name: "开发工具入口" });
  await entries.selectOption("localpilot_service.adapter");
  await expect(
    page.getByRole("checkbox", { name: "--mcp", exact: true }),
  ).toBeVisible();
  await entries.selectOption("localpilot_suite.cli/init");
  await expect(
    page.getByRole("textbox", { name: "--cloud-key-file", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "--companion-model-path", exact: true }),
  ).toBeVisible();
  await entries.selectOption("computer.cli");
  await expect(
    page.getByRole("textbox", {
      name: "--experimental-native-targets",
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: evidence("v020-full-cli-preview.png"),
  });
});
