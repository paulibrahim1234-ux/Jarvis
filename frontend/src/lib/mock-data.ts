import type {
  CalendarEvent,
  Email,
  AnkiStats,
  Message,
  QBankSession,
  WeakTopic,
  NBMEScore,
  PomodoroSession,
  StudyDay,
  Briefing,
  WeekDay,
} from "@/lib/types";

export const mockBriefing: Briefing = {
  greeting: "Good morning.",
  summary:
    "You have 5 events today including Surgery Grand Rounds at 7 AM. 142 Anki cards are due and your retention is holding at 92%. Two unread Canvas emails need attention.",
  highlights: [
    "Surgery Grand Rounds at 7:00 AM in Amphitheater B",
    "142 Anki cards due today -- 18-day streak on the line",
    "UWorld session yesterday: 78% on Cardiology block",
    "NBME 28 scheduled for next Friday",
  ],
};

export const mockCalendarEvents: CalendarEvent[] = [
  {
    id: "1",
    title: "Surgery Grand Rounds",
    time: "7:00 AM - 8:00 AM",
    location: "Amphitheater B",
    type: "lecture",
  },
  {
    id: "2",
    title: "OR Observation - Dr. Chen",
    time: "8:30 AM - 12:00 PM",
    location: "OR Suite 4",
    type: "clinical",
  },
  {
    id: "3",
    title: "Clerkship Director Meeting",
    time: "12:30 PM - 1:00 PM",
    location: "Admin 204",
    type: "meeting",
  },
  {
    id: "4",
    title: "Shelf Exam Review",
    time: "2:00 PM - 4:00 PM",
    location: "Library Room 3",
    type: "exam",
  },
  {
    id: "5",
    title: "Gym",
    time: "5:30 PM - 6:30 PM",
    location: "Rec Center",
    type: "personal",
  },
];

export const mockEmails: Email[] = [
  {
    id: "1",
    from: "Canvas Notifications",
    subject: "New Assignment: Surgery Shelf Practice Exam",
    preview:
      "A new assignment has been posted in SURG 7010. Due date: April 18...",
    time: "8:12 AM",
    read: false,
    source: "canvas",
  },
  {
    id: "2",
    from: "Dr. Sarah Mitchell",
    subject: "Re: Case Presentation Feedback",
    preview:
      "Great job on the appendicitis case yesterday. A few suggestions for next time...",
    time: "7:45 AM",
    read: false,
  },
  {
    id: "3",
    from: "One45",
    subject: "Duty Hours Reminder",
    preview:
      "Please submit your duty hours for the week ending April 11 by Friday...",
    time: "6:30 AM",
    read: true,
    source: "one45",
  },
  {
    id: "4",
    from: "Canvas Notifications",
    subject: "Grade Posted: Pathology Quiz 7",
    preview: "Your grade for Pathology Quiz 7 has been posted. Score: 88%...",
    time: "Yesterday",
    read: true,
    source: "canvas",
  },
  {
    id: "5",
    from: "Study Group",
    subject: "Tomorrow's session - Renal Physiology",
    preview:
      "Hey everyone, just confirming we are meeting at 6 PM in the library...",
    time: "Yesterday",
    read: true,
  },
];

export const mockAnkiStats: AnkiStats = {
  due: 142,
  reviewedToday: 87,
  streak: 18,
  newCards: 20,
  retention: 92,
};

export const mockMessages: Message[] = [
  {
    id: "1",
    contact: "Mom",
    text: "Don't forget to call Grandma this weekend!",
    time: "9:15 AM",
    isFromMe: false,
  },
  {
    id: "2",
    contact: "Mom",
    text: "I will! Probably Sunday afternoon",
    time: "9:18 AM",
    isFromMe: true,
  },
  {
    id: "3",
    contact: "Jake (Surgery)",
    text: "Hey are you scrubbing into the lap chole today?",
    time: "8:45 AM",
    isFromMe: false,
  },
  {
    id: "4",
    contact: "Jake (Surgery)",
    text: "Yeah Dr. Chen said I could first assist",
    time: "8:47 AM",
    isFromMe: true,
  },
  {
    id: "5",
    contact: "Jake (Surgery)",
    text: "Nice! Save me the appy case tomorrow then",
    time: "8:48 AM",
    isFromMe: false,
  },
  {
    id: "6",
    contact: "Mia",
    text: "Still on for dinner tonight?",
    time: "8:30 AM",
    isFromMe: false,
  },
  {
    id: "7",
    contact: "Mia",
    text: "Yep! 7pm at the usual spot",
    time: "8:32 AM",
    isFromMe: true,
  },
];

export const mockQBankSessions: QBankSession[] = [
  {
    id: "1",
    platform: "uworld",
    date: "Apr 10",
    score: 78,
    total: 40,
    correct: 31,
    topics: ["Cardiology"],
  },
  {
    id: "2",
    platform: "uworld",
    date: "Apr 9",
    score: 72,
    total: 40,
    correct: 29,
    topics: ["Pulmonology"],
  },
  {
    id: "3",
    platform: "uworld",
    date: "Apr 8",
    score: 85,
    total: 40,
    correct: 34,
    topics: ["GI"],
  },
  {
    id: "4",
    platform: "truelearn",
    date: "Apr 10",
    score: 70,
    total: 30,
    correct: 21,
    topics: ["Surgery Shelf"],
  },
  {
    id: "5",
    platform: "truelearn",
    date: "Apr 9",
    score: 67,
    total: 30,
    correct: 20,
    topics: ["Surgery Shelf"],
  },
  {
    id: "6",
    platform: "truelearn",
    date: "Apr 7",
    score: 73,
    total: 30,
    correct: 22,
    topics: ["Surgery Shelf"],
  },
];

