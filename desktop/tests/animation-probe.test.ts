import { describe, expect, it } from "vitest";
import { summarizeAnimationSegment } from "../src/pet/animationProbe";

describe("animation sampling uses the complete stage", () => {
  it("does not turn a short burst followed by a stall into a high frame rate", () => {
    const result = summarizeAnimationSegment({
      mode: "PEEKING",
      frames: [0, 100, 200, 1000],
      changes: [100, 200],
      visible_frames: 4,
    });
    expect(result.observed_fps).toBe(2);
    expect(result.duration_ms).toBe(1000);
    expect(result.status).toBe("CHANGING");
  });

  it("distinguishes an invisible stage from a visible static frame", () => {
    const segment = {
      mode: "RETRACTING",
      frames: [0, 1000],
      changes: [],
      visible_frames: 0,
    };
    expect(summarizeAnimationSegment(segment)).toMatchObject({
      status: "NOT_VISIBLE",
      observed_fps: 0,
    });
    expect(
      summarizeAnimationSegment({ ...segment, visible_frames: 2 }),
    ).toMatchObject({ status: "STATIC", observed_fps: 0 });
  });
});
