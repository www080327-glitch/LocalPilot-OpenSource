import { describe, it, expect } from "vitest";
import { latestConversations, conversationTitle } from "../src/conversations";
import type { Task } from "../src/domain";
const task = (
  id: string,
  session_id: string,
  created_at: number,
  user_input: string,
) => ({ id, session_id, created_at, user_input }) as Task;
describe("conversation history", () => {
  const tasks = [
    task("first", "chat-a", 1, "整理数据"),
    task("next", "chat-a", 2, "继续"),
    task("other", "chat-b", 3, "写报告"),
  ];
  it("shows one latest row per real session", () =>
    expect(latestConversations(tasks).map((t) => t.id)).toEqual([
      "other",
      "next",
    ]));
  it("uses the original request rather than the model ID or latest continue", () =>
    expect(conversationTitle(tasks[1], tasks, {}, {})).toBe("整理数据"));
  it("preserves a user-assigned conversation title", () =>
    expect(
      conversationTitle(tasks[1], tasks, { "chat-a": "我的任务" }, {}),
    ).toBe("我的任务"));
});
