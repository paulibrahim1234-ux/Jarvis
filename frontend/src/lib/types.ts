// Calendar
export interface CalendarEvent {
  id: string;
  title: string;
  time: string; // "8:00 AM - 9:00 AM"
  location?: string;
  type: "lecture" | "clinical" | "exam" | "meeting" | "personal";
}

// Email
export interface Email {
  id: string;
  from: string;
  /** Raw from_email address (e.g. "noreply@rowan.edu") — used for domain scoring. */
  from_email: string;
  subject: string;
  preview: string;
  time: string;
  read: boolean;
  source?: "canvas" | "one45" | "school" | "other";
  account?: string;
  folder?: string;
}

// Anki
export interface AnkiStats {
  due: number;
  reviewedToday: number;
  streak: number; // days
  newCards: number;
  retention: number; // percentage

  // Iter-3 enrichment — surface the real state instead of "0 due" looking broken.
  // `learning` = cards in the learning queue right now (re-review steps).
  // `suspended` = cards user has parked (AnKing default-suspend workflow).
  // `available_total` = non-suspended, non-buried cards (the active pool).
  // `suggested_count` = UWorld-mapped cards waiting to be unsuspended.
  learning?: number;
  suspended?: number;
  available_total?: number;
  suggested_count?: number;
}

// iMessage
export interface Message {
  id: string;
  contact: string;
  text: string;
  time: string;
  isFromMe: boolean;
}

// UWorld / TrueLearn
export interface QBankSession {
  id: string;
  platform: "uworld" | "truelearn";
  date: string;
  score: number; // percentage
  // Backend returns null for stub/stale sessions (see widgets.py
  // `stale_data` path) — types must reflect that.
  total: number | null;
  correct: number | null;
  topics: string[];
}

export interface WeakTopic {
  topic: string;
  score: number;
  totalQuestions: number;
  trend: "improving" | "declining" | "stable";
}

// NBME — field names match the backend payload (api/widgets.py NBMEScore).
// Old shape (exam/date/score) was a type lie that any future consumer
// importing this would silently fail on.
export interface NBMEScore {
  id: string;
  exam_name: string;
  date_taken: string;
  raw_score: number;
  percentile?: number | null;
  notes?: string | null;
}

// Pomodoro
export interface PomodoroSession {
  id: string;
  date: string;
  duration: number; // minutes
  topic?: string;
  completed: boolean;
}

// Study Streak Heatmap
export interface StudyDay {
  date: string; // YYYY-MM-DD
  minutes: number;
}

// Morning Briefing
export interface Briefing {
  greeting: string;
  summary: string;
  highlights: string[];
}

// Week View
export interface WeekDay {
  day: string; // "Monday", "Tuesday", etc.
  events: CalendarEvent[];
}

// Chat
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}
