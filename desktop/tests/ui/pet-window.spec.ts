import { test, expect } from "@playwright/test";

test("character stays transparent through hover and press", async ({ page }) => {
  await page.goto("/?pet=character");
  const character = page.locator(".edge-body");
  await expect(character).toBeVisible();
  const backgrounds = () => page.evaluate(() => [document.documentElement, document.body,
    document.getElementById("root")!, document.querySelector(".edge-body")!]
    .map(el => getComputedStyle(el).backgroundColor));
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
