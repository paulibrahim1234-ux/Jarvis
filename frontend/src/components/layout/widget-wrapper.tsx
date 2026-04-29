import type { ReactNode } from "react";

/**
 * Wraps every widget on the dashboard. Provides a TINY drag handle at the
 * top-center edge so users can rearrange widgets without sacrificing
 * normal click interactions inside the widget body.
 *
 * Earlier versions used a 28px-tall full-width invisible strip as the
 * drag handle. That strip ran on top of the widget's own header (z-10
 * above content), so clicks on widget tabs/buttons/links in the top
 * row of the card were silently captured by react-grid-layout and
 * triggered an accidental drag instead of the intended interaction.
 *
 * Fix: the OUTER hover area is `pointer-events-none` (purely visual —
 * fades in the grip pill on hover). The INNER 56×14 pill is
 * `pointer-events-auto` AND carries the `widget-drag-handle` class
 * react-grid-layout looks for. Only that small target initiates a drag.
 */
export function WidgetWrapper({ children }: { children: ReactNode }) {
  return (
    <div className="widget-outer relative h-full w-full group">
      {/* Hover-reveal area for the grip — visual only, no pointer events. */}
      <div
        aria-hidden
        className="pointer-events-none absolute top-0 left-0 right-0 h-6 z-10 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-200"
      >
        {/* The actual drag handle. Pointer events re-enabled here so only
            this 56×14 px target captures the drag. Clicks anywhere else
            in the top strip pass through to the widget content. */}
        <span
          className="widget-drag-handle pointer-events-auto cursor-grab active:cursor-grabbing block h-[5px] w-14 rounded-full"
          style={{ backgroundColor: "var(--border-strong)" }}
          aria-label="Drag to move widget"
          role="button"
          tabIndex={-1}
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
