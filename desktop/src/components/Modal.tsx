import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
export function Modal({
  title,
  onClose,
  children,
  wide = false,
  dismissible = true,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  dismissible?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const prior = document.activeElement as HTMLElement;
    const d = ref.current;
    d?.querySelector<HTMLElement>("button,input")?.focus();
    const key = (e: KeyboardEvent) => {
      const dialogs = [
        ...document.querySelectorAll('.modal[aria-modal="true"]'),
      ];
      if (dialogs.at(-1) !== d) return;
      if (e.key === "Escape" && document.querySelector(".anchored-popover"))
        return;
      if (e.key === "Escape" && dismissible) {
        e.preventDefault();
        closeRef.current();
      }
      if (e.key === "Tab" && d) {
        const a = [
          ...d.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled), textarea, select, [tabindex="0"]',
          ),
        ];
        if (!a.length) return;
        if (e.shiftKey && document.activeElement === a[0]) {
          e.preventDefault();
          a.at(-1)?.focus();
        } else if (!e.shiftKey && document.activeElement === a.at(-1)) {
          e.preventDefault();
          a[0]?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      prior?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (dismissible && e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          {dismissible && (
            <button
              className="icon-btn"
              aria-label="关闭对话框"
              onClick={onClose}
            >
              <X size={18} />
            </button>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}
