"use client";

import { useState, useEffect, useLayoutEffect, useCallback, useRef } from "react";
import { useEditModeStore } from "@/lib/edit-mode-store";
import { Responsive as ResponsiveBase } from "react-grid-layout";

// The published types don't include all runtime props (draggableHandle, etc.)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Responsive = ResponsiveBase as any;
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const LAYOUT_KEY = "jarvis-layout-v4";
const HIDDEN_KEY = "jarvis-hidden-widgets-v2";
const DEEP_FOCUS_KEY = "jarvis-deep-focus-v1";
const DEEP_FOCUS_EVENT = "jarvis-deep-focus-change";

// In Deep Focus mode, only these widgets render. Sizes/positions inherited
// from the user's saved layout — no re-layouting, just filter the list.
const DEEP_FOCUS_KEYS = new Set(["chatbot", "briefing", "spotify"]);

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

// WHY module scope: re-creating this object on every render causes React to
// see a new reference each cycle, which can trigger unnecessary child updates.
// Also used as the `cols` prop on <Responsive> to guarantee one source of truth.
const BREAKPOINT_COLS: Record<string, number> = { lg: 12, md: 8, sm: 4 };

const ALL_KEYS = DEFAULT_LAYOUT.map((l) => l.i);

interface DashboardGridProps {
  widgets: Record<string, React.ReactNode>;
}

