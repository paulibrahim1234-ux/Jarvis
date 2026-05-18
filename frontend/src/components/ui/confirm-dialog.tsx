"use client";

/**
 * ConfirmDialog primitive (OF-10).
 *
 * Accessible confirmation modal. Currently unused — created here for future
 * adoption by widgets that today render bespoke "Are you sure?" confirmations
 * inline. Centralizing on this primitive ensures every confirm flow gets
 * role=dialog, aria-modal, ESC-to-cancel, initial focus on Cancel (safer
 * default for destructive actions), and focus return to the original
 * trigger on close.
 *
 * Usage:
 *   <ConfirmDialog
 *     open={confirming}
 *     title="Delete score?"
 *     body={<>This cannot be undone.</>}
 *     confirmLabel="Delete"
 *     cancelLabel="Cancel"
 *     danger
 *     onConfirm={() => { doDelete(); setConfirming(false); }}
 *     onCancel={() => setConfirming(false)}
 *   />
 */

import { useEffect, useRef } from "react";

type Props = {
  open: boolean;
  title: string;
  body: React.ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

export function ConfirmDialog({
  open,
  title,
  body,
  onConfirm,
  onCancel,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement as HTMLElement | null;
    // rAF defer: focus before paint so screen-readers announce on open.
    const r = requestAnimationFrame(() => cancelRef.current?.focus());
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      cancelAnimationFrame(r);
      window.removeEventListener("keydown", onKey);
      // Return focus to whatever opened the dialog (a11y best practice).
      trigger?.focus?.();
    };
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center animate-in fade-in duration-150"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="bg-card border rounded-xl p-5 max-w-sm w-full animate-in zoom-in-95 fade-in duration-200 ease-out">
        <h3 id="confirm-dialog-title" className="text-sm font-semibold mb-2">
          {title}
        </h3>
        <div className="text-sm text-muted-foreground mb-4">{body}</div>
        <div className="flex gap-2 justify-end">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="px-3 py-1.5 text-sm rounded-md border hover:bg-muted transition-[background-color,border-color,color] duration-150 ease-out"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={
              "px-3 py-1.5 text-sm rounded-md transition-[background-color,opacity] duration-150 ease-out " +
              (danger
                ? "bg-red-500 text-white hover:bg-red-600"
                : "bg-primary text-primary-foreground hover:opacity-90")
            }
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
