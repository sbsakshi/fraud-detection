import { useEffect, useRef, type ReactNode } from "react";

/** Right-hand detail panel: Esc or a click on the scrim closes it, focus moves in and returns on close. */
export default function Drawer({ title, onClose, children }: { title: ReactNode; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-label="Details" tabIndex={-1} ref={ref}>
        <div className="drawer-head">
          <div style={{ minWidth: 0 }}>{title}</div>
          <button className="btn sm" onClick={onClose} aria-label="Close details">
            Close
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </>
  );
}
