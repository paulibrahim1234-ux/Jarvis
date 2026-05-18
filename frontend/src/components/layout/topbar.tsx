"use client";

import { memo, useCallback, useEffect, useState } from "react";
import { Pencil, Check, Rows3 } from "lucide-react";
import { BACKEND, fetchAuthStatus, type AuthStatus } from "@/lib/api";
import { type Theme, getInitialTheme, applyTheme, persistTheme } from "@/lib/theme";
import { useEditModeStore } from "@/lib/edit-mode-store";
import {
  type Density,
  getInitialDensity,
  applyDensity,
  setDensity,
  subscribeDensityChange,
} from "@/lib/density-store";

const DEEP_FOCUS_KEY = "jarvis-deep-focus-v1";
const DEEP_FOCUS_EVENT = "jarvis-deep-focus-change";

type ServiceStatus = "up" | "down" | "unknown";

// Clock — extracted + memoized so the 1Hz tick does not re-render the entire
// Topbar (which carries auth/health/density/theme state). Memo() means React
// skips Clock re-renders unless its props change (none), and the parent's
// per-second tick is contained to this small subtree.
const Clock = memo(function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const timeStr = now
    ? now.toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      })
    : "";

  // Extract seconds directly — toLocaleTimeString with only `second` is
  // inconsistent across browsers (Safari may return "HH:MM:SS" instead of "SS").
  const secondsStr = now ? String(now.getSeconds()).padStart(2, "0") : "";

  const weekdayStr = now
    ? now.toLocaleDateString("en-US", { weekday: "long" })
    : "";

  const dateStr = now
    ? now.toLocaleDateString("en-US", {
        month: "long",
        day: "numeric",
      })
    : "";

  return (
    <div className="relative flex items-center gap-4">
      <div className="hidden md:flex flex-col items-end leading-tight">
        <span
          style={{
            fontSize: "13px",
            color: "var(--ink-secondary)",
            fontWeight: 500,
          }}
        >
          {weekdayStr}
        </span>
        <span
          style={{
            fontSize: "11px",
            color: "var(--ink-tertiary)",
          }}
        >
          {dateStr}
        </span>
      </div>
      {/* F11: rounded-full matches the icon buttons' radius (28px pill) */}
      <div
        className="flex items-baseline gap-1 rounded-full px-2.5 py-1"
        style={{
          backgroundColor: "var(--surface-2)",
          border: "1px solid var(--border-subtle)",
        }}
      >
        <span
          className="font-mono tabular-nums"
          style={{
            fontSize: "14px",
            color: "var(--ink-primary)",
            fontWeight: 500,
          }}
        >
          {timeStr}
        </span>
        <span
          className="font-mono tabular-nums"
          style={{
            fontSize: "11px",
            color: "var(--ink-muted)",
          }}
        >
          :{secondsStr}
        </span>
      </div>
    </div>
  );
});

