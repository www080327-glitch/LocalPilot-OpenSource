import { evidence } from "./evidence";
import { test, expect } from "@playwright/test";
test("source choices, standard default, single effort popover and four permission choices", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("slider", { name: "优化目标", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  await expect(
    page.getByRole("button", { name: "标准 Agent", exact: true }),
  ).toHaveClass(/selected/);
  await page.getByRole("button", { name: "权限模式", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "工作区自动", exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^请求批准/ }).click();
  await expect(
    page.getByRole("button", { name: "权限模式", exact: true }),
  ).toContainText("请求批准");
  await page.getByRole("button", { name: "调整思考强度", exact: true }).click();
  await expect(
    page.getByRole("slider", { name: "思考强度", exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("slider", { name: "思考强度", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("slider", { name: "思考强度", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "权限模式", exact: true }).click();
  await page.getByRole("heading", { name: "今天，想完成什么？" }).click();
  await expect(page.getByText("权限", { exact: true })).toHaveCount(0);
});
test("onboarding cannot be dismissed and model library has five pages", async ({
  page,
}) => {
  await page.goto("/");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  await page
    .getByRole("button", { name: "模型库", exact: false })
    .first()
    .click();
  for (const name of ["发现模型", "推荐模型", "已下载", "正在运行", "下载任务"])
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  await page.screenshot({
    path: evidence("browser-model-library.png"),
  });
});

test("Agent profiles switch immediately without confirmation or losing the draft", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "完成设置，开始使用" }).click();
  const input = page.getByRole("textbox", { name: "给 LocalPilot 发送消息" });
  await input.fill("Keep this draft while changing the prompt.");
  await page.getByRole("button", { name: "极简 Agent", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "极简 Agent", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(input).toHaveValue("Keep this draft while changing the prompt.");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "标准 Agent", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "标准 Agent", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "今天，想完成什么？" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "了解工作区", exact: false }),
  ).toHaveCount(0);
});
