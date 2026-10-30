import { describe, it, expect } from "vitest";
import { shouldSubmitEnter } from "../src/inputBehavior";
const enter = {
  key: "Enter",
  shiftKey: false,
  altKey: false,
  metaKey: false,
  ctrlKey: false,
};
describe("Enter behavior and Chinese IME", () => {
  it("newline mode requires the explicit send shortcut", () => {
    expect(shouldSubmitEnter(enter, "newline", false, -Infinity, 1000)).toBe(
      false,
    );
    expect(
      shouldSubmitEnter(
        { ...enter, metaKey: true },
        "newline",
        false,
        -Infinity,
        1000,
      ),
    ).toBe(true);
  });
  it("send mode preserves Shift+Enter for newlines", () => {
    expect(shouldSubmitEnter(enter, "send", false, -Infinity, 1000)).toBe(true);
    expect(
      shouldSubmitEnter(
        { ...enter, shiftKey: true },
        "send",
        false,
        -Infinity,
        1000,
      ),
    ).toBe(false);
  });
  it("candidate confirmation cannot send in either mode", () => {
    for (const mode of ["newline", "send"] as const) {
      expect(
        shouldSubmitEnter(
          { ...enter, isComposing: true },
          mode,
          false,
          -Infinity,
          1000,
        ),
      ).toBe(false);
      expect(
        shouldSubmitEnter(
          { ...enter, keyCode: 229 },
          mode,
          false,
          -Infinity,
          1000,
        ),
      ).toBe(false);
      expect(shouldSubmitEnter(enter, mode, true, -Infinity, 1000)).toBe(false);
    }
  });
  it("guards WebKit's compositionend-before-Enter ordering", () => {
    expect(shouldSubmitEnter(enter, "send", false, 990, 1000)).toBe(false);
    expect(shouldSubmitEnter(enter, "send", false, 990, 1200)).toBe(true);
  });
});
