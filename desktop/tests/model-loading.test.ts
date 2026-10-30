import { describe, it, expect, vi } from "vitest";
import { ensureLocalModelLoaded } from "../src/modelLoading";
import type { Model } from "../src/domain";
const model: Model = {
  id: "local",
  model: "weights",
  adapter: "omlx",
  deployment_status: "ready",
  capabilities: [],
};
const catalog = (entry: object) => ({
  resources_supported: true,
  models: { models: [{ id: "weights", size_bytes: 1024 ** 3, ...entry }] },
});
describe("model selection loads the explicit local route", () => {
  it("loads downloaded weights within an explicit memory budget", async () => {
    const invoke = vi
      .fn()
      .mockResolvedValueOnce(catalog({ loaded: false, files_present: true }))
      .mockResolvedValueOnce({ status: "completed" });
    await ensureLocalModelLoaded(model, invoke);
    expect(invoke).toHaveBeenLastCalledWith("model_resource", {
      model: "local",
      operation: "load",
      confirmed: true,
      maxMemoryBytes: Math.ceil(3.2 * 1024 ** 3),
    });
  });
  it("does not mutate for already loaded weights", async () => {
    const invoke = vi.fn().mockResolvedValue(catalog({ loaded: true }));
    await ensureLocalModelLoaded(model, invoke);
    expect(invoke).toHaveBeenCalledTimes(1);
  });
  it("missing weights explain download before any load", async () => {
    const invoke = vi.fn().mockResolvedValue(catalog({ files_present: false }));
    await expect(ensureLocalModelLoaded(model, invoke)).rejects.toThrow(
      "没有下载完整",
    );
    expect(invoke).toHaveBeenCalledTimes(1);
  });
  it("never retries an uncertain load", async () => {
    const invoke = vi
      .fn()
      .mockResolvedValueOnce(catalog({ loaded: false }))
      .mockRejectedValueOnce(new Error("UNKNOWN"));
    await expect(ensureLocalModelLoaded(model, invoke)).rejects.toThrow(
      "UNKNOWN",
    );
    expect(invoke).toHaveBeenCalledTimes(2);
  });
});
