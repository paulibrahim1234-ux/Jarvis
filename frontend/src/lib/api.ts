export const BACKEND = "http://localhost:8000";

export async function backendAvailable(): Promise<boolean> {
  try {
    const r = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(1500) });
    return r.ok;
  } catch {
    return false;
  }
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
  conversation_id: string;
}

export async function postChat(
  messages: ChatTurn[],
  opts: { conversation_id?: string; model?: "haiku" | "sonnet" } = {}
): Promise<ChatResponse> {
  const qs = opts.model ? `?model=${opts.model}` : "";
  const r = await fetch(`${BACKEND}/chat${qs}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, conversation_id: opts.conversation_id }),
    signal: AbortSignal.timeout(60000),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail ?? "Backend error");
  }
  return r.json();
}

export interface ConversationMeta {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationMeta {
  messages: {
    id: number;
    role: "user" | "assistant";
    content: string;
    created_at: string;
  }[];
}

export async function listConversations(): Promise<ConversationMeta[]> {
  const r = await fetch(`${BACKEND}/chat/conversations`, {
    signal: AbortSignal.timeout(5000),
  });
  if (!r.ok) throw new Error("Failed to list conversations");
  const data = await r.json();
  return data.conversations ?? [];
}

export async function createConversation(title?: string): Promise<ConversationMeta> {
  const r = await fetch(`${BACKEND}/chat/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error("Failed to create conversation");
  return r.json();
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const r = await fetch(`${BACKEND}/chat/conversations/${id}`);
  if (!r.ok) throw new Error("Failed to get conversation");
  return r.json();
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await fetch(`${BACKEND}/chat/conversations/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("Failed to delete conversation");
}

export async function fetchAnkiStats() {
  const r = await fetch(`${BACKEND}/widgets/anki`, {
    signal: AbortSignal.timeout(30000),
  });
  return r.json();
}

export interface AnkiSuggestion {
  card_id: number;
  front: string;
  tag: string;
  uworld_qid: string;
  uworld_topic: string;
  missed_at: string;
}

export async function fetchAnkiSuggestions(): Promise<{
  suggestions: AnkiSuggestion[];
  available: boolean;
  error?: string;
  source?: string;
}> {
  const r = await fetch(`${BACKEND}/widgets/anki/suggestions`, {
    signal: AbortSignal.timeout(30000),
  });
  return r.json();
}

export async function unsuspendAnkiCards(
  ids: number[],
): Promise<{ unsuspended: number; errors: string[] }> {
  const r = await fetch(`${BACKEND}/widgets/anki/unsuspend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ card_ids: ids }),
    signal: AbortSignal.timeout(15000),
  });
  if (!r.ok) throw new Error(`anki unsuspend ${r.status}`);
  return r.json();
}

export interface StudyStreakDay {
  date: string; // YYYY-MM-DD
  minutes: number; // 0 means no review activity that day
}

export interface StudyStreakResponse {
  days: StudyStreakDay[];
  available: boolean;
  error?: string;
}

export async function fetchStudyStreak(): Promise<StudyStreakResponse> {
  try {
    const r = await fetch(`${BACKEND}/widgets/study-streak`, {
      signal: AbortSignal.timeout(30000),
    });
    if (!r.ok) return { days: [], available: false, error: `HTTP ${r.status}` };
    return r.json();
  } catch (e) {
    return { days: [], available: false, error: String(e) };
  }
}

export async function fetchIMessages() {
  const r = await fetch(`${BACKEND}/widgets/imessage`, {
    signal: AbortSignal.timeout(30000),
  });
  return r.json();
}

export async function fetchEmails(opts?: { folder?: string; account?: string }) {
  const url = new URL(`${BACKEND}/widgets/email`);
  if (opts?.folder) url.searchParams.set("folder", opts.folder);
  if (opts?.account) url.searchParams.set("account", opts.account);
  const r = await fetch(url.toString(), {
    signal: AbortSignal.timeout(30000),
  });
  return r.json();
}

