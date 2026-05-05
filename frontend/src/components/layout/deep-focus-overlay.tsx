"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Group, Panel, Separator, type Layout, type GroupImperativeHandle } from "react-resizable-panels";
import { PomodoroWidget } from "@/components/widgets/pomodoro-widget";
import { MorningBriefing } from "@/components/widgets/morning-briefing";
import { SpotifyWidget } from "@/components/widgets/spotify-widget";

const DEEP_FOCUS_KEY = "jarvis-deep-focus-v1";
const DEEP_FOCUS_EVENT = "jarvis-deep-focus-change";
const PANEL_LAYOUT_KEY = "jarvis-deep-focus-panels";

const PANEL_IDS = { pomodoro: "pomodoro", briefing: "briefing", spotify: "spotify" } as const;

const DEFAULT_LAYOUT: Layout = {
  [PANEL_IDS.pomodoro]: 33,
  [PANEL_IDS.briefing]: 34,
  [PANEL_IDS.spotify]: 33,
};

// Panel IDs in declaration order — used by keyboard separator reset
const PANEL_ORDER = [PANEL_IDS.pomodoro, PANEL_IDS.briefing, PANEL_IDS.spotify] as const;

/** Returns true while the viewport is >= 768 px wide (md breakpoint). */
function useIsWide() {
  const [wide, setWide] = useState(true);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    setWide(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setWide(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return wide;
}

function readLayout(): Layout | undefined {
  try {
    const raw = localStorage.getItem(PANEL_LAYOUT_KEY);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as Layout;
    // Validate: must contain our three panel ids
    if (
      typeof parsed?.[PANEL_IDS.pomodoro] === "number" &&
      typeof parsed?.[PANEL_IDS.briefing] === "number" &&
      typeof parsed?.[PANEL_IDS.spotify] === "number"
    ) {
      return parsed;
    }
  } catch {}
  return undefined;
}

function saveLayout(layout: Layout) {
  try { localStorage.setItem(PANEL_LAYOUT_KEY, JSON.stringify(layout)); } catch {}
}

// All focusable elements we allow Tab to visit inside the overlay
const FOCUSABLE_SELECTORS = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function DeepFocusOverlay() {
  const [open, setOpen] = useState(false);
  const horizontal = useIsWide();
  // undefined = not yet hydrated (avoid SSR/client mismatch); Layout = resolved
  const [savedLayout, setSavedLayout] = useState<Layout | undefined>(undefined);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Track the element that triggered the overlay open so we can restore
  // focus to it on close (A11y#2 — modal focus management)
  const triggerRef = useRef<HTMLElement | null>(null);
  const exitButtonRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  // Imperative handle lets Separator keyboard ops call resize helpers (A11y#3)
  const groupRef = useRef<GroupImperativeHandle>(null);

  // Hydrate saved panel sizes after mount (client-only, avoids SSR localStorage crash)
  useEffect(() => {
    setSavedLayout(readLayout() ?? DEFAULT_LAYOUT);
  }, []);

  // Hydrate from localStorage on mount + subscribe to event
  useEffect(() => {
    setOpen(localStorage.getItem(DEEP_FOCUS_KEY) === "1");
    const onChange = (e: Event) => {
      const ce = e as CustomEvent<{ enabled: boolean }>;
      if (ce.detail) setOpen(ce.detail.enabled);
    };
    window.addEventListener(DEEP_FOCUS_EVENT, onChange);
    return () => window.removeEventListener(DEEP_FOCUS_EVENT, onChange);
  }, []);

  // TS#2 — clear any pending debounce timer on unmount to prevent state updates
  // on an unmounted component (mirrors the pattern in dashboard-grid.tsx)
  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  // TS#1 — closeOverlay as useCallback so the ESC useEffect dep array is
  // satisfied without stale-closure issues (was declared as a plain function
  // BELOW the effect that referenced it)
  const closeOverlay = useCallback(() => {
    try { localStorage.setItem(DEEP_FOCUS_KEY, "0"); } catch {}
    window.dispatchEvent(new CustomEvent(DEEP_FOCUS_EVENT, { detail: { enabled: false } }));
    // A11y#2 — restore focus to the element that opened the overlay
    triggerRef.current?.focus();
    triggerRef.current = null;
  }, []);

  // ESC closes — dep array now includes the stable closeOverlay callback (TS#1)
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeOverlay();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closeOverlay]);

  // A11y#2 — store trigger element + set initial focus to Exit button after open
  useEffect(() => {
    if (!open) return;
    // Capture whatever had focus before the overlay rendered
    if (document.activeElement instanceof HTMLElement) {
      triggerRef.current = document.activeElement;
    }
    // Push focus to the Exit button on the next frame (after render completes)
    const raf = requestAnimationFrame(() => {
      exitButtonRef.current?.focus();
    });
    return () => cancelAnimationFrame(raf);
  }, [open]);

  // A11y#2 — tab-trap: loop Tab/Shift+Tab within the overlay's focusable descendants
  useEffect(() => {
    if (!open) return;
    const trapTab = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const overlay = overlayRef.current;
      if (!overlay) return;
      const focusable = Array.from(
        overlay.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS)
      ).filter((el) => el.offsetParent !== null); // exclude display:none
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", trapTab);
    return () => window.removeEventListener("keydown", trapTab);
  }, [open]);

  // TS#2 — onLayoutChanged as useCallback with stable saveTimer ref so the
  // function reference is stable across renders (no unnecessary Group re-renders)
  const onLayoutChanged = useCallback((layout: Layout) => {
    setSavedLayout(layout);
    // Debounce writes so we don't thrash localStorage during drag
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => saveLayout(layout), 150);
  }, []);

  // A11y#3 — keyboard resize handler for a separator. Drives resize through
  // the imperative group ref so the library's internal state stays in sync.
  // panelIndex is the 0-based index into PANEL_ORDER for the panel LEFT of
  // this separator.
  const makeSeparatorKeyDown = useCallback(
    (panelIndex: 0 | 1) => (e: React.KeyboardEvent<HTMLDivElement>) => {
      const group = groupRef.current;
      if (!group) return;
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault();

      // getLayout() returns Layout = { [panelId: string]: number }
      const current: Layout = group.getLayout();

      if (e.key === "Home") {
        // Reset all panels to the default distribution
        group.setLayout({ ...DEFAULT_LAYOUT });
        return;
      }
      if (e.key === "End") {
        // Maximize the panel to the LEFT of this separator (60% left, 20% each other)
        const maxed: Layout = {};
        PANEL_ORDER.forEach((id, i) => {
          maxed[id] = i === panelIndex ? 60 : 20;
        });
        group.setLayout(maxed);
        return;
      }

      const delta = e.key === "ArrowRight" ? 1 : -1;
      // Transfer 1% between the panels on either side of this separator
      const leftId = PANEL_ORDER[panelIndex];
      const rightId = PANEL_ORDER[panelIndex + 1];
      const leftSize = current[leftId] ?? 33;
      const rightSize = current[rightId] ?? 33;
      if (leftSize + delta < 20 || rightSize - delta < 20) return;
      group.setLayout({
        ...current,
        [leftId]: leftSize + delta,
        [rightId]: rightSize - delta,
      });
    },
    []
  );

  // Don't render until panel sizes are hydrated (avoids SSR/client mismatch)
  if (!open || savedLayout === undefined) return null;

  return (
    // A11y#2 — dialog role + aria-modal so screen readers enter a modal context
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="deep-focus-title"
      className="fixed inset-0 z-[100] animate-in fade-in duration-200"
      style={{
        backgroundColor: "color-mix(in oklch, var(--surface-0) 92%, transparent)",
        backdropFilter: "blur(10px)",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) closeOverlay(); }}
    >
      <div className="h-full w-full max-w-7xl mx-auto px-6 py-8 flex flex-col gap-5">
        {/* Header bar */}
        <div className="flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-3">
            <span aria-hidden style={{ width: 8, height: 8, borderRadius: 9999, backgroundColor: "var(--brand)" }} />
            {/* A11y#2 — id ties to aria-labelledby on the dialog root */}
            <h2 id="deep-focus-title" className="text-base font-medium" style={{ color: "var(--ink-primary)" }}>Deep Focus</h2>
            <span className="text-xs" style={{ color: "var(--ink-tertiary)" }}>
              ESC to exit · drag dividers to resize
            </span>
          </div>
          {/* A11y#2 — initial focus lands here on open; ref enables that focus effect */}
          <button
            ref={exitButtonRef}
            type="button"
            onClick={closeOverlay}
            className="px-3 py-1.5 rounded-full text-xs hover:bg-[var(--surface-raised)]"
            style={{ border: "1px solid var(--border-subtle)", color: "var(--ink-secondary)" }}
          >
            Exit
          </button>
        </div>

        {/* 3-up resizable panels: Pomodoro / Briefing / Spotify
            TS#11 — defaultLayout on Group is the single source of truth (Layout object);
            per-Panel defaultSize props removed to eliminate the redundancy.
            groupRef wires the imperative handle for keyboard separator ops (A11y#3). */}
        <Group
          groupRef={groupRef}
          orientation={horizontal ? "horizontal" : "vertical"}
          defaultLayout={savedLayout}
          onLayoutChanged={onLayoutChanged}
          className="flex-1 min-h-0"
          style={{ display: "flex", flexDirection: horizontal ? "row" : "column" }}
        >
          <Panel id={PANEL_IDS.pomodoro} minSize={20} className="min-h-0 overflow-hidden">
            <PomodoroWidget />
          </Panel>

          {/* A11y#3 — <Separator> intentionally omits tabIndex/role in its prop
              types (BaseSeparatorAttributes = Omit<HTMLAttributes, "role"|"tabIndex">).
              We wrap it in a focusable <div> that carries the ARIA attributes and
              keyboard handler, keeping the resize behaviour on the inner Separator. */}
          <div
            tabIndex={0}
            role="separator"
            aria-orientation={horizontal ? "vertical" : "horizontal"}
            aria-controls={PANEL_IDS.briefing}
            aria-valuenow={savedLayout[PANEL_IDS.pomodoro]}
            onKeyDown={makeSeparatorKeyDown(0)}
            className="contents"
          >
            <Separator className="group relative flex items-center justify-center cursor-col-resize mx-1 w-2 rounded transition-colors duration-150 hover:bg-[var(--brand-soft)] bg-transparent shrink-0">
              <span className="block w-0.5 h-6 rounded-full bg-[var(--border-subtle)] group-hover:bg-[var(--brand)] transition-colors duration-150" />
            </Separator>
          </div>

          <Panel id={PANEL_IDS.briefing} minSize={20} className="min-h-0 overflow-hidden">
            <MorningBriefing />
          </Panel>

          {/* A11y#3 — second separator controls the briefing ↔ spotify boundary */}
          <div
            tabIndex={0}
            role="separator"
            aria-orientation={horizontal ? "vertical" : "horizontal"}
            aria-controls={PANEL_IDS.spotify}
            aria-valuenow={savedLayout[PANEL_IDS.briefing]}
            onKeyDown={makeSeparatorKeyDown(1)}
            className="contents"
          >
            <Separator className="group relative flex items-center justify-center cursor-col-resize mx-1 w-2 rounded transition-colors duration-150 hover:bg-[var(--brand-soft)] bg-transparent shrink-0">
              <span className="block w-0.5 h-6 rounded-full bg-[var(--border-subtle)] group-hover:bg-[var(--brand)] transition-colors duration-150" />
            </Separator>
          </div>

          <Panel id={PANEL_IDS.spotify} minSize={20} className="min-h-0 overflow-hidden">
            <SpotifyWidget />
          </Panel>
        </Group>
      </div>
    </div>
  );
}
