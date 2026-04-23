import type { ReactNode } from "react";

export function WidgetWrapper({ children }: { children: ReactNode }) {
  return (
    <div className="widget-outer relative h-full w-full group">
      {/* Drag handle — a thin strip at the very top of the card, visible on hover.
          Uses a subtle grip pill so it reads as "grabbable" without looking like UI chrome. */}
      <div
        className="widget-drag-handle absolute top-0 left-0 right-0 h-7 z-10 cursor-grab active:cursor-grabbing flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-200"
        aria-label="Drag to move widget"
      >
        <span
          className="block h-[3px] w-8 rounded-full"
          style={{ backgroundColor: "var(--border-strong)" }}
        />
      </div>

      {/* Content — overflow is contained; bottom-right corner is carved out via CSS
          so the react-resizable-handle (a sibling in the grid item) stays clickable */}
      <div className="widget-content h-full w-full overflow-hidden">
        {children}
      </div>
    </div>
  );
}
