export interface Mood {
  name: string;
  emoji: string;
  playlistId: string;
}

export const DEFAULT_MOODS: Mood[] = [
  { name: "Studying", emoji: "📚", playlistId: "37i9dQZF1DWZeKCadgRdKQ" },
  { name: "Lo-fi",    emoji: "🎧", playlistId: "37i9dQZF1DWWQRwui0ExPn" },
  { name: "Chilling", emoji: "☁️", playlistId: "37i9dQZF1DX4WYpdgoIcn6" },
  { name: "Coding",   emoji: "💻", playlistId: "37i9dQZF1DX5trt9i14X7j" },
  { name: "Workout",  emoji: "💪", playlistId: "37i9dQZF1DX76Wlfdnj7AP" },
  { name: "Run",      emoji: "🏃", playlistId: "37i9dQZF1DWSJHnPb1f0X3" },
  { name: "Sleep",    emoji: "😴", playlistId: "37i9dQZF1DWZd79rJ6a7lp" },
  { name: "Coffee",   emoji: "☕", playlistId: "37i9dQZF1DX9vYRBO9gjDe" },
  { name: "Driving",  emoji: "🚗", playlistId: "37i9dQZF1DX9wC1KY45plY" },
  { name: "Pump-Up",  emoji: "🔥", playlistId: "37i9dQZF1DX76t638V6CA8" },
  { name: "Dinner",   emoji: "🍷", playlistId: "37i9dQZF1DX4xuWVBs4FgJ" },
  { name: "Focus",    emoji: "🧠", playlistId: "37i9dQZF1DX8NTLI2TtZa6" },
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
