"use client";

import { useState, useEffect } from "react";
import { PomodoroWidget } from "@/components/widgets/pomodoro-widget";
import { MorningBriefing } from "@/components/widgets/morning-briefing";
import { SpotifyWidget } from "@/components/widgets/spotify-widget";

const DEEP_FOCUS_KEY = "jarvis-deep-focus-v1";
const DEEP_FOCUS_EVENT = "jarvis-deep-focus-change";

function closeOverlay() {
  try {
    localStorage.setItem(DEEP_FOCUS_KEY, "0");
  } catch { /* ignore */ }
  window.dispatchEvent(
    new CustomEvent(DEEP_FOCUS_EVENT, { detail: { enabled: false } })
  );
}

export function DeepFocusOverlay() {
  const [open, setOpen] = useState(false);

  // Hydrate from localStorage and subscribe to toggle events.
  useEffect(() => {
    try {
      setOpen(localStorage.getItem(DEEP_FOCUS_KEY) === "1");
    } catch { /* ignore */ }

    const handler = (e: Event) => {
      const ce = e as CustomEvent<{ enabled: boolean }>;
      if (ce.detail != null) setOpen(ce.detail.enabled);
    };
    window.addEventListener(DEEP_FOCUS_EVENT, handler as EventListener);
    return () => window.removeEventListener(DEEP_FOCUS_EVENT, handler as EventListener);
  }, []);

  // ESC key closes the overlay.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeOverlay();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100]"
      style={{
        backgroundColor: "color-mix(in srgb, var(--surface-0, #0a0a0a) 92%, transparent)",
        backdropFilter: "blur(8px)",
        animation: "deep-focus-fade-in 200ms ease-out",
      }}
      onClick={(e) => {
        // Close on backdrop click only when the backdrop itself is the target.
        if (e.target === e.currentTarget) closeOverlay();
      }}
    >
      <style>{`
        @keyframes deep-focus-fade-in {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
      `}</style>

      <div className="h-full w-full flex flex-col items-center justify-center px-6 py-10 gap-6 max-w-7xl mx-auto">
        {/* Header */}
        <div className="w-full flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              style={{
                display: "inline-block",
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: "var(--brand, #10b981)",
              }}
            />
            <h2
              className="text-base font-medium"
              style={{ color: "var(--ink-primary, #f0f0f0)" }}
            >
              Deep Focus
            </h2>
            <span
              className="text-xs"
              style={{ color: "var(--ink-tertiary, #6b7280)" }}
            >
              Press ESC to exit
            </span>
          </div>
          <button
            type="button"
            onClick={closeOverlay}
            className="px-3 py-1.5 rounded-full text-xs transition-colors hover:bg-[var(--surface-raised)]"
            style={{
              border: "1px solid var(--border-subtle, rgba(255,255,255,0.12))",
              color: "var(--ink-secondary, #a1a1aa)",
            }}
          >
            Exit
          </button>
        </div>

        {/* 3-up grid: Pomodoro / Briefing / Spotify */}
        <div className="w-full grid grid-cols-1 md:grid-cols-3 gap-4 flex-1 max-h-[80vh]">
          <div className="min-h-[400px]">
            <PomodoroWidget />
          </div>
          <div className="min-h-[400px]">
            <MorningBriefing />
          </div>
          <div className="min-h-[400px]">
            <SpotifyWidget />
          </div>
        </div>
      </div>
    </div>
  );
}
