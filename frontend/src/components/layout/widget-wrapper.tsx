import type { ReactNode } from "react";

/**
 * Wraps every widget on the dashboard.
 *
 * Drag behaviour: a full-width 20px strip at the top edge is the ONLY
 * draggable area (carries `.widget-drag-handle`). It is always present in
 * the DOM so react-grid-layout always has a target, but it's transparent by
 * default and shows a subtle tinted bar + grip dots on hover so users can
 * discover it without it being visually dominant.
 *
 * Widget content (CardHeader buttons, tabs, etc.) starts below this strip,
 * so all interactive elements remain fully clickable.
 */
export function WidgetWrapper({ children }: { children: ReactNode }) {
  return (
    <div className="widget-outer relative h-full w-full group">
      {/*
        Full-width drag strip — 20px tall, always in DOM.
        Transparent at rest; subtle bg tint + grip dots appear on hover.
        z-10 keeps it above widget card content so it captures pointer events
        within those top 20px exclusively for dragging.
      */}
      <div
        className="widget-drag-handle absolute top-0 left-0 right-0 z-10 flex items-center justify-center"
        style={{ height: 20, cursor: "grab" }}
        aria-label="Drag to move widget"
        role="button"
        tabIndex={-1}
      >
        {/* Hover-revealed tint + grip dots */}
        <div
          className="absolute inset-0 rounded-t-xl opacity-0 group-hover:opacity-100 transition-opacity duration-150"
          style={{ backgroundColor: "rgba(255,255,255,0.04)" }}
          aria-hidden
        />
        <div
          className="relative flex items-center gap-[3px] opacity-0 group-hover:opacity-60 transition-opacity duration-150"
          aria-hidden
        >
          {/* Three grip dots */}
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <span
              key={i}
              className="block rounded-full"
              style={{
                width: 3,
                height: 3,
                backgroundColor: "var(--ink-tertiary, rgba(255,255,255,0.4))",
              }}
            />
          ))}
        </div>
      </div>

      {/* Content — overflow contained; react-resizable-handle (bottom-right)
          is a sibling in the grid item and remains clickable. */}
      <div className="widget-content h-full w-full overflow-hidden">
        {children}
      </div>
    </div>
  );
}
