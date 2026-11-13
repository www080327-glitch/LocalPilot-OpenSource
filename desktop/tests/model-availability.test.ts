import { describe, it, expect } from "vitest";
import { availableAgentModels } from "../src/modelAvailability";
import type { Model } from "../src/domain";
const model = (id: string, deployment_status: string, caps = ["tool_calling"]): Model =>
  ({ id, model: "Qwen", adapter: "omlx", cloud_egress: "LOCAL_ONLY",
     deployment_status, capabilities: caps });
describe("available Agent route picker", () => {
  it("hides undeployed and non-tool routes and collapses aliases", () => {
    expect(availableAgentModels([
      model("old", "not_deployed"),
      model("a", "ready"),
      model("alias", "ready"),
      model("chat", "ready", ["streaming"]),
    ]).map((m) => m.id)).toEqual(["a"]);
  });
});
