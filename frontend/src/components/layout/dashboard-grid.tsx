"use client";

import { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef } from "react";
import { useEditModeStore } from "@/lib/edit-mode-store";
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
  triage: "Triage",
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
  // WHY y:39: bottom row ends at y:30+h:9=39, so triage slots cleanly below
  // without displacing any existing widget.
  { i: "triage",    x: 0, y: 39, w: 4,  h: 8,  minH: 5, minW: 3 },
];

// WHY module scope: re-creating this object on every render causes React to
// see a new reference each cycle, which can trigger unnecessary child updates.
// Also used as the `cols` prop on <Responsive> to guarantee one source of truth.
const BREAKPOINT_COLS: Record<string, number> = { lg: 12, md: 8, sm: 4 };

const ALL_KEYS = DEFAULT_LAYOUT.map((l) => l.i);

// react-grid-layout requires its direct children to be plain DOM elements
// so it can React.cloneElement them with style+className for positioning.
// A memoized custom-component wrapper silently drops those injected props,
// rendering every widget at h-full stacked vertically (the "saved layout
// doesn't reload" symptom). To memoize, memo the widget COMPONENTS
// themselves (e.g. const CalendarWidget = memo(CalendarWidget)).

// WHY module scope: these helpers have no closure over component state, so
// recreating them as inline arrows on every render wastes identity and
// defeats memoisation in callbacks that reference them (useCallback deps
// would need to include the arrow, triggering spurious re-runs).
// Stable module-scope functions also make the eslint exhaustive-deps rule
// happy without eslint-disable comments.
function safeSet(key: string, value: string) {
  // iOS Safari throws QuotaExceededError when localStorage is near its ~5MB
  // cap. Swallow silently — losing layout persistence beats crashing the grid
  // with an error that React bubbles to an error boundary.
  try { localStorage.setItem(key, value); } catch { /* ignore quota errors */ }
}
function safeRemove(key: string) {
  try { localStorage.removeItem(key); } catch { /* ignore */ }
}

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
  const [saveConfirm, setSaveConfirm] = useState(false);
  const [recoverOpen, setRecoverOpen] = useState(false);
  const [recoverList, setRecoverList] = useState<
    Array<{ key: string; layout: ReactGridLayout.Layouts; summary: string; ts: number }>
  >([]);
  const saveConfirmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Holds "HH:MM" of the last save — shown in the button label while saveConfirm is true.
  const [saveTime, setSaveTime] = useState("");

  // E4: Clear the save-confirm timer on unmount to prevent setState calls
  // on an already-unmounted component (React 18 shows a warning for this).
  useEffect(() => {
    return () => {
      if (saveConfirmTimerRef.current) clearTimeout(saveConfirmTimerRef.current);
    };
  }, []);

  // Load saved state on mount.
  // BACKEND FALLBACK: if localStorage is empty (compacted, devtools-cleared,
  // private window, etc.) we fetch the last layout the backend mirror saw and
  // hydrate localStorage from it. This guards against the loss class that
  // destroyed the user's hand-crafted layout previously.
  useEffect(() => {
    const savedLayout = localStorage.getItem(LAYOUT_KEY);
    if (!savedLayout) {
      // Fire backend fallback (best-effort). The grid will start with
      // DEFAULT_LAYOUT in the meantime; once backend responds with a real
      // saved layout, we reset state + populate localStorage.
      const backend = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";
      fetch(`${backend}/widgets/layout`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          const lay = d && d.layout;
          if (lay && Array.isArray(lay.lg)) {
            safeSet(LAYOUT_KEY, JSON.stringify(lay));
            setLayouts(lay);
            console.info("[layout] hydrated from backend mirror saved at", d.saved_at);
          }
        })
        .catch(() => { /* offline or endpoint missing — fall through to default */ });
    }
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
  }, []);

  // Toggle body.edit-mode-active so globals.css can show resize handles via
  // a body-scoped selector (avoids z-index battles with widget-content).
  useEffect(() => {
    if (editMode) {
      document.body.classList.add("edit-mode-active");
    } else {
      document.body.classList.remove("edit-mode-active");
    }
    return () => document.body.classList.remove("edit-mode-active");
  }, [editMode]);

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

  // Track edit mode in a ref so onLayoutChange (stable identity) can read
  // the live value without subscribing to it as a dep.
  const editModeRef = useRef(editMode);
  useEffect(() => { editModeRef.current = editMode; }, [editMode]);

  const onLayoutChange = useCallback(
    (_current: ReactGridLayout.Layout[], allLayouts: ReactGridLayout.Layouts) => {
      // CRITICAL: only persist when the user is actively editing. Otherwise
      // react-grid-layout's spurious onLayoutChange firings (initial mount,
      // breakpoint regeneration, post-render reflows) overwrite the user's
      // saved positions with whatever transient state RGL just produced —
      // which is exactly what destroyed the user's hand-crafted layout
      // last time (the GridChild memo ate positioning props, RGL rebuilt
      // the layout from scratch on every render, and this handler dutifully
      // saved the corrupted result over the real one).
      setLayouts(allLayouts);
      if (!editModeRef.current) return;
      safeSet(LAYOUT_KEY, JSON.stringify(allLayouts));
      // Rolling timestamped backup so future regressions are recoverable
      // without grepping the browser's leveldb files.
      try {
        const ts = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
        safeSet(`jarvis-layout-backup-${ts}`, JSON.stringify(allLayouts));
        const backups = Object.keys(localStorage)
          .filter((k) => k.startsWith("jarvis-layout-backup-"))
          .sort();
        while (backups.length > 10) {
          const old = backups.shift();
          if (old) safeRemove(old);
        }
      } catch { /* quota errors are tolerated by safeSet */ }
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
    // 1) localStorage — primary read path on next mount.
    safeSet(LAYOUT_KEY, JSON.stringify(layouts));
    // 2) Permanent named snapshot — `jarvis-layout-saved-*` keys are NOT
    //    matched by the rolling-backup cleanup (which only prunes the
    //    `jarvis-layout-backup-*` prefix). Every Save click leaves a
    //    timestamped permanent record the user can always recover.
    const ts = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
    safeSet(`jarvis-layout-saved-${ts}`, JSON.stringify(layouts));
    // 3) Backend disk mirror — survives localStorage loss (compaction,
    //    devtools clear, profile reset). Fire-and-forget; failure here
    //    doesn't affect the local save which already succeeded.
    const backend = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";
    fetch(`${backend}/widgets/layout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout: layouts }),
    }).catch((e) => {
      console.warn("Layout backend mirror failed (local save still succeeded):", e);
    });
    const now = new Date();
    setSaveTime(`${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}`);
    setSaveConfirm(true);
    if (saveConfirmTimerRef.current) clearTimeout(saveConfirmTimerRef.current);
    saveConfirmTimerRef.current = setTimeout(() => setSaveConfirm(false), 2500);
  }, [layouts]);

  // Explicit "load saved" — re-reads localStorage and replaces current layout
  // state. Useful after Deep Focus exit or any scenario where the in-memory
  // state drifts from what's persisted.
  const loadSavedLayout = useCallback(() => {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return;
    try {
      const parsed: ReactGridLayout.Layouts = JSON.parse(raw);
      if (parsed && typeof parsed === "object") setLayouts(parsed);
    } catch { /* keep current */ }
  }, []);

  // ── RECOVERY UI ────────────────────────────────────────────────────────
  // Scans localStorage for every saved layout snapshot (rolling backups,
  // explicit recovery snapshots, and current-state checkpoints) and lets
  // the user preview + apply any of them. Built because a layout-overwrite
  // bug (GridChild memo, OF-12) destroyed a user's hand-crafted layout
  // and there was no way to surface the surviving leveldb history without
  // manual forensics. Going forward this is the always-available escape
  // hatch.
  const openRecoverPanel = useCallback(() => {
    const found: typeof recoverList = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k) continue;
      const isCandidate =
        k.startsWith("jarvis-layout-backup-") ||
        k.startsWith("jarvis-layout-saved-") ||   // WHY: saveLayout() writes this prefix; was missing here
        k.startsWith("jarvis-layout-recovery-") ||
        k.startsWith("jarvis-layout-snapshot-");
      if (!isCandidate) continue;
      const raw = localStorage.getItem(k);
      if (!raw) continue;
      let layout: ReactGridLayout.Layouts;
      try { layout = JSON.parse(raw); } catch { continue; }
      const lg = layout.lg;
      if (!Array.isArray(lg) || lg.length === 0) continue;
      // Build a 1-line distinctive summary using briefing + pomodoro positions
      // (those are the ones users tend to move; helps differentiate).
      const briefing = lg.find((l) => l.i === "briefing");
      const pomodoro = lg.find((l) => l.i === "pomodoro");
      const calendar = lg.find((l) => l.i === "calendar");
      const summary = [
        briefing && `briefing(${briefing.x},${briefing.y},${briefing.w}×${briefing.h})`,
        pomodoro && `pomodoro(${pomodoro.x},${pomodoro.y},${pomodoro.w}×${pomodoro.h})`,
        calendar && `calendar(${calendar.x},${calendar.y})`,
        `${lg.length} widgets`,
      ].filter(Boolean).join(" · ");
      // Parse a millisecond ts from the key for sorting (newest first).
      let ts = 0;
      const m = k.match(/(\d{14})$/);
      if (m) {
        const s = m[1]; // YYYYMMDDHHMMSS
        ts = Date.parse(
          `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}T${s.slice(8,10)}:${s.slice(10,12)}:${s.slice(12,14)}`
        ) || 0;
      }
      found.push({ key: k, layout, summary, ts });
    }
    found.sort((a, b) => b.ts - a.ts);
    setRecoverList(found);
    setRecoverOpen(true);
  }, []);

  const applyRecovery = useCallback((entry: { key: string; layout: ReactGridLayout.Layouts }) => {
    // Snapshot current state into a timestamped pre-recovery key first so
    // the user can undo this if the choice was wrong.
    const cur = localStorage.getItem(LAYOUT_KEY);
    if (cur) {
      const ts = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
      safeSet(`jarvis-layout-pre-recovery-${ts}`, cur);
    }
    safeSet(LAYOUT_KEY, JSON.stringify(entry.layout));
    setLayouts(entry.layout);
    setRecoverOpen(false);
  }, []);

  const deleteRecoveryEntry = useCallback((key: string) => {
    safeRemove(key);
    setRecoverList((prev) => prev.filter((e) => e.key !== key));
  }, []);

  // Listen for Deep Focus modal close (Reviewer-B emits jarvis-deep-focus-change
  // with enabled:false) and re-read persisted layout so in-memory state stays
  // consistent with localStorage even if nothing triggered a mount.
  // NOTE: this effect is intentionally placed after loadSavedLayout is declared.
  useEffect(() => {
    const onFocusChange = (e: Event) => {
      const ce = e as CustomEvent<{ enabled: boolean }>;
      if (ce.detail && !ce.detail.enabled) {
        loadSavedLayout();
      }
    };
    window.addEventListener("jarvis-deep-focus-change", onFocusChange);
    return () => window.removeEventListener("jarvis-deep-focus-change", onFocusChange);
  }, [loadSavedLayout]);

  // Decorate every layout item:
  //   view mode  → static: true  (hard-disables drag/resize at GridItem layer)
  //   edit mode  → omit static   (don't set static: false — RGL v2.2.3 retains
  //                               stale disabled:true when static is explicitly false;
  //                               omitting it lets RGL derive from isDraggable/isResizable)
  // The decoration is derived (not stored) so toggling never mutates saved positions.
  const decoratedLayouts = useMemo(() => {
    const result: ReactGridLayout.Layouts = {};
    for (const [bp, items] of Object.entries(layouts)) {
      result[bp] = (items as ReactGridLayout.Layout[]).map((it) => {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { static: _drop, ...rest } = it as ReactGridLayout.Layout & { static?: boolean };
        void _drop;
        return editMode ? rest : { ...rest, static: true };
      });
    }
    return result;
  }, [layouts, editMode]);

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
          {saveConfirm ? `Saved ${saveTime}` : "Save"}
        </button>
        <div
          aria-hidden
          style={{ width: 1, height: 16, backgroundColor: "var(--border-default)" }}
        />
        <button
          onClick={loadSavedLayout}
          className="flex items-center gap-1.5 px-3 h-8 transition-colors hover:text-foreground hover:bg-[var(--surface-raised)]"
          style={{
            fontSize: "12px",
            fontWeight: 500,
            color: "var(--ink-tertiary)",
          }}
          title="Reload layout from last save"
        >
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M4 9a8 8 0 1 1 0 6" />
          </svg>
          Load
        </button>
        <div
          aria-hidden
          style={{ width: 1, height: 16, backgroundColor: "var(--border-default)" }}
        />
        <button
          onClick={openRecoverPanel}
          className="flex items-center gap-1.5 px-3 h-8 transition-colors hover:text-foreground hover:bg-[var(--surface-raised)]"
          style={{
            fontSize: "12px",
            fontWeight: 600,
            color: "var(--accent)",
          }}
          title="Browse and restore any saved layout backup"
        >
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 12a9 9 0 1 0 9-9 9 9 0 0 0-7 3.3L3 8m0-5v5h5m4-1v5l3.5 2" />
          </svg>
          Recover
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
                  className="flex items-center gap-1.5 transition-[background-color,border-color,color,text-decoration-color] duration-150 ease-out"
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

      {/* Recovery panel — modal-overlay so it floats over the grid */}
      {recoverOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Recover saved layout"
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-start justify-center p-6 animate-in fade-in duration-150"
          onClick={(e) => { if (e.target === e.currentTarget) setRecoverOpen(false); }}
        >
          <div
            className="w-full max-w-2xl mt-12 animate-in fade-in zoom-in-95 duration-200 ease-out"
            style={{
              borderRadius: "var(--radius-card)",
              border: "1px solid var(--border-default)",
              backgroundColor: "var(--surface-1)",
              boxShadow: "var(--shadow-card-hover)",
              maxHeight: "calc(100vh - 120px)",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div className="flex items-center justify-between p-4 border-b" style={{borderColor:"var(--border-default)"}}>
              <div>
                <p className="jv-section-title">Recover saved layout</p>
                <p style={{fontSize:"11px",color:"var(--ink-muted)",marginTop:"2px"}}>
                  {recoverList.length === 0
                    ? "No saved snapshots yet — backups will appear here as you edit."
                    : `${recoverList.length} snapshot${recoverList.length === 1 ? "" : "s"} found · newest first`}
                </p>
              </div>
              <button
                onClick={() => setRecoverOpen(false)}
                className="px-2 h-7 rounded hover:bg-[var(--surface-raised)]"
                style={{fontSize:"11px",color:"var(--ink-tertiary)"}}
                aria-label="Close"
              >
                Close
              </button>
            </div>
            <div style={{overflowY:"auto",padding:"8px"}}>
              {recoverList.length === 0 ? (
                <div className="text-center py-8" style={{fontSize:"12px",color:"var(--ink-muted)"}}>
                  Your layout edits are now auto-backed-up. Drag a widget in edit mode and re-open this panel.
                </div>
              ) : (
                recoverList.map((entry) => {
                  const labelDate = entry.ts
                    ? new Date(entry.ts).toLocaleString(undefined, {
                        month: "short", day: "numeric",
                        hour: "numeric", minute: "2-digit",
                      })
                    : entry.key;
                  const kind = entry.key.startsWith("jarvis-layout-recovery-")
                    ? "Recovered"
                    : entry.key.startsWith("jarvis-layout-pre-recovery-")
                      ? "Before-recover"
                      : entry.key.startsWith("jarvis-layout-snapshot-")
                        ? "Snapshot"
                        : "Auto-backup";
                  return (
                    <div
                      key={entry.key}
                      className="flex items-start gap-3 p-3 mb-1 rounded"
                      style={{
                        borderRadius: "var(--radius-chip)",
                        backgroundColor: "var(--surface-2)",
                      }}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span style={{fontSize:"10px",fontWeight:600,padding:"1px 6px",borderRadius:"3px",backgroundColor:"var(--surface-raised)",color:"var(--ink-tertiary)"}}>
                            {kind}
                          </span>
                          <span style={{fontSize:"12px",fontWeight:500,color:"var(--ink-primary)"}}>
                            {labelDate}
                          </span>
                        </div>
                        <p style={{fontSize:"11px",color:"var(--ink-muted)",marginTop:"4px",fontFamily:"var(--font-mono)"}}>
                          {entry.summary}
                        </p>
                        <p style={{fontSize:"10px",color:"var(--ink-muted)",marginTop:"2px"}}>
                          {entry.key}
                        </p>
                      </div>
                      <div className="flex flex-col gap-1 shrink-0">
                        <button
                          onClick={() => applyRecovery(entry)}
                          className="px-3 h-7 rounded transition-colors hover:bg-[var(--surface-raised)]"
                          style={{fontSize:"11px",fontWeight:500,backgroundColor:"var(--accent-soft)",color:"var(--accent)",border:"1px solid var(--accent)"}}
                        >
                          Apply
                        </button>
                        {!entry.key.startsWith("jarvis-layout-recovery-") && (
                          <button
                            onClick={() => deleteRecoveryEntry(entry.key)}
                            className="px-2 h-6 rounded transition-colors hover:bg-[var(--surface-raised)]"
                            style={{fontSize:"10px",color:"var(--ink-muted)"}}
                            title="Delete this snapshot"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* Grid */}
      {/*
        WHY decoratedLayouts exists: react-grid-layout v2's grid-level
        `isDraggable={false}` is occasionally bypassed (RGL caches drag
        listeners across prop transitions in some scenarios), causing
        clicks on plain divs/spans inside widgets to start a drag even
        when the user thinks they're not in edit mode. The bullet-proof
        fix is RGL's per-item `static: true` flag — at the GridItem
        layer, RGL hard-codes `isDraggable=false, isResizable=false` for
        any item with `static: true`. Setting `static: !editMode` on
        every layout item gives one ironclad answer instead of relying
        on the grid-level prop being honored.

        The decoration is derived (not stored) so toggling edit mode
        doesn't mutate the user's saved layout positions.
      */}
      {width > 0 && (
        <Responsive
          key={editMode ? "editing" : "locked"}
          className="layout"
          layouts={decoratedLayouts}
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
            <div key={key} className="h-full w-full">{widgets[key]}</div>
          ))}
        </Responsive>
      )}
    </div>
  );
}