export function DashboardGrid({ widgets }: DashboardGridProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const { editMode } = useEditModeStore();
  const [layouts, setLayouts] = useState<ReactGridLayout.Layouts>({ lg: DEFAULT_LAYOUT });
  const [hiddenWidgets, setHiddenWidgets] = useState<Set<string>>(new Set());
  const [showPanel, setShowPanel] = useState(false);
  const [deepFocus, setDeepFocus] = useState(false);
  const [saveConfirm, setSaveConfirm] = useState(false);
  const saveConfirmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // E4: Clear the save-confirm timer on unmount to prevent setState calls
  // on an already-unmounted component (React 18 shows a warning for this).
  useEffect(() => {
    return () => {
      if (saveConfirmTimerRef.current) clearTimeout(saveConfirmTimerRef.current);
    };
  }, []);

  // Load saved state on mount
  useEffect(() => {
    const savedLayout = localStorage.getItem(LAYOUT_KEY);
    if (savedLayout) {
      try {
        const parsed: ReactGridLayout.Layouts = JSON.parse(savedLayout);
        // Sanity-check: if any widget overflows its breakpoint's column count, fall back to default for that breakpoint.
        const sanitized: ReactGridLayout.Layouts = {};
        if (parsed && typeof parsed === "object") {
          for (const [bp, items] of Object.entries(parsed)) {
            if (!Array.isArray(items)) continue;
            const cols = BREAKPOINT_COLS[bp] ?? 12;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const hasOverflow = (items as any[]).some((item: any) => (item.x + item.w) > cols);
            // WHY clamp instead of falling back to DEFAULT_LAYOUT:
            // DEFAULT_LAYOUT is authored for lg=12 (streak.w=12, chatbot fills
            // cols 8-11, briefing.w=8). Using it as the fallback for md=8 or
            // sm=4 overflows those grids too, creating an infinite re-overflow
            // loop on viewports <900px. Per-breakpoint clamping preserves the
            // user's saved positions while bounding every widget inside cols.
            sanitized[bp] = hasOverflow
              ? DEFAULT_LAYOUT.map((item) => ({
                  ...item,
                  x: Math.min(item.x, Math.max(0, cols - 1)),
                  w: Math.min(item.w, cols - Math.min(item.x, cols - 1)),
                }))
              : (items as ReactGridLayout.Layout[]);
          }
        }
        // Schema migration: any widget present in DEFAULT_LAYOUT but absent
        // from saved layouts (e.g. user upgraded and a new widget was
        // added) renders at (0,0) on top of existing widgets. Append the
        // missing keys with their default positions so new widgets land
        // sensibly.
        for (const bp of Object.keys(sanitized)) {
          const existing = sanitized[bp] as ReactGridLayout.Layout[];
          const haveKeys = new Set(existing.map((l) => l.i));
          const missing = DEFAULT_LAYOUT.filter((l) => !haveKeys.has(l.i));
          if (missing.length) {
            sanitized[bp] = [...existing, ...missing];
          }
        }
        setLayouts(sanitized);
      } catch { /* keep default */ }
    }
    const savedHidden = localStorage.getItem(HIDDEN_KEY);
    if (savedHidden) {
      try { setHiddenWidgets(new Set(JSON.parse(savedHidden))); } catch { /* keep default */ }
    }
    try {
      setDeepFocus(localStorage.getItem(DEEP_FOCUS_KEY) === "1");
    } catch { /* ignore */ }
  }, []);

  // Listen for Deep Focus toggles from the topbar so the grid re-renders
  // immediately. Same-tab updates use a CustomEvent (the storage event only
  // fires across tabs).
  useEffect(() => {
    const onChange = (e: Event) => {
      const ce = e as CustomEvent<{ enabled: boolean }>;
      if (ce.detail) setDeepFocus(ce.detail.enabled);
    };
    window.addEventListener(DEEP_FOCUS_EVENT, onChange);
    return () => window.removeEventListener(DEEP_FOCUS_EVENT, onChange);
  }, []);

  useLayoutEffect(() => {
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

  // localStorage on iOS Safari throws QuotaExceededError when storage is
  // near full (~5MB cap, easy to hit with cached app data). Wrap every
  // setItem so the layout-change handler can never crash the grid with
  // an unhandled exception that React bubbles to an error boundary.
  const safeSet = (key: string, value: string) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Silently drop — better to lose layout persistence than to crash.
      // A future enhancement: surface a one-time toast.
    }
  };
  const safeRemove = (key: string) => {
    try { localStorage.removeItem(key); } catch { /* ignore */ }
  };

  const onLayoutChange = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (_current: any, allLayouts: any) => {
      setLayouts(allLayouts);
      safeSet(LAYOUT_KEY, JSON.stringify(allLayouts));
    },
    []
  );

  const toggleWidget = useCallback((key: string) => {
    setHiddenWidgets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      safeSet(HIDDEN_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);

  const resetLayout = useCallback(() => {
    setLayouts({ lg: DEFAULT_LAYOUT });
    setHiddenWidgets(new Set());
    safeSet(LAYOUT_KEY, JSON.stringify({ lg: DEFAULT_LAYOUT }));
    safeRemove(HIDDEN_KEY);
  }, []);

  const saveLayout = useCallback(() => {
    safeSet(LAYOUT_KEY, JSON.stringify(layouts));
    setSaveConfirm(true);
    if (saveConfirmTimerRef.current) clearTimeout(saveConfirmTimerRef.current);
    saveConfirmTimerRef.current = setTimeout(() => setSaveConfirm(false), 2000);
  }, [layouts]);

  // In Deep Focus mode, restrict to the 3-widget set regardless of the
  // user's saved hidden list — the toggle is meant to be a fast, reversible
  // override that doesn't mutate their preferences.
  const visibleKeys = deepFocus
    ? ALL_KEYS.filter((k) => DEEP_FOCUS_KEYS.has(k) && !hiddenWidgets.has(k))
    : ALL_KEYS.filter((k) => !hiddenWidgets.has(k));
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
          className="flex items-center gap-2 px-3 h-8 transition-colors hover:bg-[var(--surface-raised)]"
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
          className="flex items-center gap-1.5 px-3 h-8 transition-colors hover:text-foreground hover:bg-[var(--surface-raised)]"
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
        <div
          aria-hidden
          style={{ width: 1, height: 16, backgroundColor: "var(--border-default)" }}
        />
        <button
          onClick={saveLayout}
          className="flex items-center gap-1.5 px-3 h-8 transition-colors hover:text-foreground hover:bg-[var(--surface-raised)]"
          style={{
            fontSize: "12px",
            fontWeight: 500,
            color: saveConfirm ? "var(--status-live)" : "var(--ink-tertiary)",
          }}
          title="Save layout"
        >
          {saveConfirm ? (
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
            </svg>
          )}
          {saveConfirm ? "Saved" : "Save"}
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
          cols={BREAKPOINT_COLS}
          rowHeight={30}
          width={width}
          onLayoutChange={onLayoutChange}
          draggableHandle=".widget-drag-handle"
          // draggableCancel prevents react-grid-layout from treating clicks on
          // interactive descendants as drag initiations when the user happens
          // to hold the mouse down on a button or input for more than the drag
          // threshold (~125ms). Without this, slow-clickers see widgets move
          // instead of buttons activating. The list mirrors common interactive
          // roles/elements; `.no-drag` is the escape-hatch each widget uses.
          draggableCancel=".no-drag, button, input, textarea, select, a, [role='button'], [role='tab'], [role='switch'], [role='listitem']"
          // isDraggable and isResizable mirror editMode so the grid is fully
          // frozen when the user isn't explicitly in layout-edit mode. This
          // also disables the resize handle entirely outside edit mode so it
          // can't be accidentally triggered.
          isDraggable={editMode}
          isResizable={editMode}
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
