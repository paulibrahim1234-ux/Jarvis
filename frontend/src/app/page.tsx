"use client";

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
import { StudyStreakWidget } from "@/components/widgets/study-streak-widget";
import { UWorldWidget } from "@/components/widgets/uworld-widget";
import { NBMETrackerWidget } from "@/components/widgets/nbme-tracker-widget";
import { WeekWidget } from "@/components/widgets/week-widget";
import { SpotifyWidget } from "@/components/widgets/spotify-widget";

const widgets: Record<string, React.ReactNode> = {
  briefing:  <WidgetWrapper><MorningBriefing /></WidgetWrapper>,
  calendar:  <WidgetWrapper><CalendarWidget /></WidgetWrapper>,
  email:     <WidgetWrapper><EmailWidget /></WidgetWrapper>,
  imessage:  <WidgetWrapper><IMessageWidget /></WidgetWrapper>,
  anki:      <WidgetWrapper><AnkiStatsWidget /></WidgetWrapper>,
  pomodoro:  <WidgetWrapper><PomodoroWidget /></WidgetWrapper>,
  week:      <WidgetWrapper><WeekWidget /></WidgetWrapper>,
  streak:    <WidgetWrapper><StudyStreakWidget /></WidgetWrapper>,
  spotify:   <WidgetWrapper><SpotifyWidget /></WidgetWrapper>,
  qbank:     <WidgetWrapper><UWorldWidget /></WidgetWrapper>,
  nbme:      <WidgetWrapper><NBMETrackerWidget /></WidgetWrapper>,
  chatbot:   <ChatbotPanel embedded />,
};

export default function Home() {
  return (
    <div className="flex h-screen flex-col">
      <Topbar />
      <main className="flex-1 overflow-y-auto p-4">
        <DashboardGrid widgets={widgets} />
      </main>
    </div>
  );
}
