import { test, expect } from "@playwright/test";
test("new permissions keep full access explicit and restore keyboard focus", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  const trigger = page.getByRole("button", { name: "权限模式", exact: true });
  await expect(trigger).toContainText("工作区写入");
  await trigger.click();
  await page.getByRole("button", { name: /^完全权限 按当前/ }).click();
  await expect(trigger).toContainText("完全权限");
  await expect(
    page.getByRole("dialog", { name: "开启完全权限？" }),
  ).toHaveCount(0);
  await trigger.click();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.getByRole("heading", { name: "今天，想完成什么？" }).click();
  await expect(page.locator(".permission-popover")).toHaveCount(0);
  await expect(
    page.getByText("自动路由待 Core 扩展", { exact: false }),
  ).toHaveCount(0);
});
test("legacy permission storage is preserved", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("lp.permissionMode", JSON.stringify("uncertain")),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  await expect(
    page.getByRole("button", { name: "权限模式", exact: true }),
  ).toContainText("原有：较高风险自动");
});
