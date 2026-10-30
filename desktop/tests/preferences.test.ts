import { describe, it, expect } from "vitest";
import {
  initialGlobal,
  productDefaults,
  initialPreferences,
  sourceAllows,
  routingSupported,
  routeEvidence,
  taskPreferences,
} from "../src/preferences";
import { previewModels } from "../src/preview";
describe("preference authority", () => {
  it("does not treat a local primary with cloud permission as pure cloud", () =>
    expect(
      sourceAllows(
        { ...initialPreferences, source: "cloud_only" },
        {
          ...previewModels[0],
          adapter: "omlx",
          cloud_egress: "REQUIRES_APPROVAL",
        },
      ),
    ).toBe(false));
  it("restores delegated preferences from Core instead of initial defaults", () => {
    expect(
      taskPreferences(
        {
          service: {
            route_decision: {
              routing_preferences: {
                source: "local_only",
                objective: "quality",
              },
            },
          },
          thinking: { requested: "none" },
        },
        initialPreferences,
      ),
    ).toEqual({ source: "local_only", objective: "quality", effort: "none" });
    expect(
      taskPreferences({}, { ...initialPreferences, source: "cloud_first" })
        .source,
    ).toBe("cloud_first");
  });
  it("requires explicit first completion", () =>
    expect(initialGlobal.completed).toBe(false));
  it("never infers optimization or reasoning from source", () =>
    expect({ ...initialPreferences, source: "cloud_only" }).toMatchObject({
      objective: "balanced",
      effort: null,
    }));
  it("blocks unknown egress for local-only", () =>
    expect(
      sourceAllows(
        { ...initialPreferences, source: "local_only" },
        { ...previewModels[0], cloud_egress: undefined },
      ),
    ).toBe(false));
  it("requires full extension negotiation", () =>
    expect(
      routingSupported(
        { compatibility: { capabilities: ["routing_preferences_v1"] } },
        { version: "1.0" },
      ),
    ).toBe(false));
  it("accepts complete supported contract", () =>
    expect(
      routingSupported(
        { compatibility: { capabilities: ["routing_preferences_v1"] } },
        {
          version: "1.0",
          task_create_field: "routing_preferences",
          sources: [
            "local_only",
            "local_first",
            "balanced",
            "cloud_first",
            "cloud_only",
          ],
          objectives: ["speed", "quality", "efficiency", "balanced"],
          evidence_field: "service.route_decision.routing_preferences",
        },
      ),
    ).toBe(true));
  it("does not fabricate backend evidence", () =>
    expect(routeEvidence({ model: "selected-in-ui" })).toBeNull());
  it("keeps unavailable preference evidence unknown for old backend", () =>
    expect(
      routeEvidence({
        service: {
          route_decision: {
            selected: "local",
            selection: "explicit",
            backend_fallback: false,
          },
        },
      }),
    ).toEqual({
      selected: "local",
      selection: "explicit",
      backend_fallback: false,
      preferences: null,
      reason: null,
    }));
});

it("neutralizes removed optimization in new defaults without mutating historical settings", () => {
  const legacy = {
    ...initialGlobal,
    defaults: { ...initialPreferences, objective: "speed" as const },
  };
  expect(productDefaults(legacy).defaults.objective).toBe("balanced");
  expect(legacy.defaults.objective).toBe("speed");
  expect(
    taskPreferences(
      {
        service: {
          route_decision: {
            routing_preferences: { source: "local_only", objective: "speed" },
          },
        },
      },
      initialPreferences,
    ).objective,
  ).toBe("speed");
});
