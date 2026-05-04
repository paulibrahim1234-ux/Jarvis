/**
 * Density store — plain module-level state (no Zustand dep) that mirrors the
 * pattern used by theme.ts. Using a subscriber set instead of a React context
 * keeps this framework-agnostic and lets both the topbar button and any widget
 * react to changes without prop-drilling.
 */

export type Density = "compact" | "comfortable";

const DENSITY_KEY = "jarvis.density";
const DENSITY_EVENT = "jarvis-density-change";

// ── Persistence helpers ───────────────────────────────────────────────────────

export function getInitialDensity(): Density {
  if (typeof window === "undefined") return "comfortable";
  const saved = localStorage.getItem(DENSITY_KEY);
  return saved === "compact" ? "compact" : "comfortable";
}

/**
 * Apply density to <body> by toggling the `density-compact` class.
 * CSS variables in globals.css key off this class:
 *   --widget-density-pad  → 1rem  (comfortable) / 0.5rem (compact)
 *   --widget-density-font → 1rem  (comfortable) / 0.875rem (compact)
 */
export function applyDensity(density: Density): void {
  if (typeof document === "undefined") return;
  if (density === "compact") {
    document.body.classList.add("density-compact");
  } else {
    document.body.classList.remove("density-compact");
  }
}

export function persistDensity(density: Density): void {
  try {
    localStorage.setItem(DENSITY_KEY, density);
  } catch {
    /* ignore quota/security errors */
  }
}

// ── Simple pub/sub so the topbar and any listener can stay in sync ────────────

export function dispatchDensityChange(density: Density): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<{ density: Density }>(DENSITY_EVENT, {
      detail: { density },
    }),
  );
}

export function subscribeDensityChange(
  cb: (density: Density) => void,
): () => void {
  // WHY SSR guard: dispatchDensityChange already guards with typeof window,
  // but subscribeDensityChange was missing the same check. During Next.js
  // server-side rendering window is undefined; calling addEventListener on it
  // throws a ReferenceError that crashes the SSR pass. Return a no-op cleanup
  // so callers can safely call this in a useEffect without special-casing SSR.
  if (typeof window === "undefined") return () => {};
  const handler = (e: Event) => {
    const ce = e as CustomEvent<{ density: Density }>;
    if (ce.detail) cb(ce.detail.density);
  };
  window.addEventListener(DENSITY_EVENT, handler);
  return () => window.removeEventListener(DENSITY_EVENT, handler);
}

// ── Convenience toggle ────────────────────────────────────────────────────────

export function setDensity(density: Density): void {
  applyDensity(density);
  persistDensity(density);
  dispatchDensityChange(density);
}
