/**
 * Runtime config for the Jarvis dashboard widgets.
 *
 * Edit this file directly to customize your dashboard (contact names,
 * message allowlist, rotation info). Kept inside `src/` so the bundler
 * always resolves it — no dynamic-import gymnastics.
 */

export type QBank = "uworld" | "truelearn";

export interface JarvisConfig {
  /** First name shown in the greeting line (e.g. "Good afternoon, <name>."). */
  firstName?: string;
  /** Current rotation or block name. */
  rotation: string;
  /** ISO date of the next shelf / board exam (YYYY-MM-DD). */
  shelfExamDate: string;
  /** Question bank in use. */
  qbank: QBank;
  /**
   * Allowlist of contacts (phone numbers or emails) the Messages widget
   * is permitted to show. Empty array = show everything (no filter).
   */
  messagesContactsAllowlist: string[];
  /**
   * Handle -> display-name map. Phone keys in any format (normalized to
   * last 10 digits); email keys case-insensitive. Unmapped handles fall
   * back to the raw identifier.
   *
   *   { "+1 (555) 123-4567": "Sarah", "mom@example.com": "Mom" }
   */
  contacts?: Record<string, string>;
  /** Enable Spotify widget. */
  spotifyEnabled: boolean;
}

// ─── EDIT ME ─────────────────────────────────────────────────────────────────
export const jarvisConfig: JarvisConfig = {
  firstName: "",
  rotation: "",
  shelfExamDate: "",
  qbank: "uworld",
  messagesContactsAllowlist: [],
  contacts: {
    // "5551234567": "Mom",
    // "friend@example.com": "Alex",
  },
  spotifyEnabled: true,
};
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Normalize a handle (phone or email) for comparison.
 *   Email: trim + lowercase.
 *   Phone: strip non-digits, keep last 10. Tolerant of "+1", spaces,
 *     dashes, parentheses, US country-code omission.
 */
export function normalizeHandle(h: string): string {
  if (!h) return "";
  if (h.includes("@")) return h.trim().toLowerCase();
  const digits = h.replace(/\D/g, "");
  return digits.slice(-10);
}

/** Build a normalized-handle → display-name map. */
export function buildContactLookup(
  contacts: Record<string, string> | undefined,
): Map<string, string> {
  const map = new Map<string, string>();
  if (!contacts) return map;
  for (const [raw, name] of Object.entries(contacts)) {
    const key = normalizeHandle(raw);
    if (key) map.set(key, name);
  }
  return map;
}

/** Build the set of normalized allowlisted handles. */
export function buildAllowlistSet(
  allowlist: string[] | undefined,
): Set<string> {
  const set = new Set<string>();
  if (!allowlist) return set;
  for (const raw of allowlist) {
    const key = normalizeHandle(raw);
    if (key) set.add(key);
  }
  return set;
}

/** Resolve a single handle (possibly a comma-joined group chat) via config. */
export function resolveDisplayName(
  handle: string,
  lookup: Map<string, string>,
): string {
  if (!handle) return handle;
  if (handle.includes(",")) {
    const parts = handle
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
    return parts
      .map((p) => lookup.get(normalizeHandle(p)) ?? p)
      .join(", ");
  }
  return lookup.get(normalizeHandle(handle)) ?? handle;
}

/** Check whether a handle passes the allowlist. Empty set = pass-through. */
export function passesAllowlist(
  handle: string,
  allowlist: Set<string>,
): boolean {
  if (allowlist.size === 0) return true;
  if (!handle) return false;
  if (handle.includes(",")) {
    return handle
      .split(",")
      .map((p) => normalizeHandle(p.trim()))
      .some((k) => allowlist.has(k));
  }
  return allowlist.has(normalizeHandle(handle));
}
