"use client";

import dynamic from "next/dynamic";
import { Topbar } from "@/components/layout/topbar";
import { DashboardGrid } from "@/components/layout/dashboard-grid";
import { WidgetWrapper } from "@/components/layout/widget-wrapper";
import { ChatbotPanel } from "@/components/chat/chatbot-panel";
import { MorningBriefing } from "@/components/widgets/morning-briefing";
import { CalendarWidget } from "@/components/widgets/calendar-widget";
import { EmailWidget } from "@/components/widgets/email-widget";
import { IMessageWidget } from "@/components/widgets/imessage-widget";
import { AnkiStatsWidget } from "@/components/widgets/anki-stats-widget";
import { PomodoroWidget } from "@/components/widgets/pomodoro-widget";
import { WeekWidget } from "@/components/widgets/week-widget";
import { SpotifyWidget } from "@/components/widgets/spotify-widget";
import { DeepFocusOverlay } from "@/components/layout/deep-focus-overlay";

// OP-01: NBME chart widget pulls in recharts (~238KB gzipped). Splitting it
// into its own chunk shrinks the root bundle and defers recharts until the
// chart is actually rendered.
const NBMETrackerWidget = dynamic(
  () => import("@/components/widgets/nbme-tracker-widget").then(m => ({ default: m.NBMETrackerWidget })),
  { ssr: false, loading: () => <div className="jv-skeleton rounded-xl h-full w-full" /> }
);

// OP-04: below-fold widgets (y >= 24 in DEFAULT_LAYOUT) — defer until needed.
// ssr: false keeps them out of the initial server-rendered payload; the
// loading placeholder mounts in their slot until the chunk loads.
const UWorldWidget = dynamic(
  () => import("@/components/widgets/uworld-widget").then(m => ({ default: m.UWorldWidget })),
  { ssr: false, loading: () => <div className="jv-skeleton rounded-xl h-full w-full" /> }
);
const StudyStreakWidget = dynamic(
  () => import("@/components/widgets/study-streak-widget").then(m => ({ default: m.StudyStreakWidget })),
  { ssr: false, loading: () => <div className="jv-skeleton rounded-xl h-full w-full" /> }
);
const TriageWidget = dynamic(
  () => import("@/components/widgets/triage-widget").then(m => ({ default: m.TriageWidget })),
  { ssr: false, loading: () => <div className="jv-skeleton rounded-xl h-full w-full" /> }
);

// MorningBriefing and SpotifyWidget manage their own WidgetWrapper so they
// can forward status/lastUpdated props from inside the component where the
// fetch state lives. All other widgets use the standard external wrapper.
const widgets: Record<string, React.ReactNode> = {
  briefing:  <MorningBriefing />,
  calendar:  <WidgetWrapper><CalendarWidget /></WidgetWrapper>,
  email:     <WidgetWrapper><EmailWidget /></WidgetWrapper>,
  imessage:  <WidgetWrapper><IMessageWidget /></WidgetWrapper>,
  anki:      <WidgetWrapper><AnkiStatsWidget /></WidgetWrapper>,
  pomodoro:  <WidgetWrapper><PomodoroWidget /></WidgetWrapper>,
  week:      <WidgetWrapper><WeekWidget /></WidgetWrapper>,
  streak:    <WidgetWrapper><StudyStreakWidget /></WidgetWrapper>,
  spotify:   <SpotifyWidget />,
  qbank:     <WidgetWrapper><UWorldWidget /></WidgetWrapper>,
  nbme:      <WidgetWrapper><NBMETrackerWidget /></WidgetWrapper>,
  chatbot:   <ChatbotPanel embedded />,
  triage:    <WidgetWrapper><TriageWidget /></WidgetWrapper>,
};

export default function Home() {
  return (
    <div className="flex h-screen flex-col">
      <Topbar />
      <main className="flex-1 overflow-y-auto p-4">
        <DashboardGrid widgets={widgets} />
      </main>
      <DeepFocusOverlay />
    </div>
  );
}
