export const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

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
  opts: { conversation_id?: string; model?: "haiku" | "sonnet"; signal?: AbortSignal } = {}
): Promise<ChatResponse> {
  const qs = opts.model ? `?model=${opts.model}` : "";
  const r = await fetch(`${BACKEND}/chat${qs}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, conversation_id: opts.conversation_id }),
    signal: opts.signal ?? AbortSignal.timeout(60000),
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
    signal: AbortSignal.timeout(10_000),
  });
  if (!r.ok) throw new Error("Failed to create conversation");
  return r.json();
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const r = await fetch(`${BACKEND}/chat/conversations/${id}`, {
    signal: AbortSignal.timeout(30_000),
  });
  if (!r.ok) throw new Error("Failed to get conversation");
  return r.json();
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await fetch(`${BACKEND}/chat/conversations/${id}`, {
    method: "DELETE",
    signal: AbortSignal.timeout(10_000),
  });
  if (!r.ok) throw new Error("Failed to delete conversation");
}

export async function fetchAnkiStats() {
  const r = await fetch(`${BACKEND}/widgets/anki`, {
    signal: AbortSignal.timeout(30000),
  });
  if (!r.ok) throw new Error(`anki stats ${r.status}`);
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

export interface UWorldSession {
  id: string;
  platform: "uworld" | "truelearn";
  date: string;
  score: number;
  total: number | null;
  correct: number | null;
  topics: string[];
  test_id?: string | null;
}

export interface UWorldWeakTopic {
  topic: string;
  score: number;
  trend: "improving" | "declining" | "stable";
}

export interface UWorldIncorrect {
  uworld_qid: string;
  uworld_topic: string;
  uworld_system: string;
  uworld_category: string;
  uworld_topic_name: string;
  missed_at: string;
  test_id: string | null;
  test_seq: number | null;
}

export async function fetchUWorldData(): Promise<{
  sessions: UWorldSession[];
  weak_topics: UWorldWeakTopic[];
  incorrect: UWorldIncorrect[];
  available: boolean;
  source?: string;
  scraped_at?: string | null;
  stale_data?: boolean;
  error?: string;
}> {
  try {
    const r = await fetch(`${BACKEND}/widgets/uworld`, {
      signal: AbortSignal.timeout(10000),
    });
    if (!r.ok) return { sessions: [], weak_topics: [], incorrect: [], available: false, error: `HTTP ${r.status}` };
    return r.json();
  } catch (e) {
    return { sessions: [], weak_topics: [], incorrect: [], available: false, error: String(e) };
  }
}

export async function refreshUWorld(): Promise<{
  available: boolean;
  status: string;
  sessions: UWorldSession[];
  weak_topics: UWorldWeakTopic[];
  source?: string;
  message?: string;
  scraped_at?: string;
}> {
  try {
    const r = await fetch(`${BACKEND}/widgets/uworld/refresh`, {
      method: "POST",
      signal: AbortSignal.timeout(300000), // scrape can take up to 5min with Results pages
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ message: `HTTP ${r.status}` }));
      return { available: false, status: "error", sessions: [], weak_topics: [], message: err.message ?? `HTTP ${r.status}` };
    }
    return r.json();
  } catch (e) {
    return { available: false, status: "error", sessions: [], weak_topics: [], message: String(e) };
  }
}

/**
 * Open a UWorld question URL in the user's existing Comet UWorld tab,
 * preserving the logged-in session. Falls back to opening in the default
 * browser when no UWorld tab is currently open.
 */
export async function openUWorldQuestion(url: string): Promise<{ ok: boolean; navigated_existing_tab?: boolean; error?: string }> {
  try {
    const r = await fetch(`${BACKEND}/widgets/uworld/open-question`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
      signal: AbortSignal.timeout(10000),
    });
    if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
    return r.json();
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function fetchAnkiSuggestions(opts?: {
  /** Restrict results to specific UWorld QIDs (for a single session). */
  qidFilter?: string[];
}): Promise<{
  suggestions: AnkiSuggestion[];
  available: boolean;
  error?: string;
  source?: string;
}> {
  const params = new URLSearchParams();
  if (opts?.qidFilter && opts.qidFilter.length > 0) {
    params.set("qid_filter", opts.qidFilter.join(","));
  }
  const qs = params.toString();
  const r = await fetch(`${BACKEND}/widgets/anki/suggestions${qs ? "?" + qs : ""}`, {
    signal: AbortSignal.timeout(30000),
  });
  if (!r.ok) throw new Error(`anki suggestions ${r.status}`);
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

/** Re-run the Anki QID index build (a one-shot scan that maps every
 * suspended UWorld AnKing card to its Step::<qid> tag). Resumable —
 * already-indexed cards are skipped. Returns immediately; status can be
 * polled at /widgets/anki/build-index/status. */
export async function rebuildAnkiQidIndex(): Promise<{ status: string; progress?: number; total?: number; error?: string }> {
  const r = await fetch(`${BACKEND}/widgets/anki/build-index`, {
    method: "POST",
    signal: AbortSignal.timeout(15000),
  });
  if (!r.ok) throw new Error(`anki build-index ${r.status}`);
  return r.json();
}

/** Poll the index-build progress. */
export async function getAnkiBuildIndexStatus(): Promise<{
  running: boolean;
  progress: number;
  total: number;
  percent: number;
  index_size: number;
  error: string | null;
}> {
  const r = await fetch(`${BACKEND}/widgets/anki/build-index/status`, {
    signal: AbortSignal.timeout(5000),
  });
  if (!r.ok) throw new Error(`anki build-index status ${r.status}`);
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
  if (!r.ok) throw new Error(`imessage ${r.status}`);
  return r.json();
}

export async function fetchEmails(opts?: { folder?: string; account?: string }) {
  const url = new URL(`${BACKEND}/widgets/email`);
  if (opts?.folder) url.searchParams.set("folder", opts.folder);
  if (opts?.account) url.searchParams.set("account", opts.account);
  const r = await fetch(url.toString(), {
    signal: AbortSignal.timeout(30000),
  });
  if (!r.ok) throw new Error(`email ${r.status}`);
  return r.json();
}

export type EmailFolder = { name: string; unread: number };
export type EmailAccountFolders = {
  account: string;
  account_email: string;
  folders: EmailFolder[];
};

/** Fetch the full plain-text body of one Outlook email by id. Used by
 * the EmailPreviewModal to show the email content inline without
 * leaving the dashboard. */
export async function fetchEmailBody(id: string): Promise<{
  available: boolean;
  id?: string;
  subject?: string;
  sender_name?: string;
  sender_email?: string;
  received_at?: string;
  body?: string;
  error?: string;
}> {
  const url = new URL(`${BACKEND}/widgets/email/body`);
  url.searchParams.set("id", id);
  const r = await fetch(url.toString(), { signal: AbortSignal.timeout(20000) });
  if (!r.ok) return { available: false, error: `HTTP ${r.status}` };
  return r.json();
}

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
  if (!r.ok) throw new Error(`spotify ${r.status}`);
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

export async function playSpotifyContext(uri: string) {
  const r = await fetch(`${BACKEND}/widgets/spotify/play-context`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context_uri: uri }),
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) throw new Error(`spotify play-context ${r.status}`);
  return r.json().catch(() => ({}));
}

export async function controlSpotify(cmd: "play" | "pause" | "next" | "previous") {
  const action = cmd === "previous" ? "prev" : cmd;
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
  if (!r.ok) throw new Error(`calendar ${r.status}`);
  return r.json();
}

// Morning briefing aggregator (anki + events + unread + greeting).

/** A single todo item returned by /widgets/briefing.
 * Manual todos have source "manual" (or undefined for pre-existing items).
 * Auto-extracted todos from Haiku have source "auto" and additionally carry
 * source_email_id linking back to the originating email.
 * Reminders-backed todos have source "reminders" and a Reminders app id. */
export interface BriefingTodo {
  id: string;
  text: string;
  done: boolean;
  due: string | null;
  created_at: string;
  /** Provenance: "manual" = user-created, "auto" = Haiku-extracted from email,
   * "reminders" = synced from Reminders.app via the backend bridge. */
  source?: "manual" | "auto" | "reminders";
  /** Present only when source === "auto". The Outlook email id the task came from. */
  source_email_id?: string;
  /** Present only when source === "reminders". The Reminders.app item id. */
  reminders_id?: string;
}

export async function fetchBriefing() {
  const r = await fetch(`${BACKEND}/widgets/briefing`, {
    signal: AbortSignal.timeout(20000),
  });
  if (!r.ok) throw new Error(`briefing ${r.status}`);
  return r.json();
}

/** Create a new Reminders.app item via the backend bridge.
 * Optimistic callers should append locally; the backend response includes
 * the assigned Reminders id so the item can be completed/deleted later. */
export async function addTodoReminder(
  title: string,
  due_hint?: string,
): Promise<{ ok: boolean; id?: string }> {
  const r = await fetch(`${BACKEND}/widgets/todos/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, due_hint }),
  });
  if (!r.ok) {
    // Swallow the body — caller inspects ok flag, not the error detail.
    await r.json().catch(() => ({}));
    return { ok: false };
  }
  return r.json();
}

