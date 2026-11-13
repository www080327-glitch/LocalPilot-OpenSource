import { describe, it, expect } from "vitest";
import { summarizeCollaboration } from "../src/collaboration";
import type { StreamEvent } from "../src/domain";

const event = (sequence: number, type: string, data: object): StreamEvent => ({
  sequence, task_id: "task-1", type: "runtime.event", data: { type, data },
});
describe("real collaboration event accounting", () => {
  it("distinguishes parent calls, child calls, and ordinary model switching", () => {
    const events = [
      event(1, "ModelRequestStarted", { primary: "cloud", model: "cloud-main" }),
      event(2, "ModelSwitched", { primary: "local", model: "local-main" }),
      event(3, "SubagentStarted", { id: "worker-1", backend: "local", provider: "omlx", model: "Qwen", tier: "low" }),
      event(4, "SubagentEvent", { id: "worker-1", event: { type: "ModelRequestStarted", data: { primary: "local" } } }),
      event(5, "SubagentCompleted", { id: "worker-1", status: "completed" }),
      event(5, "SubagentCompleted", { id: "worker-1", status: "completed" }),
    ];
    const result = summarizeCollaboration(events);
    expect(result.localRequests).toBe(1);
    expect(result.cloudRequests).toBe(1);
    expect(result.subagents).toMatchObject([{ model: "Qwen", requests: 1, status: "completed" }]);
  });
  it("does not fabricate a ratio when no model request was observed", () => {
    expect(summarizeCollaboration([event(1, "ModelSwitched", { primary: "local" })]))
      .toMatchObject({ localRequests: 0, cloudRequests: 0, subagents: [] });
  });
});
