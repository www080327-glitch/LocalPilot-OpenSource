import { describe, expect, it } from "vitest";
import {
  isMissingSession,
  restoredConversation,
} from "../src/hooks/useSessionRecovery";
import { initialPreferences } from "../src/preferences";
import type { Task } from "../src/domain";

const task = (id: string, created_at: number, changes: Partial<Task> = {}) =>
  ({
    id,
    session_id: "session-a",
    model: "old-model",
    created_at,
    status: "completed",
    user_input: id + " question",
    result: { output_text: id + " answer" },
    ...changes,
  }) as Task;

describe("confirmed Session absence", () => {
  it("requires the native HTTP status and structured service error code", () => {
    const missing =
      'HTTP 404 · {"error":{"code":"session_not_found","message":"Session not found"}}';
    expect(isMissingSession(missing)).toBe(true);
    expect(isMissingSession(new Error(missing))).toBe(true);
    for (const error of [
      'HTTP 404 · {"error":{"code":"task_not_found"}}',
      'HTTP 403 · {"error":{"code":"session_not_found"}}',
      'HTTP 503 · {"error":{"code":"session_not_found"}}',
      "HTTP 404: Session not found",
      "HTTP 404 · <html>not found</html>",
      "服务不可达；请检查连接或启动服务",
    ])
      expect(isMissingSession(error)).toBe(false);
  });
});

describe("restored conversation projection", () => {
  it("retains each real task once in order and selects the current Session model", () => {
    const first = task("first", 1);
    const next = task("next", 2, { session_model: "new-model" });
    const view = restoredConversation(
      next,
      [next, task("other", 3, { session_id: "session-b" }), first],
      {},
      {},
      "scope",
      initialPreferences,
      "fallback",
    );
    expect(view.messages.map((message) => message.id)).toEqual([
      "user-first",
      "answer-first",
      "user-next",
      "answer-next",
    ]);
    expect(view.model).toBe("new-model");
    expect(first.model).toBe("old-model");
  });
  it("recovers a draft only within the same service and client scope", () => {
    const current = task("first", 1);
    const drafts = {
      "session-a": {
        preferences: { ...initialPreferences, source: "local_only" as const },
        input: "unsent draft",
        title: "draft",
        model: "cached-model",
        scope: "same-client",
      },
    };
    const recovered = restoredConversation(
      current,
      [current],
      {},
      drafts,
      "same-client",
      initialPreferences,
      "fallback",
    );
    expect(recovered.input).toBe("unsent draft");
    expect(recovered.preferences.source).toBe("local_only");
    const other = restoredConversation(
      current,
      [current],
      {},
      drafts,
      "different-client",
      initialPreferences,
      "fallback",
    );
    expect(other.input).toBe("");
    expect(other.preferences).toEqual(initialPreferences);
    expect(drafts["session-a"].input).toBe("unsent draft");
  });
  it("uses the host saved original request without adding fictitious missing turns", () => {
    const current = task("first", 1, { user_input: undefined });
    const view = restoredConversation(
      current,
      [current],
      { first: { input: "host saved original" } },
      {},
      "scope",
      initialPreferences,
      "fallback",
    );
    expect(view.messages[0].text).toBe("host saved original");
    expect(view.messages).toHaveLength(2);
    const missing = restoredConversation(
      current,
      [current],
      {},
      {},
      "scope",
      initialPreferences,
      "fallback",
    );
    expect(missing.messages).toHaveLength(1);
    expect(missing.messages[0].source).toContain("此客户端未保存原始提问");
  });
});
