import { latestTask, errorAfterHealthyConnection } from "../src/domain";
import { describe, it, expect } from "vitest";
import {
  dimensions,
  isUnknown,
  liveEfforts,
  compatible,
  textOf,
  usageOf,
  replyText,
} from "../src/domain";
import { previewTask, previewModels } from "../src/preview";
describe("honest service state", () => {
  it("clears a stale startup failure after actual health recovery and preserves unrelated failures", () => {
    expect(
      errorAfterHealthyConnection(
        '管理操作未完成：{"error":"Core failed to start"}',
        "network unavailable",
      ),
    ).toBe("");
    expect(
      errorAfterHealthyConnection("network unavailable", "network unavailable"),
    ).toBe("");
    for (const error of [
      "文件夹授权已失效",
      "HTTP 403",
      "Active tasks remain",
      "管理操作未完成：{invalid}",
    ])
      expect(errorAfterHealthyConnection(error, "network unavailable")).toBe(
        error,
      );
  });
  it("shows live SSE after approval instead of stale approval text", () => {
    const m = {
      id: "answer",
      role: "assistant" as const,
      text: "Approval required",
      taskId: "t",
    };
    expect(
      replyText(
        m,
        { ...previewTask, status: "running", quiescent: false },
        "partial reply",
      ),
    ).toBe("partial reply");
    expect(
      replyText(
        { ...m, text: "Final reply" },
        { ...previewTask, status: "completed", quiescent: true },
        "partial reply",
      ),
    ).toBe("Final reply");
  });
  it("does not turn completed into verification passed", () => {
    const task = {
      ...previewTask,
      result: null,
      verification_summary: undefined,
    };
    expect(dimensions(task)).toEqual({
      runtime: "completed",
      delivery: "unknown",
      verification: "not_run",
      engineering: "unverified",
      outcome: "unverified",
    });
  });
  it("quarantines unknown effects even after cancellation", () =>
    expect(
      isUnknown({
        ...previewTask,
        status: "cancelled",
        receipt_summary: { unknown_effects: 1 },
      }),
    ).toBe(true));
  it("never invents RC2 per-request reasoning support", () =>
    expect(
      liveEfforts({ ...previewModels[0], reasoning_efforts: ["ultra", "pro"] }),
    ).toEqual([]));
  it("does not present absent token usage as zero", () =>
    expect(usageOf(previewTask)).toBeNull());
  it("keeps missing output usage unknown", () =>
    expect(
      usageOf({
        ...previewTask,
        result: { model_calls: [{ input_tokens: 10 }] },
      }),
    ).toEqual({ input: 10, output: null }));
  it("retains snapshot final text", () =>
    expect(textOf(previewTask)).toContain("更清晰"));
  it("fails malformed compatibility negotiation", () =>
    expect(
      compatible({
        status: "ready",
        persistence: true,
        compatibility: { agent_service_api: "2.0" },
      }),
    ).toBe(false));
});

describe("authoritative task ordering", () => {
  it("historical SSE replay cannot regress a completed or rejected task", () => {
    for (const status of ["completed", "incomplete", "cancelled"]) {
      const fresh = {
        ...previewTask,
        status,
        last_event_id: 300,
        required_action: null,
      };
      const stale = {
        ...fresh,
        status: "requires_approval",
        last_event_id: 40,
        required_action: { id: "expired" },
      };
      expect(latestTask(fresh, stale)).toBe(fresh);
      expect(latestTask(stale, fresh)).toBe(fresh);
    }
  });
});