export function Topbar() {
  const [backend, setBackend] = useState<ServiceStatus>("unknown");
  const [theme, setTheme] = useState<Theme>("dark");
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [deepFocus, setDeepFocus] = useState(false);
  const [density, setDensityState] = useState<Density>("comfortable");
  const { editMode, setEditMode } = useEditModeStore();

  // Initialize deep-focus state from localStorage on mount, and listen for
  // changes from other components (the storage event covers other tabs;
  // a same-tab CustomEvent covers in-page propagation since `storage` only
  // fires across tabs).
  useEffect(() => {
    try {
      setDeepFocus(localStorage.getItem(DEEP_FOCUS_KEY) === "1");
    } catch {
      /* ignore */
    }
    const onChange = (e: Event) => {
      const ce = e as CustomEvent<{ enabled: boolean }>;
      if (ce.detail) setDeepFocus(ce.detail.enabled);
    };
    window.addEventListener(DEEP_FOCUS_EVENT, onChange);
    return () => window.removeEventListener(DEEP_FOCUS_EVENT, onChange);
  }, []);

  // Initialize density from localStorage on mount, then subscribe to changes
  // dispatched by setDensity() so any other component can stay in sync.
  // applyDensity is called here so the body class is in place even if the
  // user never clicks the button (value comes from persisted localStorage).
  useEffect(() => {
    const initial = getInitialDensity();
    setDensityState(initial);
    applyDensity(initial);
    return subscribeDensityChange((d) => setDensityState(d));
  }, []);

  const toggleDensity = useCallback(() => {
    // Side effects (DOM class, persist, broadcast event) MUST live outside the
    // setState updater. React invokes updater fns during render in strict mode,
    // so calling setDensity() here would dispatch a custom event mid-render
    // and trigger setState in subscribed components (e.g. MorningBriefing) →
    // "Cannot update a component while rendering a different component" warning.
    const next: Density = density === "compact" ? "comfortable" : "compact";
    setDensityState(next);
    setDensity(next); // applies body class + persists + dispatches
  }, [density]);

  const toggleDeepFocus = useCallback(() => {
    setDeepFocus((prev) => {
      const next = !prev;
      try {
        if (next) localStorage.setItem(DEEP_FOCUS_KEY, "1");
        else localStorage.removeItem(DEEP_FOCUS_KEY);
      } catch {
        /* ignore */
      }
      window.dispatchEvent(
        new CustomEvent(DEEP_FOCUS_EVENT, { detail: { enabled: next } }),
      );
      return next;
    });
  }, []);

  // Credential health — refreshes every 2 min on the client. The backend
  // caches the live Anthropic probe for 5 min, so this hits real Anthropic
  // at most every 5 min but the UI reflects user-driven changes (e.g.
  // pasting a new token at /setup) within the next polling tick.
  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      try {
        const s = await fetchAuthStatus();
        if (!cancelled) setAuthStatus(s);
      } catch {
        /* ignore */
      }
    };
    probe();
    const id = setInterval(probe, 120_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Initialize theme from localStorage on mount
  useEffect(() => {
    const initial = getInitialTheme();
    setTheme(initial);
    applyTheme(initial);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      applyTheme(next);
      persistTheme(next);
      return next;
    });
  }, []);

  // Backend health probe — light, once every 30s
  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      try {
        const r = await fetch(`${BACKEND}/health`, {
          signal: AbortSignal.timeout(5_000),
        });
        if (cancelled) return;
        setBackend(r.ok ? "up" : "down");
      } catch {
        if (!cancelled) setBackend("down");
      }
    };
    probe();
    const id = setInterval(probe, 30_000);
    const onVis = () => {
      if (document.visibilityState === "visible") probe();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  const statusLabel = backend === "up" ? "Live" : backend === "down" ? "Offline" : "Connecting";
  const statusState: "live" | "warn" | "error" | "loading" =
    backend === "up" ? "live" : backend === "down" ? "error" : "loading";

  return (
    <header
      className="sticky top-0 z-50 flex h-14 items-center justify-between px-6 backdrop-blur-xl"
      style={{
        backgroundColor: "color-mix(in oklch, var(--surface-0) 72%, transparent)",
      }}
    >
      {/* Bottom border: gradient fading from accent center to transparent edges */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, var(--border-accent) 35%, var(--border-accent) 65%, transparent)",
        }}
      />

      {/* Subtle gradient wash across the whole bar */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(180deg, color-mix(in oklch, var(--brand) 4%, transparent) 0%, transparent 100%)",
        }}
      />

      {/* Brand + status */}
      <div className="relative flex items-center gap-3">
        <span
          className="font-semibold"
          style={{
            fontSize: "20px",
            letterSpacing: "0.18em",
            lineHeight: 1,
          }}
        >
          <span style={{ color: "var(--brand)" }}>J</span>
          <span style={{ color: "var(--ink-primary)" }}>ARVIS</span>
        </span>
        <span
          className="hidden sm:inline-flex items-center gap-1.5 rounded-full border px-2 py-[2px]"
          style={{
            borderColor: "var(--border-subtle)",
            backgroundColor: "var(--surface-2)",
            // WHY ink-secondary + 11px/600: `ink-tertiary` at 10px is borderline
            // on WCAG 4.5:1 for small text. ink-secondary is darker (passes
            // across both themes) and 11px/600 clears the AA threshold for
            // text this small without visually dominating the chip.
            fontSize: "11px",
            fontWeight: 600,
            color: "var(--ink-secondary)",
            letterSpacing: "0.04em",
          }}
          title={`Backend: ${statusLabel}`}
        >
          <span className="jv-live-dot" data-state={statusState} />
          <span style={{ textTransform: "uppercase" }}>
            {statusLabel}
          </span>
        </span>

        {/* Claude credential health — only show when we have a verdict.
            Hide while loading; show a green dot when valid; show an amber
            "Re-auth Claude" link when invalid (clicks → /setup). */}
        {authStatus !== null && !authStatus.claude && (
          <a
            href={`${BACKEND}/setup`}
            target="_blank"
            rel="noreferrer"
            className="hidden sm:inline-flex items-center gap-1.5 rounded-full border px-2 py-[2px] hover:opacity-90 transition-opacity"
            style={{
              // WHY CSS vars instead of hardcoded RGB: `rgb(252, 211, 77)` on
              // `rgba(245,158,11,0.12)` fails WCAG 4.5:1 contrast on light theme
              // because both values are light-theme-only constants. The design
              // tokens `--status-warn` / `--status-warn-soft` are defined per
              // theme in globals.css and are calibrated to meet contrast in both
              // dark and light modes without needing a media query here.
              borderColor: "color-mix(in oklch, var(--status-warn) 40%, transparent)",
              backgroundColor: "var(--status-warn-soft)",
              fontSize: "11px",
              fontWeight: 600,
              color: "var(--status-warn)",
              letterSpacing: "0.04em",
              textDecoration: "none",
            }}
            title={`Claude auth: ${authStatus.claude_error ?? "invalid"}. Click to update credentials.`}
          >
            <span style={{
              width: 6, height: 6, borderRadius: 999,
              backgroundColor: "var(--status-warn)",
              display: "inline-block",
            }} />
            <span style={{ textTransform: "uppercase", fontWeight: 500 }}>
              Re-auth Claude
            </span>
          </a>
        )}

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          className="flex items-center justify-center rounded-full border transition-colors"
          style={{
            width: 28,
            height: 28,
            borderColor: "var(--border-subtle)",
            backgroundColor: "var(--surface-2)",
            color: "var(--ink-tertiary)",
          }}
        >
          {theme === "dark" ? (
            /* Sun icon */
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="4"/>
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
            </svg>
          ) : (
            /* Moon icon */
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
          )}
        </button>

        {/* Deep Focus toggle — collapses the dashboard down to chat,
            briefing, and Spotify only. Persists in localStorage; both
            Topbar and DashboardGrid read the same key + listen for the
            CustomEvent below. */}
        <button
          data-deep-focus-trigger
          onClick={toggleDeepFocus}
          aria-pressed={deepFocus}
          aria-label={deepFocus ? "Exit deep focus" : "Enter deep focus"}
          title={deepFocus ? "Exit Deep Focus" : "Enter Deep Focus"}
          className="flex items-center justify-center rounded-full border transition-colors"
          style={{
            width: 28,
            height: 28,
            borderColor: deepFocus ? "var(--brand)" : "var(--border-subtle)",
            backgroundColor: deepFocus ? "color-mix(in oklch, var(--brand) 20%, transparent)" : "var(--surface-2)",
            color: deepFocus ? "var(--brand)" : "var(--ink-tertiary)",
          }}
        >
          {/* Concentric-circle "target" glyph for focus */}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="5" />
            <circle cx="12" cy="12" r="1" fill="currentColor" />
          </svg>
        </button>

        {/* Density toggle — switches between comfortable (default) and compact
            spacing. `setDensity` in density-store adds/removes the
            `density-compact` class on <body> and persists to localStorage
            under `jarvis.density` so the preference survives page reloads. */}
        <button
          onClick={toggleDensity}
          aria-pressed={density === "compact"}
          aria-label={density === "compact" ? "Switch to comfortable density" : "Switch to compact density"}
          title={density === "compact" ? "Comfortable density" : "Compact density"}
          className="flex items-center justify-center rounded-full border transition-colors"
          style={{
            width: 28,
            height: 28,
            borderColor: density === "compact" ? "var(--brand)" : "var(--border-subtle)",
            backgroundColor: density === "compact"
              ? "color-mix(in oklch, var(--brand) 20%, transparent)"
              : "var(--surface-2)",
            color: density === "compact" ? "var(--brand)" : "var(--ink-tertiary)",
          }}
        >
          <Rows3 width={14} height={14} aria-hidden />
        </button>

        {/* Edit layout toggle — exposes the drag grip on each widget and
            unlocks resizing. The icon swaps between a pencil (off) and a
            check (on) so the current mode is unambiguous at a glance.
            State lives in the edit-mode-store module and is persisted to
            localStorage so the preference survives page reloads. */}
        <button
          onClick={() => setEditMode(!editMode)}
          aria-pressed={editMode}
          aria-label={editMode ? "Done editing layout" : "Edit layout"}
          title={editMode ? "Done editing layout" : "Edit layout"}
          className="flex items-center gap-1.5 rounded-full border px-2.5 transition-colors"
          style={{
            height: 28,
            borderColor: editMode ? "var(--brand)" : "var(--border-subtle)",
            backgroundColor: editMode
              ? "color-mix(in oklch, var(--brand) 20%, transparent)"
              : "var(--surface-2)",
            color: editMode ? "var(--brand)" : "var(--ink-tertiary)",
            fontSize: "11px",
            fontWeight: 500,
          }}
        >
          {editMode ? (
            <Check width={12} height={12} aria-hidden />
          ) : (
            <Pencil width={12} height={12} aria-hidden />
          )}
          {/* F12: whitespace-nowrap stops "Edit layout" / "Done editing" from
               wrapping on narrow viewports. hidden sm:inline collapses the
               label below the sm breakpoint so only the icon shows, keeping
               the topbar tidy on small screens without losing the button. */}
          <span className="hidden sm:inline whitespace-nowrap">
            {editMode ? "Done editing" : "Edit layout"}
          </span>
        </button>
      </div>

      {/* Date + time — extracted to memoized <Clock /> so the per-second
          tick re-renders only this subtree, not the entire Topbar. */}
      <Clock />
    </header>
  );
}
