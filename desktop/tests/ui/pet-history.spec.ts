import { expect, test } from "@playwright/test";
import { auditBridge } from "./audit-bridge";

const saved = [
  {
    id: "saved-user",
    role: "user",
    text: "上次约定的项目代号是青禾。",
    answer_id: null,
  },
  {
    id: "saved-answer",
    role: "assistant",
    text: "记下了，青禾的回滚验证还没有完成。",
    answer_id: "saved-answer",
  },
];

test("pet restores saved speakers after reopening without sending a model request", async ({
  page,
}) => {
  await auditBridge(page, false, {
    historyPages: [{ messages: saved, next_before: null }],
  });
  await page.goto("/?pet=bubble");
  await expect(page.locator(".pet-message.user")).toHaveText(saved[0].text);
  await expect(page.locator(".pet-message.assistant")).toContainText(
    saved[1].text,
  );
  await page.reload();
  await expect(page.locator(".pet-message.user")).toHaveText(saved[0].text);
  await expect(page.locator(".pet-message.assistant")).toContainText(
    saved[1].text,
  );
  const calls = await page.evaluate(() => (window as any).fixtureCalls);
  expect(calls.filter((call: any) => call.command === "pet_chat")).toHaveLength(
    0,
  );
  expect(
    calls.filter((call: any) => call.args.payload?.command === "pet_history"),
  ).toEqual([
    {
      command: "pet_service",
      args: { payload: { command: "pet_history", limit: 30 } },
    },
  ]);
});

test("delayed saved history preserves an unsent draft and input focus", async ({
  page,
}) => {
  await auditBridge(page, false, {
    historyPages: [{ messages: saved, next_before: null }],
    delayHistory: true,
  });
  await page.goto("/?pet=bubble");
  const input = page.getByRole("textbox", { name: "回复 DeepSeek 娘" });
  await input.fill("这是尚未发送的新草稿。\n第二行仍要保留。");
  await expect
    .poll(() => page.evaluate(() => typeof (window as any).releaseHistory))
    .toBe("function");
  await page.evaluate(() => (window as any).releaseHistory());
  await expect(page.getByText(saved[1].text, { exact: true })).toBeVisible();
  await expect(input).toHaveValue("这是尚未发送的新草稿。\n第二行仍要保留。");
  await expect(input).toBeFocused();
});

test("late hydration merges stable IDs without losing or repeating a new reply", async ({
  page,
}) => {
  const current = [
    { id: "current-user", role: "user", text: "新的问题", answer_id: null },
    {
      id: "current-answer",
      role: "assistant",
      text: "新的回复",
      answer_id: "current-answer",
    },
  ];
  await auditBridge(page, false, {
    historyPages: [{ messages: [...saved, ...current], next_before: null }],
    delayHistory: true,
    chatResult: {
      status: "ok",
      text: "新的回复",
      question_id: "current-user",
      answer_id: "current-answer",
    },
  });
  await page.goto("/?pet=bubble");
  await page
    .getByRole("textbox", { name: "回复 DeepSeek 娘" })
    .fill("新的问题");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByText("新的回复", { exact: true })).toBeVisible();
  await page.evaluate(() => (window as any).releaseHistory());
  await expect(page.locator(".pet-message")).toHaveCount(4);
  await expect(page.getByText("新的问题", { exact: true })).toHaveCount(1);
  await expect(page.getByText("新的回复", { exact: true })).toHaveCount(1);
  expect(
    await page.evaluate(
      () =>
        (window as any).fixtureCalls.filter(
          (call: any) => call.command === "pet_chat",
        ).length,
    ),
  ).toBe(1);
});

test("saved history can arrive while the current reply is still streaming", async ({
  page,
}) => {
  await auditBridge(page, false, {
    historyPages: [{ messages: saved, next_before: null }],
    delayHistory: true,
    delayChat: true,
    chatResult: {
      status: "ok",
      text: "流式回答已结束。",
      question_id: "stream-user",
      answer_id: "stream-answer",
    },
  });
  await page.goto("/?pet=bubble");
  await page
    .getByRole("textbox", { name: "回复 DeepSeek 娘" })
    .fill("当前这条仍在回答。");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect
    .poll(() => page.evaluate(() => typeof (window as any).releaseChat))
    .toBe("function");
  await page.evaluate(() => {
    const host = window as any;
    const request = host.fixtureCalls.find(
      (call: any) => call.command === "pet_chat",
    );
    host.emitFixture("pet-stream", {
      id: request.args.requestId,
      data: { event: "draft", text: "正在继续说明…" },
    });
    host.releaseHistory();
  });
  await expect(
    page.getByText("当前这条仍在回答。", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("正在继续说明…", { exact: true })).toBeVisible();
  await page.evaluate(() => (window as any).releaseChat());
  await expect(
    page.getByText("流式回答已结束。", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("正在继续说明…", { exact: true })).toHaveCount(0);
});

test("older page prepends with the exact cursor and keeps the reading position", async ({
  page,
}) => {
  const cursor = { timestamp: 100, id: "a".repeat(32) };
  const recent = Array.from({ length: 6 }, (_, index) => ({
    id: `recent-${index}`,
    role: "user",
    text: `近期消息 ${index}。这里保留较长内容，验证翻页不会跳回底部。`,
    answer_id: null,
  }));
  const older = [
    {
      id: "older",
      role: "assistant",
      text: "更早的已保存回复。",
      answer_id: "older",
    },
  ];
  await auditBridge(page, false, {
    historyPages: [
      { messages: recent, next_before: cursor },
      { messages: older, next_before: null },
    ],
  });
  await page.goto("/?pet=bubble");
  const button = page.getByRole("button", {
    name: "查看更早聊天",
    exact: true,
  });
  await button.scrollIntoViewIfNeeded();
  const first = page.getByText(recent[0].text, { exact: true });
  const top = (await first.boundingBox())!.y;
  await button.click();
  await expect(page.locator(".pet-message")).toHaveCount(7);
  await expect
    .poll(async () => Math.abs((await first.boundingBox())!.y - top))
    .toBeLessThan(3);
  const calls = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (call: any) => call.args.payload?.command === "pet_history",
    ),
  );
  expect(calls[1].args.payload).toEqual({
    command: "pet_history",
    limit: 30,
    before: cursor,
  });
  await expect(button).toHaveCount(0);
});

