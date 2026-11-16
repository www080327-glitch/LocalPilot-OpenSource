import { call } from "../bridge";

// The native diagnostic request is available only in an owned installation-test
// profile. No sampling runs during ordinary pet use.
export function measurePetAnimation(onError: (error: unknown) => void) {
  const started = performance.now();
  const segments: { mode: string; frames: number[]; changes: number[] }[] = [];
  let current: (typeof segments)[number] | undefined;
  let previous = "";
  let frame = 0;
  const sample = (now: number) => {
    const viewport = document.querySelector<HTMLElement>(".edge-viewport");
    const mode = viewport?.dataset.mode || "HIDDEN";
    if (
      !document.hidden &&
      ["RETRACTING", "PEEKING", "DRAGGING"].includes(mode)
    ) {
      if (!current || current.mode !== mode) {
        current = { mode, frames: [], changes: [] };
        segments.push(current);
        previous = "";
      }
      const signature = Array.from(
        viewport!.querySelectorAll<HTMLElement>(".edge-sprite,.edge-water"),
      )
        .map((element) => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return [
            rect.x,
            rect.y,
            rect.width,
            rect.height,
            style.opacity,
            style.transform,
            style.backgroundPosition,
          ].join(",");
        })
        .join("|");
      current.frames.push(now);
      if (signature !== previous) {
        current.changes.push(now);
        previous = signature;
      }
    } else current = undefined;
    if (now - started < 6000) {
      frame = requestAnimationFrame(sample);
      return;
    }
    void call("pet_action", {
      action: "animation_report",
      value: {
        user_agent: navigator.userAgent,
        device_pixel_ratio: devicePixelRatio,
        reduced_motion: matchMedia("(prefers-reduced-motion: reduce)").matches,
        duration_ms: now - started,
        segments: segments.map((segment) => ({
          ...segment,
          duration_ms: segment.frames.at(-1)! - segment.frames[0],
          observed_fps:
            segment.changes.length > 1
              ? ((segment.changes.length - 1) * 1000) /
                (segment.changes.at(-1)! - segment.changes[0])
              : 0,
        })),
      },
    }).catch(onError);
  };
  frame = requestAnimationFrame(sample);
  return () => cancelAnimationFrame(frame);
}
