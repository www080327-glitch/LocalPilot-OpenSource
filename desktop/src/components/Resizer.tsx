import { useRef, useEffect } from "react";
export function Resizer({
  side,
  width,
  onChange,
  max = 480,
}: {
  side: "left" | "right";
  width: number;
  max?: number;
  onChange: (n: number) => void;
}) {
  const cleanup = useRef<() => void>(() => {});
  useEffect(() => () => cleanup.current(), []);
  return (
    <div
      className={`resizer ${side}`}
      role="separator"
      aria-label={side === "left" ? "调整侧栏宽度" : "调整任务栏宽度"}
      aria-orientation="vertical"
      aria-valuenow={width}
      aria-valuemin={220}
      aria-valuemax={max}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          onChange(
            Math.max(
              220,
              Math.min(
                max,
                width +
                  (e.key === "ArrowRight" ? 1 : -1) *
                    (side === "left" ? 16 : -16),
              ),
            ),
          );
        }
      }}
      onPointerDown={(e) => {
        e.preventDefault();
        const start = e.clientX;
        const move = (v: PointerEvent) =>
          onChange(
            Math.max(
              220,
              Math.min(
                max,
                width + (v.clientX - start) * (side === "left" ? 1 : -1),
              ),
            ),
          );
        const end = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", end);
          document.body.classList.remove("resizing");
        };
        cleanup.current = end;
        document.body.classList.add("resizing");
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", end, { once: true });
      }}
    />
  );
}
