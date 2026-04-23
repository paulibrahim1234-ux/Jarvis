"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Responsive as ResponsiveBase } from "react-grid-layout";

// The published types don't include all runtime props (draggableHandle, etc.)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Responsive = ResponsiveBase as any;
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const LAYOUT_KEY = "jarvis-layout-v4";
const HIDDEN_KEY = "jarvis-hidden-widgets-v2";

const WIDGET_LABELS: Record<string, string> = {
  briefing: "Morning Briefing",
  calendar: "Upcoming",
  email: "Inbox",
  imessage: "Messages",
  anki: "Anki",
  pomodoro: "Pomodoro",
  week: "This Week",
  streak: "Study Streak",
  spotify: "Spotify",
  qbank: "QBank",
  nbme: "NBME Progress",
  chatbot: "Jarvis Chat",
};

const DEFAULT_LAYOUT: ReactGridLayout.Layout[] = [
  { i: "briefing",  x: 0, y: 0,  w: 8,  h: 4,  minH: 3, minW: 4 },
  { i: "chatbot",   x: 8, y: 0,  w: 4,  h: 18, minH: 6, minW: 3 },
  { i: "calendar",  x: 0, y: 4,  w: 4,  h: 7,  minH: 5, minW: 2 },
  { i: "email",     x: 4, y: 4,  w: 4,  h: 7,  minH: 5, minW: 2 },
  { i: "imessage",  x: 0, y: 11, w: 4,  h: 7,  minH: 5, minW: 2 },
  { i: "anki",      x: 4, y: 11, w: 4,  h: 7,  minH: 4, minW: 2 },
  { i: "pomodoro",  x: 0, y: 18, w: 4,  h: 6,  minH: 4, minW: 2 },
  { i: "week",      x: 4, y: 18, w: 4,  h: 6,  minH: 4, minW: 2 },
  { i: "spotify",   x: 8, y: 18, w: 4,  h: 6,  minH: 3, minW: 2 },
  { i: "streak",    x: 0, y: 24, w: 12, h: 6,  minH: 5, minW: 4 },
  { i: "qbank",     x: 0, y: 30, w: 8,  h: 9,  minH: 6, minW: 3 },
  { i: "nbme",      x: 8, y: 30, w: 4,  h: 9,  minH: 6, minW: 2 },
];

const ALL_KEYS = DEFAULT_LAYOUT.map((l) => l.i);

interface DashboardGridProps {
  widgets: Record<string, React.ReactNode>;
}

