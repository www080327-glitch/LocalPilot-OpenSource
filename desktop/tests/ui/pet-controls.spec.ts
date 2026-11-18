import { expect, test } from "@playwright/test";
import { auditBridge } from "./audit-bridge";

test("the pet size slider sends its selected size to the window and restores the default", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/?pet=bubble");
  await page.getByRole("button", { name: "宠物设置", exact: true }).click();
  const size = page.getByRole("slider", { name: "角色大小" });
  await expect(size).toHaveValue("1");
  await size.scrollIntoViewIfNeeded();
  const bounds = (await size.boundingBox())!;
  await size.click({
    position: { x: bounds.width * 0.8, y: bounds.height / 2 },
  });
  const selected = Number(await size.inputValue());
  expect(selected).toBeGreaterThan(1);
  const windowSize = () =>
    page.evaluate(
      () =>
        (window as any).fixtureCalls
          .filter(
            (c: any) =>
              c.command === "pet_action" && c.args.action === "settings",
          )
          .at(-1)?.args.value.size,
    );
  await expect.poll(windowSize).toBe(selected);

  await size.press("Home");
  await size.press("ArrowRight");
  await size.press("ArrowRight");
  await size.press("ArrowRight");
  await expect(size).toHaveValue("1");
  await expect.poll(windowSize).toBe(1);
});

test("the title bar X requests bubble collapse and an explicit reopening retains the unsent draft", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/?pet=bubble");
  const input = page.getByRole("textbox", { name: "回复 DeepSeek 娘" });
  await input.fill("留在输入框的草稿");
  await page.getByRole("button", { name: "收起", exact: true }).click();
  const actions = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (c: any) =>
        (c.command === "pet_action" &&
          ["collapse", "hide", "quit"].includes(c.args.action)) ||
        c.command === "pet_chat",
    ),
  );
  expect(actions).toEqual([
    { command: "pet_action", args: { action: "collapse", value: null } },
  ]);

  await page.evaluate(() =>
    (window as any).emitFixture("pet-state", { expanded: true, focus: true }),
  );
  await expect(input).toHaveValue("留在输入框的草稿");
  await expect(input).toBeFocused();
});