export const mockWeakTopics: WeakTopic[] = [
  { topic: "Renal Physiology", score: 58, totalQuestions: 45, trend: "improving" },
  { topic: "Biostatistics", score: 52, totalQuestions: 38, trend: "stable" },
  { topic: "Immunology", score: 61, totalQuestions: 52, trend: "declining" },
  { topic: "Pharmacology - Autonomic", score: 55, totalQuestions: 30, trend: "improving" },
  { topic: "Endocrine", score: 63, totalQuestions: 41, trend: "stable" },
];

export const mockNBMEScores: NBMEScore[] = [
  { id: "1", exam: "NBME 25", date: "Jan 15", score: 198, percentile: 32 },
  { id: "2", exam: "NBME 26", date: "Feb 5", score: 210, percentile: 45 },
  { id: "3", exam: "NBME 27", date: "Feb 28", score: 218, percentile: 55 },
  { id: "4", exam: "NBME 29", date: "Mar 20", score: 225, percentile: 63 },
  { id: "5", exam: "NBME 30", date: "Apr 5", score: 232, percentile: 72 },
];

export const mockPomodoroSessions: PomodoroSession[] = [
  { id: "1", date: "2026-04-11", duration: 25, topic: "Anki", completed: true },
  { id: "2", date: "2026-04-11", duration: 25, topic: "UWorld", completed: true },
  { id: "3", date: "2026-04-11", duration: 25, topic: "UWorld", completed: true },
  { id: "4", date: "2026-04-11", duration: 25, topic: "Surgery Notes", completed: false },
];

// Generate 364 days of study data for the heatmap
function generateStudyDays(): StudyDay[] {
  const days: StudyDay[] = [];
  const today = new Date();
  for (let i = 363; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const dateStr = d.toISOString().split("T")[0];
    const dayOfWeek = d.getDay();
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    let minutes: number;
    // Seeded-ish random based on date string for consistency
    const hash = dateStr.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
    const pseudo = ((hash * 9301 + 49297) % 233280) / 233280;
    if (pseudo < 0.08) {
      minutes = 0;
    } else if (isWeekend) {
      minutes = Math.floor(pseudo * 90);
    } else {
      minutes = Math.floor(30 + pseudo * 150);
    }
    days.push({ date: dateStr, minutes });
  }
  return days;
}

export const mockStudyDays: StudyDay[] = generateStudyDays();

export const mockWeekEvents: WeekDay[] = [
  {
    day: "Monday, Apr 13",
    events: [
      { id: "w1", title: "Morning Report", time: "7:00 AM - 7:30 AM", location: "Conf Room A", type: "lecture" },
      { id: "w2", title: "OR - Dr. Patel (Hernia)", time: "8:00 AM - 12:00 PM", location: "OR Suite 2", type: "clinical" },
      { id: "w3", title: "Noon Conference", time: "12:00 PM - 1:00 PM", location: "Amphitheater B", type: "lecture" },
      { id: "w4", title: "Study Block", time: "2:00 PM - 5:00 PM", type: "personal" },
    ],
  },
  {
    day: "Tuesday, Apr 14",
    events: [
      { id: "w5", title: "Surgery Grand Rounds", time: "7:00 AM - 8:00 AM", location: "Amphitheater B", type: "lecture" },
      { id: "w6", title: "Floor Rounding", time: "8:30 AM - 11:00 AM", location: "5 North", type: "clinical" },
      { id: "w7", title: "Sim Lab - Suturing", time: "1:00 PM - 3:00 PM", location: "Sim Center", type: "clinical" },
    ],
  },
  {
    day: "Wednesday, Apr 15",
    events: [
      { id: "w8", title: "OR - Dr. Chen (Lap Chole)", time: "7:30 AM - 12:00 PM", location: "OR Suite 4", type: "clinical" },
      { id: "w9", title: "Clerkship Small Group", time: "1:00 PM - 2:30 PM", location: "Room 210", type: "lecture" },
      { id: "w10", title: "UWorld Block", time: "3:00 PM - 5:00 PM", type: "personal" },
    ],
  },
  {
    day: "Thursday, Apr 16",
    events: [
      { id: "w11", title: "M&M Conference", time: "7:00 AM - 8:00 AM", location: "Amphitheater B", type: "lecture" },
      { id: "w12", title: "Clinic - Gen Surg", time: "8:30 AM - 4:00 PM", location: "Surgery Clinic", type: "clinical" },
    ],
  },
  {
    day: "Friday, Apr 17",
    events: [
      { id: "w13", title: "Morning Report", time: "7:00 AM - 7:30 AM", location: "Conf Room A", type: "lecture" },
      { id: "w14", title: "NBME 28 Practice Exam", time: "9:00 AM - 1:00 PM", location: "Testing Center", type: "exam" },
      { id: "w15", title: "Post-Exam Debrief", time: "2:00 PM - 3:00 PM", location: "Library Room 3", type: "meeting" },
    ],
  },
];
