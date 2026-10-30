import { test, expect } from "@playwright/test";
test("empty new chats do not fill history and unsent drafts survive switching and reload", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const preferences = {
      source: "local_first",
      objective: "balanced",
      effort: null,
    };
    localStorage.setItem(
      "lp.chats.v1",
      JSON.stringify(
        Object.fromEntries(
          [1, 2, 3].map((n) => [
            "draft-" + n,
            { preferences, model: "", title: "新会话", scope: "||" },
          ]),
        ),
      ),
    );
  });
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  const history = page.locator(".task-list");
  for (let i = 0; i < 3; i++)
    await page.getByRole("button", { name: /新会话⌘ N/ }).click();
  await expect(history.locator(".task-row")).toHaveCount(0);
  const input = page.getByRole("textbox", { name: "给 LocalPilot 发送消息" });
  await input.fill("整理一份测试数据");
  await expect(history.locator(".task-row")).toHaveCount(1);
  await page.getByRole("button", { name: /新会话⌘ N/ }).click();
  await expect(input).toHaveValue("");
  await history.getByRole("button", { name: /整理一份测试数据/ }).click();
  await expect(input).toHaveValue("整理一份测试数据");
  await page.reload();
  await expect(input).toHaveValue("整理一份测试数据");
  await expect(history.locator(".task-row")).toHaveCount(1);
});
