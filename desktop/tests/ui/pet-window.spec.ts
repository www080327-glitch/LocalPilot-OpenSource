import { test, expect } from "@playwright/test";
import { auditBridge } from "./audit-bridge";

test("pet settings offer pose recovery only after a local character is identified", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/?pet=bubble");
  await page.getByTitle("宠物设置", { exact: true }).click();
  const poses = page.getByRole("button", { name: "导入当前角色探头姿态包" });
  await expect(poses).toBeEnabled();
  await page.evaluate(() =>
    (window as any).emitFixture("pet-asset", { status: "asset_pending" }),
  );
  await expect(poses).toBeDisabled();
  await expect(page.getByText(/未找到已登记的本机角色/)).toBeVisible();
  await page.evaluate(() =>
    (window as any).emitFixture("pet-asset", {
      status: "ready",
      label: "个人角色",
    }),
  );
  await expect(poses).toBeDisabled();
  await page.evaluate(() =>
    (window as any).emitFixture("pet-asset", {
      status: "ready",
      id: "fixture",
      label: "测试角色",
      edge: { status: "invalid", error: "姿态包身份已变化" },
    }),
  );
  await expect(poses).toBeEnabled();
  await expect(
    page.getByText(/姿态包身份已变化。选择与当前角色对应的姿态包文件夹/),
  ).toBeVisible();
  await poses.click();
  await expect(page.getByText(/姿态包身份已变化/)).toHaveCount(0);
});

test("character stays transparent through hover and press", async ({
  page,
}) => {
  await page.goto("/?pet=character");
  const character = page.locator(".edge-body");
  await expect(character).toBeVisible();
  const backgrounds = () =>
    page.evaluate(() =>
      [
        document.documentElement,
        document.body,
        document.getElementById("root")!,
        document.querySelector(".edge-body")!,
      ].map((el) => getComputedStyle(el).backgroundColor),
    );
  expect(await backgrounds()).toEqual(Array(4).fill("rgba(0, 0, 0, 0)"));
  await character.hover();
  expect(await backgrounds()).toEqual(Array(4).fill("rgba(0, 0, 0, 0)"));
  await page.mouse.down();
  expect(await backgrounds()).toEqual(Array(4).fill("rgba(0, 0, 0, 0)"));
  await page.mouse.up();
});

test("task review query opens the main application", async ({ page }) => {
  await page.goto("/?petTask=review-example");
  await expect(page.locator("html")).not.toHaveAttribute("data-pet");
  await expect(page.locator(".edge-body")).toHaveCount(0);
});
