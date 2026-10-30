import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { compatibleEffort, thinkingKey } from "../src/modelThinking";
import { Effort } from "../src/components/Effort";
import type { Model } from "../src/domain";
const local: Model = {
  id: "local",
  model: "Qwen",
  adapter: "omlx",
  deployment_status: "ready",
  capabilities: [],
  reasoning_efforts: ["none", "high"],
  default_reasoning_effort: "none",
};
const cloud: Model = {
  ...local,
  id: "cloud",
  model: "DeepSeek",
  adapter: "deepseek-native",
  reasoning_efforts: ["none", "low", "medium", "high"],
};
describe("thinking follows the selected model", () => {
  it("clears incompatible cloud efforts for the local model", () =>
    expect(compatibleEffort(local, "medium")).toBe("none"));
  it("does not send an inherited effort to a model without controls", () =>
    expect(
      compatibleEffort({ ...local, reasoning_efforts: [] }, "high"),
    ).toBeNull());
  it("keeps separately keyed preferences and shared aliases", () => {
    expect(thinkingKey(local)).not.toBe(thinkingKey(cloud));
    expect(thinkingKey({ ...local, id: "alias" })).toBe(thinkingKey(local));
    expect(compatibleEffort(cloud, "medium")).toBe("medium");
  });
  it("uses the existing slider with exactly two real levels", () => {
    const html = renderToStaticMarkup(
      <Effort options={["none", "high"]} value="high" onChange={() => {}} />,
    );
    expect(html).toContain('max="1"');
    expect(html).toContain('aria-label="思考强度 开启"');
    expect(html).toContain('aria-label="思考强度 关闭"');
    expect(html).not.toContain("RC2");
  });
});
