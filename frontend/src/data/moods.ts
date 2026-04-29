export interface Mood {
  name: string;
  emoji: string;
  playlistId: string;
}

// Defaults seeded from the user's own Spotify library (private repo, OK to
// hardcode private IDs). The Spotify-editorial 37i9dQZF1... IDs that ship
// in many tutorials no longer resolve for non-commercial Web API clients
// (Spotify deprecated that access in late 2024 — see Web API changelog),
// so picking real user-owned playlists is the only thing that actually
// plays without a 404. Edit Moods → Replace playlist… to swap.
export const DEFAULT_MOODS: Mood[] = [
  { name: "Studying", emoji: "📚", playlistId: "7FT5LXHXnf5FRy2PYlPTDN" },  // calm classical reading music
  { name: "Lo-fi",    emoji: "🎧", playlistId: "5SDPei4m0IuABIYRsDJcBC" },  // Chill Drive — Lofi Hip Hop
  { name: "Chilling", emoji: "☁️", playlistId: "5dGBsIih0E2PCAgvMlvRBn" },  // GOOD MOOD SHIT!!!
  { name: "Coding",   emoji: "💻", playlistId: "5SDPei4m0IuABIYRsDJcBC" },  // Chill Drive — Lofi
  { name: "Workout",  emoji: "💪", playlistId: "2heqVugafAhVJtDuW3dV0r" },  // Gym Motivation
  { name: "Run",      emoji: "🏃", playlistId: "4nzyDY8X1m0AQRV5SDrZlQ" },  // Running
  { name: "Sleep",    emoji: "😴", playlistId: "54OYFjQKKwSrZLIkTryYND" },  // Piano & Violin
  { name: "Coffee",   emoji: "☕", playlistId: "7FT5LXHXnf5FRy2PYlPTDN" },  // calm classical reading
  { name: "Driving",  emoji: "🚗", playlistId: "5SDPei4m0IuABIYRsDJcBC" },  // Chill Drive
  { name: "Pump-Up",  emoji: "🔥", playlistId: "4Cy9kER42gAhQWdUO4bZbN" },  // really hype shit
  { name: "Dinner",   emoji: "🍷", playlistId: "54OYFjQKKwSrZLIkTryYND" },  // Piano & Violin
  { name: "Focus",    emoji: "🧠", playlistId: "7FT5LXHXnf5FRy2PYlPTDN" },  // calm classical reading
];

export const MOODS_STORAGE_KEY = "jarvis-moods-v1";

export function loadMoods(): Mood[] {
  if (typeof window === "undefined") return DEFAULT_MOODS;
  try {
    const raw = localStorage.getItem(MOODS_STORAGE_KEY);
    if (!raw) return DEFAULT_MOODS;
    const parsed = JSON.parse(raw);
    if (
      Array.isArray(parsed) &&
      parsed.length > 0 &&
      parsed.every(
        (m) => m && typeof m.name === "string" && typeof m.playlistId === "string",
      )
    ) {
      return parsed as Mood[];
    }
  } catch {
    // corrupt storage — fall through to defaults
  }
  return DEFAULT_MOODS;
}

export function saveMoods(moods: Mood[]): void {
  localStorage.setItem(MOODS_STORAGE_KEY, JSON.stringify(moods));
}

export function resetMoods(): void {
  localStorage.removeItem(MOODS_STORAGE_KEY);
}

/** Extract a playlist ID from a raw Spotify URL or bare ID string.
 * Handles:
 *   https://open.spotify.com/playlist/37i9dQZF1DWZeKCadgRdKQ
 *   spotify:playlist:37i9dQZF1DWZeKCadgRdKQ
 *   37i9dQZF1DWZeKCadgRdKQ  (bare ID)
 */
export function extractPlaylistId(raw: string): string {
  const trimmed = raw.trim();
  // open.spotify.com URL
  const urlMatch = trimmed.match(/open\.spotify\.com\/playlist\/([A-Za-z0-9]+)/);
  if (urlMatch) return urlMatch[1];
  // spotify URI
  const uriMatch = trimmed.match(/^spotify:playlist:([A-Za-z0-9]+)$/);
  if (uriMatch) return uriMatch[1];
  // bare ID (alphanumeric, Spotify IDs are 22 chars but accept any length)
  if (/^[A-Za-z0-9]+$/.test(trimmed)) return trimmed;
  return trimmed;
}
