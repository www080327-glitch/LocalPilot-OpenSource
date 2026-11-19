import { call } from "../bridge";

interface Segment {
  mode: string;
  frames: number[];
  changes: number[];
  visible_frames: number;
}

export function summarizeAnimationSegment(segment: Segment) {
  const duration = segment.frames.at(-1)! - segment.frames[0];
  return {
    ...segment,
    duration_ms: duration,
    status: !segment.visible_frames
      ? "NOT_VISIBLE"
      : segment.changes.length
        ? "CHANGING"
        : "STATIC",
    observed_fps: duration > 0 ? (segment.changes.length * 1000) / duration : 0,
  };
}

function visibleSignature(viewport: HTMLElement) {
  return Array.from(
    viewport.querySelectorAll<HTMLElement>(".edge-sprite,.edge-water"),
  )
    .map((element) => {
      if (
        element.classList.contains("edge-sprite") &&
        element.dataset.imageReady !== "true"
      )
        return "";
      const rect = element.getBoundingClientRect();
      let left = Math.max(0, rect.left),
        top = Math.max(0, rect.top),
        right = Math.min(innerWidth, rect.right),
        bottom = Math.min(innerHeight, rect.bottom),
        opacity = 1,
        insideViewport = true;
      const style = getComputedStyle(element);
      for (
        let parent: HTMLElement | null = element;
        parent;
        parent = parent.parentElement
      ) {
        const parentStyle = getComputedStyle(parent);
        if (
          parentStyle.display === "none" ||
          parentStyle.visibility !== "visible"
        )
          return "";
        opacity *= Number(parentStyle.opacity);
        if (parent !== element && insideViewport) {
          const clip = parent.getBoundingClientRect();
          if (parentStyle.overflowX !== "visible") {
            left = Math.max(left, clip.left);
            right = Math.min(right, clip.right);
          }
          if (parentStyle.overflowY !== "visible") {
            top = Math.max(top, clip.top);
            bottom = Math.min(bottom, clip.bottom);
          }
        }
        if (parent === viewport) insideViewport = false;
      }
      if (opacity === 0 || left >= right || top >= bottom) return "";
      return [
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        opacity,
        left,
        top,
        right,
        bottom,
        style.transform,
        style.backgroundPosition,
        style.backgroundSize,
        element.dataset.spriteSource || "water",
      ].join(",");
    })
    .filter(Boolean)
    .join("|");
}

// This samples compositor inputs. Record the actual window to establish visible
// pixels, including image loading, display occlusion and the OS compositor.
export function measurePetAnimation(onError: (error: unknown) => void) {
  const started = performance.now();
  const segments: Segment[] = [];
  let current: Segment | undefined;
  let previous: string | undefined;
  let frame = 0;
  const sample = (now: number) => {
    const viewport = document.querySelector<HTMLElement>(".edge-viewport");
    const mode = viewport?.dataset.mode || "HIDDEN";
    if (
      !document.hidden &&
      ["RETRACTING", "PEEKING", "DRAGGING"].includes(mode)
    ) {
      if (!current || current.mode !== mode) {
        current = { mode, frames: [], changes: [], visible_frames: 0 };
        segments.push(current);
        previous = undefined;
      }
      const signature = visibleSignature(viewport!);
      current.frames.push(now);
      if (signature) current.visible_frames++;
      if (previous !== undefined && signature !== previous)
        current.changes.push(now);
      previous = signature;
    } else current = undefined;
    if (now - started < 6000) {
      frame = requestAnimationFrame(sample);
      return;
    }
    void call("pet_action", {
      action: "animation_report",
      value: {
        sampling_method: "visible_element_styles",
        pixel_visibility_verified: false,
        status: segments.length ? "SAMPLED" : "NO_ANIMATION_STAGES",
        user_agent: navigator.userAgent,
        device_pixel_ratio: devicePixelRatio,
        reduced_motion: matchMedia("(prefers-reduced-motion: reduce)").matches,
        duration_ms: now - started,
        segments: segments.map(summarizeAnimationSegment),
      },
    }).catch(onError);
  };
  frame = requestAnimationFrame(sample);
  return () => cancelAnimationFrame(frame);
}
