"use client";

import type { CSSProperties, ReactNode } from "react";
import { GripVertical } from "lucide-react";
import { useEditModeStore } from "@/lib/edit-mode-store";

/** Status of the widget's last data fetch. */
export type WidgetStatus = "fresh" | "stale" | "error";

/**
 * Convert an epoch-ms timestamp to a human-readable relative string.
 * Used for the status-dot tooltip so the user sees "Updated 2m ago"
 * rather than a raw timestamp.
 */
function relativeTime(epochMs: number): string {
  const diffMs = Date.now() - epochMs;
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return "Updated just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `Updated ${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `Updated ${diffHr}h ago`;
  return `Updated ${Math.floor(diffHr / 24)}d ago`;
}

/**
 * Wraps every widget on the dashboard.
 *
 * Drag behaviour: react-grid-layout is configured with
 * `draggableHandle=".widget-drag-handle"` so ONLY elements carrying that
 * class initiate a drag. Previously a full-width 20px z-10 strip at the top
 * carried the class, which silently swallowed clicks on any button or tab
 * that happened to render within those top 20 pixels.
 *
 * Now the class lives exclusively on the GripVertical icon wrapper that is
 * conditionally rendered in the CardHeader area — only while editMode is
 * active. When editMode is off the DOM element is fully unmounted (not just
 * hidden) so react-grid-layout finds no `.widget-drag-handle` target and
 * treats all pointer events as normal content interactions.
 */
interface WidgetWrapperProps {
  children: ReactNode;
  /** Optional freshness indicator shown as a 6px colored dot in the top-left
   *  of the wrapper. Allows at-a-glance health checking without opening the
   *  widget. */
  status?: WidgetStatus;
  /** Epoch ms of last successful data load — used to compute the tooltip. */
  lastUpdated?: number;
}

export function WidgetWrapper({ children, status, lastUpdated }: WidgetWrapperProps) {
  // editMode is read from the lightweight module-level store; it never
  // causes a parent re-render — only this wrapper and the topbar re-render
  // when the toggle fires.
  const { editMode } = useEditModeStore();

  // A11y#4 — use CSS token vars instead of Tailwind color classes so the dot
  // inherits the theme-calibrated OKLCH values that already meet 3:1 contrast,
  // avoiding the raw bg-green-500 etc. which have no guarantee in both themes
  const dotStyle: CSSProperties | null =
    status === "fresh"
      ? { backgroundColor: "var(--status-live)" }
      : status === "stale"
      ? { backgroundColor: "var(--status-warn)" }
      : status === "error"
      ? { backgroundColor: "var(--status-error)" }
      : null;

  // A11y#4 — verbose label combines state name + relative time so SR users
  // get the same info sighted users get from color + tooltip together
  const dotAriaLabel = `Status: ${status ?? "unknown"}. ${lastUpdated ? relativeTime(lastUpdated) : ""}`;

  return (
    <div className="widget-outer relative h-full w-full group/widget">
      {/*
        Grip handle — conditionally mounted ONLY in edit mode.
        Positioned absolute in the top-right of the card so it overlaps the
        CardHeader without displacing existing header content (title, badges).
        z-20 sits above the card surface but below modals/popovers (z-50).

        WHY absolute top-right rather than inline in the CardHeader?
        WidgetWrapper doesn't know each widget's internal header structure —
        each widget owns its own CardHeader markup. Absolute positioning lets
        us inject the affordance without modifying every widget's JSX.
      */}
      {editMode && (
        // A11y#7 — grip is a <button> so keyboard users can reach it; p-1.5
        // gives a ~28x28 hit target (44px min is ideal but 28 matches the
        // compact card header budget without displacing content)
        <button
          type="button"
          className="widget-drag-handle absolute top-2 right-2 z-20 flex items-center justify-center rounded p-1.5
            text-foreground/30 hover:text-foreground/70 hover:bg-foreground/10 transition-colors
            [cursor:grab] active:[cursor:grabbing]"
          aria-label="Reposition widget"
          title="Drag to move"
        >
          <GripVertical className="h-4 w-4" aria-hidden />
        </button>
      )}

      {/* Status dot — top-left corner, only when a status is provided.
          Kept outside widget content so it composites above everything
          without affecting the widget's own header layout. z-10 keeps it
          below the edit-mode grip (z-20) so grips still win on overlap. */}
      {dotStyle && (
        // A11y#4 — role="status" lets SR announce live-region changes;
        // 8px dot (was 6px) + 1px surface ring improves contrast on all backgrounds
        <span
          role="status"
          className="pointer-events-none absolute top-2 left-2 z-10 rounded-full"
          style={{
            width: 8,
            height: 8,
            boxShadow: "0 0 0 1px var(--surface-0)",
            ...dotStyle,
          }}
          title={dotAriaLabel}
          aria-label={dotAriaLabel}
        />
      )}

      {/* Widget content — full height, overflow contained. */}
      <div className="widget-content h-full w-full overflow-hidden">
        {children}
      </div>
    </div>
  );
}