/** Mark a Reminders.app item complete via the backend bridge.
 * Callers should optimistically remove the item from the local list
 * and only show an error if the response comes back ok: false. */
export async function completeTodoReminder(
  id: string,
): Promise<{ ok: boolean }> {
  const r = await fetch(`${BACKEND}/widgets/todos/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  if (!r.ok) return { ok: false };
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

export interface AuthStatus {
  claude: boolean;
  claude_error?: string | null;
  outlook: boolean;
  spotify: boolean;
  anki: boolean;
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  try {
    const r = await fetch(`${BACKEND}/auth/status`, {
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) return { claude: false, outlook: false, spotify: false, anki: false };
    return r.json();
  } catch {
    return { claude: false, outlook: false, spotify: false, anki: false };
  }
}

/** Force-refresh the Anthropic credential probe (bypass server-side cache).
 * Use after the user updates the token via /setup. */
export async function fetchAnthropicStatus(force = false): Promise<{
  ok: boolean;
  error: string | null;
  error_detail?: string;
  checked_at: number;
  cached: boolean;
}> {
  const url = `${BACKEND}/auth/anthropic/status${force ? "?force=true" : ""}`;
  const r = await fetch(url, { signal: AbortSignal.timeout(15000) });
  if (!r.ok) throw new Error(`anthropic status ${r.status}`);
  return r.json();
}

/** Mark an Outlook email as read by its numeric id.
 * Fire-and-forget safe — errors are swallowed by the caller. */
export async function markEmailRead(id: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const r = await fetch(`${BACKEND}/widgets/email/mark-read`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
      signal: AbortSignal.timeout(15000),
    });
    if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
    return r.json();
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

export async function addEmailToCalendar(body: {
  title: string;
  start_iso: string;
  end_iso?: string;
  location?: string;
  notes?: string;
  calendar_name?: string;
}): Promise<{ ok: boolean; event_id?: string; error?: string }> {
  const r = await fetch(`${BACKEND}/widgets/email/add-to-calendar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  });
  // WHY explicit r.ok check: every other POST in this file guards against
  // 4xx/5xx before calling r.json(). Without it, an error response's
  // {detail: '...'} body doesn't match the typed return shape, so the caller
  // sees ok: undefined (falsy) and the UI silently fails with no error message.
  if (!r.ok) {
    const err = await r.json().catch(() => ({} as Record<string, string>));
    return { ok: false, error: err.detail ?? err.message ?? `HTTP ${r.status}` };
  }
  return r.json();
}

