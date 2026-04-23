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
  total: number;
  correct: number;
  topics: string[];
}

export interface WeakTopic {
  topic: string;
  score: number;
  totalQuestions: number;
  trend: "improving" | "declining" | "stable";
}

// NBME
export interface NBMEScore {
  id: string;
  exam: string;
  date: string;
  score: number;
  percentile?: number;
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
