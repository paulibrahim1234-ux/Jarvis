"use client";

import { useEffect, useState } from "react";
import { BACKEND } from "@/lib/api";
import { type Theme, getInitialTheme, applyTheme, persistTheme } from "@/lib/theme";

type ServiceStatus = "up" | "down" | "unknown";

export function Topbar() {
  const [now, setNow] = useState<Date | null>(null);
  const [backend, setBackend] = useState<ServiceStatus>("unknown");
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // Initialize theme from localStorage on mount
  useEffect(() => {
    const initial = getInitialTheme();
    setTheme(initial);
    applyTheme(initial);
  }, []);

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
    persistTheme(next);
  }

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
            fontSize: "10px",
            color: "var(--ink-tertiary)",
            letterSpacing: "0.04em",
          }}
          title={`Backend: ${statusLabel}`}
        >
          <span className="jv-live-dot" data-state={statusState} />
          <span style={{ textTransform: "uppercase", fontWeight: 500 }}>
            {statusLabel}
          </span>
        </span>

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
      </div>

      {/* Date + time */}
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
        <div
          className="flex items-baseline gap-1 rounded-md px-2.5 py-1"
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
    </header>
  );
}
