"use client";

import { useEffect, useState } from "react";
import { BACKEND } from "@/lib/api";

type ServiceStatus = "up" | "down" | "unknown";

export function Topbar() {
  const [now, setNow] = useState<Date | null>(null);
  const [backend, setBackend] = useState<ServiceStatus>("unknown");

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
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
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const timeStr = now
    ? now.toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      })
    : "";

  const secondsStr = now
    ? now.toLocaleTimeString("en-US", {
        second: "2-digit",
        hour12: false,
      })
    : "";

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

      {/* Brand */}
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