export type EmailFolder = { name: string; unread: number };
export type EmailAccountFolders = {
  account: string;
  account_email: string;
  folders: EmailFolder[];
};

export async function fetchEmailFolders(): Promise<{
  accounts: EmailAccountFolders[];
  available: boolean;
  error?: string;
}> {
  const r = await fetch(`${BACKEND}/widgets/email/folders`, {
    signal: AbortSignal.timeout(30000),
  });
  if (!r.ok) throw new Error(`email folders ${r.status}`);
  return r.json();
}

export async function fetchSpotify() {
  const r = await fetch(`${BACKEND}/widgets/spotify`, {
    signal: AbortSignal.timeout(30000),
  });
  return r.json();
}

export async function searchSpotify(query: string, limit = 10) {
  const r = await fetch(`${BACKEND}/widgets/spotify/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit }),
    signal: AbortSignal.timeout(15000),
  });
  if (!r.ok) throw new Error(`spotify search ${r.status}`);
  return r.json();
}

export async function playSpotifyURI(uri: string) {
  const r = await fetch(`${BACKEND}/widgets/spotify/play`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uri }),
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) throw new Error(`spotify play ${r.status}`);
  return r.json().catch(() => ({}));
}

export async function controlSpotify(cmd: "play" | "pause" | "next" | "previous") {
  const action =
    cmd === "play" || cmd === "pause" ? "toggle" : cmd === "previous" ? "prev" : cmd;
  const r = await fetch(`${BACKEND}/widgets/spotify/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) throw new Error(`spotify control ${r.status}`);
  return r.json().catch(() => ({}));
}

export async function setSpotifyVolume(volume: number) {
  const r = await fetch(`${BACKEND}/widgets/spotify/volume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ volume }),
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) throw new Error(`spotify volume ${r.status}`);
  return r.json().catch(() => ({}));
}

export async function fetchCalendar(range?: { start: string; end: string }) {
  const url = new URL(`${BACKEND}/widgets/calendar`);
  if (range) {
    url.searchParams.set("start", range.start);
    url.searchParams.set("end", range.end);
  }
  const r = await fetch(url.toString(), {
    signal: AbortSignal.timeout(30000),
  });
  return r.json();
}

// Morning briefing aggregator (anki + events + unread + greeting).
export async function fetchBriefing() {
  const r = await fetch(`${BACKEND}/widgets/briefing`, {
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) throw new Error(`briefing ${r.status}`);
  return r.json();
}

// NBME score CRUD.
export type NBMEScore = {
  id: string;
  exam_name: string;
  date_taken: string;
  raw_score: number;
  percentile: number | null;
  notes: string | null;
};

export async function fetchNBME(): Promise<{ scores: NBMEScore[]; available: boolean }> {
  const r = await fetch(`${BACKEND}/widgets/nbme`, {
    signal: AbortSignal.timeout(5000),
  });
  if (!r.ok) throw new Error(`nbme ${r.status}`);
  return r.json();
}

export async function postNBMEScore(
  score: Omit<NBMEScore, "id">,
): Promise<NBMEScore> {
  const r = await fetch(`${BACKEND}/widgets/nbme`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(score),
    signal: AbortSignal.timeout(5000),
  });
  if (!r.ok) throw new Error(`nbme create ${r.status}`);
  return r.json();
}

export async function deleteNBMEScore(id: string): Promise<void> {
  const r = await fetch(`${BACKEND}/widgets/nbme/${id}`, {
    method: "DELETE",
    signal: AbortSignal.timeout(5000),
  });
  if (!r.ok) throw new Error(`nbme delete ${r.status}`);
}

export async function fetchAuthStatus() {
  const r = await fetch(`${BACKEND}/auth/status`, {
    signal: AbortSignal.timeout(3000),
  });
  return r.json();
}