export function DashboardGrid({ widgets }: DashboardGridProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [layouts, setLayouts] = useState<ReactGridLayout.Layouts>({ lg: DEFAULT_LAYOUT });
  const [hiddenWidgets, setHiddenWidgets] = useState<Set<string>>(new Set());
  const [showPanel, setShowPanel] = useState(false);

  // Load saved state on mount
  useEffect(() => {
    const savedLayout = localStorage.getItem(LAYOUT_KEY);
    if (savedLayout) {
      try { setLayouts(JSON.parse(savedLayout)); } catch { /* keep default */ }
    }
    const savedHidden = localStorage.getItem(HIDDEN_KEY);
    if (savedHidden) {
      try { setHiddenWidgets(new Set(JSON.parse(savedHidden))); } catch { /* keep default */ }
    }
  }, []);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    setWidth(node.getBoundingClientRect().width);
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) setWidth(entry.contentRect.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Close the panel when the user clicks outside it
  useEffect(() => {
    if (!showPanel) return;
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest("[data-widgets-panel]") || target?.closest("[data-widgets-trigger]")) return;
      setShowPanel(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [showPanel]);

  const onLayoutChange = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (_current: any, allLayouts: any) => {
      setLayouts(allLayouts);
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(allLayouts));
    },
    []
  );

  const toggleWidget = useCallback((key: string) => {
    setHiddenWidgets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      localStorage.setItem(HIDDEN_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);

  const resetLayout = useCallback(() => {
    setLayouts({ lg: DEFAULT_LAYOUT });
    setHiddenWidgets(new Set());
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ lg: DEFAULT_LAYOUT }));
    localStorage.removeItem(HIDDEN_KEY);
  }, []);

  const visibleKeys = ALL_KEYS.filter((k) => !hiddenWidgets.has(k));
  const hiddenCount = hiddenWidgets.size;
  const totalCount = ALL_KEYS.length;
  const visibleCount = totalCount - hiddenCount;

  return (
    <div ref={containerRef} className="relative min-h-[200px]">
      {/* Controls — polished segmented group, reads as a real UI control */}
      <div
        className="absolute -top-1 right-0 z-20 flex items-center gap-0 rounded-lg overflow-hidden"
        style={{
          border: "1px solid var(--border-default)",
          backgroundColor: "var(--surface-1)",
          boxShadow: "var(--shadow-card)",
        }}
      >
        <button
          data-widgets-trigger
          onClick={() => setShowPanel((v) => !v)}
          className="group/btn flex items-center gap-2 px-3 h-8 transition-colors"
          style={{
            fontSize: "12px",
            fontWeight: 500,
            color: showPanel ? "var(--ink-primary)" : "var(--ink-secondary)",
            backgroundColor: showPanel ? "var(--surface-2)" : "transparent",
          }}
          title={showPanel ? "Close widget panel" : "Show widget panel"}
        >
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
          <span>Widgets</span>
          <span
            className="rounded-full px-1.5 py-[1px] tabular-nums"
            style={{
              fontSize: "10px",
              backgroundColor: hiddenCount > 0 ? "var(--status-warn-soft)" : "var(--surface-2)",
              color: hiddenCount > 0 ? "var(--status-warn)" : "var(--ink-tertiary)",
              lineHeight: 1.5,
            }}
          >
            {visibleCount}/{totalCount}
          </span>
        </button>
        <div
          aria-hidden
          style={{ width: 1, height: 16, backgroundColor: "var(--border-default)" }}
        />
        <button
          onClick={resetLayout}
          className="flex items-center gap-1.5 px-3 h-8 transition-colors hover:text-foreground"
          style={{
            fontSize: "12px",
            fontWeight: 500,
            color: "var(--ink-tertiary)",
          }}
          title="Reset layout to default"
        >
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M20 9A8 8 0 0 0 6.3 6.3L4 9m16 6a8 8 0 0 1-13.7 2.7L4 15" />
          </svg>
          Reset
        </button>
      </div>

      {/* Widget visibility panel */}
      {showPanel && (
        <div
          data-widgets-panel
          className="mb-3 mt-10"
          style={{
            borderRadius: "var(--radius-card)",
            border: "1px solid var(--border-default)",
            backgroundColor: "var(--surface-1)",
            padding: "16px",
            boxShadow: "var(--shadow-card-hover)",
          }}
        >
          <div className="flex items-center justify-between mb-3">
            <p className="jv-section-title">Toggle Widgets</p>
            <p style={{ fontSize: "11px", color: "var(--ink-muted)" }}>
              Drag the grip at the top of any card to rearrange
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {ALL_KEYS.map((key) => {
              const isVisible = !hiddenWidgets.has(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleWidget(key)}
                  className="flex items-center gap-1.5 transition-all"
                  style={{
                    fontSize: "12px",
                    fontWeight: 500,
                    padding: "5px 10px",
                    borderRadius: "var(--radius-chip)",
                    border: "1px solid",
                    borderColor: isVisible ? "var(--border-strong)" : "var(--border-subtle)",
                    backgroundColor: isVisible ? "var(--surface-2)" : "transparent",
                    color: isVisible ? "var(--ink-primary)" : "var(--ink-muted)",
                    textDecoration: isVisible ? "none" : "line-through",
                  }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      width: 6,
                      height: 6,
                      borderRadius: 999,
                      backgroundColor: isVisible ? "var(--status-live)" : "transparent",
                      border: isVisible ? "none" : "1px solid var(--border-strong)",
                    }}
                  />
                  {WIDGET_LABELS[key] || key}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Grid */}
      {width > 0 && (
        <Responsive
          className="layout"
          layouts={layouts}
          breakpoints={{ lg: 900, md: 600, sm: 0 }}
          cols={{ lg: 12, md: 8, sm: 4 }}
          rowHeight={30}
          width={width}
          onLayoutChange={onLayoutChange}
          draggableHandle=".widget-drag-handle"
          isResizable={true}
          resizeHandles={["se"]}
          compactType="vertical"
          margin={[12, 12]}
        >
          {visibleKeys.map((key) => (
            <div key={key} className="h-full w-full">
              {widgets[key]}
            </div>
          ))}
        </Responsive>
      )}
    </div>
  );
}