export async function fetchSpotifyHome(): Promise<{
  available: boolean;
  error?: string;
  top_tracks?: Array<{ title: string; artist: string; album_art?: string | null; uri?: string | null }>;
  top_artists?: Array<{ name: string; album_art?: string | null; uri?: string | null }>;
  // recently_played here is PLAYLISTS derived from track context (the
  // backend `get_recently_played_playlists`), not raw tracks. Cover lives
  // on the `cover` field; keep `album_art` optional for backwards compat
  // with cached payloads.
  recently_played?: Array<{
    name: string;
    uri: string;
    id: string;
    cover?: string | null;
    album_art?: string | null;
    track_count?: number;
    owner?: string | null;
  }>;
  playlists?: Array<{ name: string; uri: string; id: string; cover?: string | null }>;
  // Backend rate-limit signal — set when Spotify has 429'd Jarvis's app
  // creds. The widget should render a banner instead of empty sections so
  // the user knows it's a temporary upstream issue, not a Jarvis bug.
  rate_limited?: boolean;
  rate_limit_retry_in_seconds?: number;
  rate_limit_message?: string;
}> {
  const r = await fetch(`${BACKEND}/widgets/spotify/home`, {
    signal: AbortSignal.timeout(10000),
  });
  // WHY `HTTP ${r.status}` instead of r.statusText: HTTP/2 connections send
  // an empty status text; r.statusText is "" on all HTTP/2 responses, making
  // the error opaque. A numeric status code is always present and informative.
  if (!r.ok) return { available: false, error: `HTTP ${r.status}` };
  return r.json();
}

// ── Triage (chief-of-staff) ───────────────────────────────────────────────────

export interface TriageInfoItem {
  sender: string;
  subject: string;
  summary: string;
}

export interface TriageMeetingItem {
  sender: string;
  subject: string;
  datetime_hint: string;
  needs_calendar_check: boolean;
}

export interface TriageActionItem {
  sender: string;
  subject_or_thread: string;
  excerpt: string;
  draft_reply: string;
  channel: "email" | "imessage";
}

export interface TriageStaleItem {
  sender: string;
  subject_or_thread: string;
  days_stale: number;
  channel: "email" | "imessage";
}

export interface TriageData {
  skip_count: number;
  skip_senders: string[];
  info_only: TriageInfoItem[];
  meeting_info: TriageMeetingItem[];
  action_required: TriageActionItem[];
  stale: TriageStaleItem[];
  error?: string;
}

/**
 * Fetch the chief-of-staff triage result. Backend caches 5 min (Opus is expensive).
 * Pass `bust: true` to append a cache-busting query param so the backend's
 * _cached() sees a new key and forces a fresh Anthropic call.
 */
export async function fetchTriage(opts: { bust?: boolean } = {}): Promise<TriageData> {
  // WHY 60s timeout: the Opus API call inside the backend can take 10-30s on
  // a cache miss. A short timeout would surface false "fetch failed" errors.
  const url = opts.bust
    ? `${BACKEND}/widgets/triage?bust=${Date.now()}`
    : `${BACKEND}/widgets/triage`;
  const r = await fetch(url, { signal: AbortSignal.timeout(60_000) });
  if (!r.ok) {
    throw new Error(`triage fetch ${r.status}`);
  }
  return r.json();
}
