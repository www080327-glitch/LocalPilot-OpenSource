import { test, expect } from "@playwright/test";
async function start(page: any) {
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
}
test("default Enter inserts a newline and settings persist send mode", async ({
  page,
}) => {
  await start(page);
  const input = page.getByRole("textbox", { name: "给 LocalPilot 发送消息" });
  await input.fill("第一行");
  await input.press("Enter");
  await expect(input).toHaveValue("第一行\n");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("combobox", { name: "回车键行为" }).selectOption("send");
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("lp.enterBehavior")))
    .toBe('"send"');
  await page.reload();
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "回车键行为" })).toHaveValue(
    "send",
  );
});
test("IME confirmation Enter and keyCode 229 never submit in send mode", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("lp.enterBehavior", '"send"'),
  );
  await start(page);
  const input = page.getByRole("textbox", { name: "给 LocalPilot 发送消息" });
  await input.fill("zhongwen");
  const results = await input.evaluate((node) => {
    const key = (extra: object = {}) => {
      const event = new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true,
        ...extra,
      });
      node.dispatchEvent(event);
      return event.defaultPrevented;
    };
    node.dispatchEvent(
      new CompositionEvent("compositionstart", { bubbles: true }),
    );
    const during = key();
    node.dispatchEvent(
      new CompositionEvent("compositionend", { bubbles: true, data: "中文" }),
    );
    const confirm = key();
    const webkit = key({ keyCode: 229 });
    return { during, confirm, webkit };
  });
  expect(results).toEqual({ during: false, confirm: false, webkit: false });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // A later intentional Enter still sends (this fixture opens connection settings).
  await page.waitForTimeout(120);
  await input.press("Enter");
  await expect(
    page.getByRole("dialog", { name: "连接与偏好设置" }),
  ).toBeVisible();
});
