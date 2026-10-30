import { useEffect, useRef, type ReactNode } from "react";
export function Popover({
  children,
  onClose,
  className,
  anchor,
}: {
  children: ReactNode;
  onClose: () => void;
  className: string;
  anchor?: React.RefObject<HTMLElement | null>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const prior = document.activeElement as HTMLElement;
    const panel = ref.current;
    panel
      ?.querySelector<HTMLElement>(
        'button:not(:disabled),input:not(:disabled),select:not(:disabled),[tabindex="0"]',
      )
      ?.focus();
    function outside(e: PointerEvent) {
      if (
        !panel?.contains(e.target as Node) &&
        !anchor?.current?.contains(e.target as Node)
      )
        close.current();
    }
    function key(e: KeyboardEvent) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        const items = [
          ...(panel?.querySelectorAll<HTMLElement>("button:not(:disabled)") ||
            []),
        ];
        const i = items.indexOf(document.activeElement as HTMLElement);
        if (items.length) {
          e.preventDefault();
          items[
            (i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length
          ]?.focus();
        }
      }
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close.current();
        prior?.focus();
      }
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      if (panel?.contains(document.activeElement)) prior?.focus();
    };
  }, []);
  return (
    <div
      ref={ref}
      className={`${className} anchored-popover`}
      role="dialog"
      aria-modal="false"
    >
      {children}
    </div>
  );
}
