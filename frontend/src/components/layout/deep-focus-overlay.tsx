"use client";
import { useEffect, useRef, useState } from "react";
import { Group, Panel, Separator, type Layout } from "react-resizable-panels";
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

export function DeepFocusOverlay() {
  const [open, setOpen] = useState(false);
  const horizontal = useIsWide();
  // undefined = not yet hydrated (avoid SSR/client mismatch); Layout = resolved
  const [savedLayout, setSavedLayout] = useState<Layout | undefined>(undefined);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // ESC closes
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeOverlay();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function closeOverlay() {
    try { localStorage.setItem(DEEP_FOCUS_KEY, "0"); } catch {}
    window.dispatchEvent(new CustomEvent(DEEP_FOCUS_EVENT, { detail: { enabled: false } }));
  }

  function onLayoutChanged(layout: Layout) {
    // Debounce writes so we don't thrash localStorage during drag
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => saveLayout(layout), 150);
  }

  // Don't render until panel sizes are hydrated (avoids SSR/client mismatch)
  if (!open || savedLayout === undefined) return null;

  return (
    <div
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
            <h2 className="text-base font-medium" style={{ color: "var(--ink-primary)" }}>Deep Focus</h2>
            <span className="text-xs" style={{ color: "var(--ink-tertiary)" }}>
              ESC to exit · drag dividers to resize
            </span>
          </div>
          <button
            type="button"
            onClick={closeOverlay}
            className="px-3 py-1.5 rounded-full text-xs hover:bg-[var(--surface-raised)]"
            style={{ border: "1px solid var(--border-subtle)", color: "var(--ink-secondary)" }}
          >
            Exit
          </button>
        </div>

        {/* 3-up resizable panels: Pomodoro / Briefing / Spotify */}
        <Group
          orientation={horizontal ? "horizontal" : "vertical"}
          defaultLayout={savedLayout}
          onLayoutChanged={onLayoutChanged}
          className="flex-1 min-h-0"
          style={{ display: "flex", flexDirection: horizontal ? "row" : "column" }}
        >
          <Panel id={PANEL_IDS.pomodoro} defaultSize={savedLayout[PANEL_IDS.pomodoro]} minSize={20} className="min-h-0 overflow-hidden">
            <PomodoroWidget />
          </Panel>

          <Separator className="group relative flex items-center justify-center cursor-col-resize mx-1 w-2 rounded transition-colors duration-150 hover:bg-[var(--brand-soft)] bg-transparent shrink-0">
            <span className="block w-0.5 h-6 rounded-full bg-[var(--border-subtle)] group-hover:bg-[var(--brand)] transition-colors duration-150" />
          </Separator>

          <Panel id={PANEL_IDS.briefing} defaultSize={savedLayout[PANEL_IDS.briefing]} minSize={20} className="min-h-0 overflow-hidden">
            <MorningBriefing />
          </Panel>

          <Separator className="group relative flex items-center justify-center cursor-col-resize mx-1 w-2 rounded transition-colors duration-150 hover:bg-[var(--brand-soft)] bg-transparent shrink-0">
            <span className="block w-0.5 h-6 rounded-full bg-[var(--border-subtle)] group-hover:bg-[var(--brand)] transition-colors duration-150" />
          </Separator>

          <Panel id={PANEL_IDS.spotify} defaultSize={savedLayout[PANEL_IDS.spotify]} minSize={20} className="min-h-0 overflow-hidden">
            <SpotifyWidget />
          </Panel>
        </Group>
      </div>
    </div>
  );
}
