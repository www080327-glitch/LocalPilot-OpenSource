import { describe, expect, it } from "vitest";
import { observedModelShare, subagentTraces } from "../src/collaboration";
import type { Task, StreamEvent } from "../src/domain";

function task(id: string, result: Record<string, unknown> | null, status = "completed"): Task {
  return { id, session_id: "conversation", status, quiescent: status === "completed",
    result, model: "hybrid", tools: [], required_action: null, last_event_id: 3 };
}

function event(sequence: number, type: string, data: Record<string, unknown>): StreamEvent {
  return { sequence, type: "runtime.event", task_id: "task-2",
    data: { type, data } };
}

describe("collaboration is evidence-driven", () => {
  it("aggregates actual hybrid requests per conversation without inventing token usage", () => {
    const prior = task("task-1", { runtime_metrics: {
      hybrid: { by_backend: {
        localA: { kind: "local", calls: 2 },
        cloudB: { kind: "cloud", calls: 1 },
      } },
    } });
    const live = task("task-2", null, "running");
    const e = [
      event(1, "HybridModelUsage", { usage: { kind: "local" } }),
      event(2, "HybridModelUsage", { usage: { kind: "cloud" } }),
    ];
    const result = observedModelShare([prior, live], live, e);
    expect(result).toMatchObject({ local: 3, cloud: 2, observed: 5, unknown: 0,
      localPercent: 60, cloudPercent: 40 });
  });

  it("keeps unclassified direct model calls out of the local/cloud percentages", () => {
    const direct = task("task-1", { model_calls: [{}, {}] });
    const share = observedModelShare([direct], direct, []);
    expect(share).toMatchObject({ local: 0, cloud: 0, unknown: 2, observed: 0,
      localPercent: null, cloudPercent: null });
  });

  it("reconstructs child model, source, and lifecycle from actual emitted events", () => {
    const traces = subagentTraces([
      event(5, "SubagentCompleted", { id: "1.1", status: "completed", configured_model: "Qwen" }),
      event(1, "SubagentStarted", { id: "1.1", backend: "local", provider: "oMLX", model: "Qwen" }),
      event(2, "SubagentEvent", { id: "1.1", event: {
        type: "ModelRequestStarted", data: { model: "Qwen" },
      } }),
      event(3, "SubagentEvent", { id: "1.1", event: {
        type: "ToolCallStarted", data: { name: "read_file" },
      } }),
    ]);
    expect(traces).toHaveLength(1);
    expect(traces[0]).toMatchObject({
      id: "1.1", model: "Qwen", source: "local", status: "completed", provider: "oMLX",
    });
    expect(traces[0].steps.map((step) => step.label)).toEqual([
      "请求模型 · Qwen", "调用工具 · read_file",
    ]);
  });

  it("does not infer worker source when the start event was not retained", () => {
    const traces = subagentTraces([
      event(7, "SubagentFailed", { id: "2.1", status: "failed", configured_model: "Cloud-X" }),
    ]);
    expect(traces[0]).toMatchObject({ model: "Cloud-X", source: "unknown", status: "failed" });
  });
});
