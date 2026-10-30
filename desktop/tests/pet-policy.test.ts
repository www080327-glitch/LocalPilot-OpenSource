import { describe, it, expect } from "vitest";
import { defaults, eligible } from "../src/pet/policy";
const notice = {
  status: "pending",
  delivery: "popup_available",
  type: "explicit_reminder",
};
const now = new Date(2026, 9, 25, 12, 0);
describe("pet reminder policy", () => {
  it("defaults to silent focus protection", () =>
    expect(eligible(defaults, notice, false, now, [])).toBe(false));
  it("requires explicit whitelist and delivery enablement", () => {
    const s = { ...defaults, proactive: true, focus: false };
    expect(eligible(s, notice, false, now, [])).toBe(true);
    expect(
      eligible(s, { ...notice, type: "screen_observation" }, false, now, []),
    ).toBe(false);
  });
  it("honors quiet hours, service DND, caps and cooldown", () => {
    const s = { ...defaults, proactive: true, focus: false };
    expect(eligible(s, notice, true, now, [])).toBe(false);
    expect(eligible(s, notice, false, new Date(2026, 9, 25, 23), [])).toBe(
      false,
    );
    expect(eligible(s, notice, false, now, [now.getTime() - 1000])).toBe(false);
    expect(eligible({ ...s, daily_limit: 0 }, notice, false, now, [])).toBe(
      false,
    );
  });
});