test("history failure retries only history and leaves the draft untouched", async ({
  page,
}) => {
  await auditBridge(page, false, {
    historyPages: [{ messages: saved, next_before: null }],
    historyFails: true,
  });
  await page.goto("/?pet=bubble");
  await page
    .getByRole("textbox", { name: "回复 DeepSeek 娘" })
    .fill("保留这个草稿。");
  await expect(
    page.getByRole("button", { name: "重试聊天记录" }),
  ).toBeVisible();
  await page.evaluate((saved) => {
    const host = window as any;
    host.fixtureHistoryFails = false;
    host.fixtureHistoryPages = [{ messages: saved, next_before: null }];
  }, saved);
  await page.getByRole("button", { name: "重试聊天记录" }).click();
  await expect(page.getByText(saved[1].text, { exact: true })).toHaveCount(1);
  await expect(
    page.getByRole("textbox", { name: "回复 DeepSeek 娘" }),
  ).toHaveValue("保留这个草稿。");
  expect(
    await page.evaluate(
      () =>
        (window as any).fixtureCalls.filter(
          (call: any) => call.command === "pet_chat",
        ).length,
    ),
  ).toBe(0);
});

test("clearing memory prevents a late saved page from restoring deleted chat", async ({
  page,
}) => {
  await auditBridge(page, false, {
    historyPages: [{ messages: saved, next_before: null }],
    delayHistory: true,
  });
  await page.goto("/?pet=bubble");
  await expect
    .poll(() => page.evaluate(() => typeof (window as any).releaseHistory))
    .toBe("function");
  await page
    .getByRole("textbox", { name: "回复 DeepSeek 娘" })
    .fill("还没发送的草稿。");
  await page.getByTitle("宠物设置", { exact: true }).click();
  await page.getByRole("button", { name: /查看、导出或清理记忆/ }).click();
  await page.getByRole("button", { name: "清理全部记忆", exact: true }).click();
  await page.getByRole("button", { name: "确认永久清理", exact: true }).click();
  await page.evaluate(() => (window as any).releaseHistory());
  await page.getByTitle("返回聊天", { exact: true }).click();
  await expect(page.getByText(saved[0].text, { exact: true })).toHaveCount(0);
  await expect(page.getByText(saved[1].text, { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("textbox", { name: "回复 DeepSeek 娘" }),
  ).toHaveValue("还没发送的草稿。");
});

test("reenabling memory preserves loaded page order, live messages and the older cursor", async ({
  page,
}) => {
  const firstCursor = { timestamp: 100, id: "a".repeat(32) };
  const olderCursor = { timestamp: 50, id: "b".repeat(32) };
  const older = {
    id: "older-saved",
    role: "user",
    text: "最早加载的历史消息。",
    answer_id: null,
  };
  await auditBridge(page, false, {
    historyPages: [
      { messages: saved, next_before: firstCursor },
      { messages: [older], next_before: olderCursor },
    ],
  });
  await page.goto("/?pet=bubble");
  await page.getByRole("button", { name: "查看更早聊天", exact: true }).click();
  await expect(page.locator(".pet-message")).toHaveCount(3);
  await expect(page.locator(".pet-message").first()).toHaveText(older.text);
  await page.getByTitle("宠物设置", { exact: true }).click();
  await page.getByRole("checkbox", { name: "保存聊天记忆" }).uncheck();
  await page.getByTitle("返回聊天", { exact: true }).click();
  await page
    .getByRole("textbox", { name: "回复 DeepSeek 娘" })
    .fill("关闭记忆期间的新消息。");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByText("测试回复", { exact: true })).toBeVisible();
  const originalOrder = await page.locator(".pet-message").allTextContents();
  await page.getByTitle("宠物设置", { exact: true }).click();
  await page.getByRole("checkbox", { name: "保存聊天记忆" }).check();
  await page.getByTitle("返回聊天", { exact: true }).click();
  expect(await page.locator(".pet-message").allTextContents()).toEqual(
    originalOrder,
  );
  const calls = () =>
    page.evaluate(() =>
      (window as any).fixtureCalls.filter(
        (call: any) => call.args.payload?.command === "pet_history",
      ),
    );
  expect(await calls()).toHaveLength(2);
  await page.getByRole("button", { name: "查看更早聊天", exact: true }).click();
  await expect.poll(async () => (await calls()).length).toBe(3);
  expect((await calls())[2].args.payload.before).toEqual(olderCursor);
});
