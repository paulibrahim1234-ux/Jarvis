"use client";

/**
 * Minimal editMode store implemented as a React Context + hook pair.
 *
 * Why not Zustand? Zustand is not in package.json and adding a new runtime
 * dependency solely for one boolean is disproportionate. This module exposes
 * the same ergonomic surface (`useEditModeStore`) so swapping to Zustand later
 * is a one-file change.
 *
 * WHY a module-level singleton instead of a root Provider?
 * The dashboard is a single-page client app with no SSR islands boundary
 * between Topbar, DashboardGrid, and WidgetWrapper — a module-level
 * subscription map lets each consumer subscribe/unsubscribe independently
 * without wrapping the whole tree in a new Provider component.
 */

import { useState, useEffect } from "react";

const STORAGE_KEY = "jarvis.editMode";

// Internal subscriber registry — call each listener when state changes.
type Listener = (editMode: boolean) => void;
const listeners = new Set<Listener>();

// Module-level state: starts false (safe server-side default).
let _editMode = false;

// Toggle a body class so CSS can defensively kill drag affordances when off.
// Why this exists alongside the React isDraggable wiring: react-grid-layout v2
// sometimes retains drag listeners across prop transitions, so a CSS belt
// (cursor:default + display:none on resize handles) backs up the JS suspenders.
function applyEditModeClass(active: boolean) {
  if (typeof document === "undefined") return;
  if (active) document.body.classList.add("edit-mode-active");
  else document.body.classList.remove("edit-mode-active");
}

function setEditMode(next: boolean) {
  _editMode = next;
  applyEditModeClass(next);
  // Persist so the preference survives navigation reloads.
  try {
    localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  } catch {
    // iOS Safari private mode throws QuotaExceededError — silently ignore.
  }
  // Notify all mounted consumers synchronously.
  listeners.forEach((fn) => fn(next));
}

/**
 * React hook that subscribes to editMode.
 *
 * Hydrates from localStorage on first client mount (inside useEffect, not
 * during render) to prevent React hydration-mismatch warnings that would
 * arise from reading localStorage during SSR.
 */
export function useEditModeStore() {
  const [editMode, setLocal] = useState<boolean>(false);

  useEffect(() => {
    // Post-mount hydration: read persisted value and align local state.
    // This runs only once and never during SSR, so no hydration mismatch.
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        const hydrated = stored === "1";
        _editMode = hydrated;
        applyEditModeClass(hydrated);
        setLocal(hydrated);
        // Notify other already-mounted consumers so they're consistent.
        listeners.forEach((fn) => fn(hydrated));
      } else {
        // Default off — ensure the body class is also off so CSS rules apply.
        applyEditModeClass(false);
      }
    } catch {
      /* ignore */
    }

    // Subscribe to future changes.
    const listener: Listener = (next) => setLocal(next);
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, []);

  return { editMode, setEditMode };
}
