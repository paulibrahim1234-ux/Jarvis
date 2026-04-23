"use client";

import { useRef, useState, useEffect, useMemo } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { fetchCalendar } from "@/lib/api";
import { openInApp } from "@/lib/open-apps";
import {
  groupByDay,
  rangeForNextDays,
  formatTime,
  type RawCalendarEvent,
  type BucketedEvent,
} from "@/lib/calendar";

// Lightweight type inference from event title (no mock fallback — we want
// the widget to show connect-state, not fake data).
function inferType(title: string): string {
  const t = title.toLowerCase();
  if (/exam|shelf|nbme|uworld|quiz|test/.test(t)) return "exam";
  if (/rotation|clinic|rounds|call|ward|or\b|surgery|hospital/.test(t)) return "clinical";
  if (/lecture|class|small group|cbl|pbl|pcm|didactic/.test(t)) return "lecture";
  if (/meeting|advisor|mentor|1:1|one-on-one/.test(t)) return "meeting";
  return "personal";
}

const typeColors: Record<string, string> = {
  lecture: "bg-blue-500/10 text-blue-400",
  clinical: "bg-emerald-500/10 text-emerald-400",
  exam: "bg-red-500/10 text-red-400",
  meeting: "bg-amber-500/10 text-amber-400",
  personal: "bg-purple-500/10 text-purple-400",
};

export function WeekWidget() {
  const contentRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [events, setEvents] = useState<RawCalendarEvent[]>([]);
  const [live, setLive] = useState(false);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) setContainerWidth(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const range = rangeForNextDays(7);
    fetchCalendar(range)
      .then((data) => {
        if (data.auth_needed) {
          setAuthUrl(data.auth_url ?? "http://localhost:8000/auth/microsoft");
        } else if (data.available && Array.isArray(data.events)) {
          setEvents(data.events as RawCalendarEvent[]);
          setLive(true);
        }
      })
      .catch(() => {
        /* backend offline — leave empty; render empty-state */
      })
      .finally(() => setLoading(false));
  }, []);

  const grouped = useMemo(() => {
    const start = new Date();
    return groupByDay(events, start, 7);
  }, [events]);

  const isWide = containerWidth > 600;
  const isVeryWide = containerWidth > 900;

  const unavailable = !loading && !live;

  return (
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-5 pb-3">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          This Week
          {live ? (
            <span
              className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block"
              title="Live from Outlook"
            />
          ) : authUrl ? (
            <a
              href={authUrl}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] normal-case font-normal text-blue-400/70 hover:text-blue-400 underline"
            >
              connect Outlook
            </a>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent ref={contentRef} className="flex-1 min-h-0 p-5 pt-0">
        {unavailable ? (
          <div className="flex h-full items-center justify-center text-center">
            <p className="text-xs text-muted-foreground/70">
              Calendar unavailable — {authUrl ? "connect Outlook above" : "backend offline"}.
            </p>
          </div>
        ) : (
          <div className="relative h-full">
            {isWide ? (
              <div
                className="grid h-full gap-3"
                style={{
                  gridTemplateColumns: isVeryWide
                    ? `repeat(${grouped.length}, 1fr)`
                    : "repeat(2, 1fr)",
                }}
              >
                {grouped.map((day) => (
                  <DayColumn key={day.label} day={day} />
                ))}
              </div>
            ) : (
              <>
                <ScrollArea className="h-full">
                  <div className="space-y-4 pr-2">
                    {grouped.map((day) => (
                      <DayColumn key={day.label} day={day} />
                    ))}
                  </div>
                </ScrollArea>
                <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-card to-transparent" />
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DayColumn({
  day,
}: {
  day: { day: Date; label: string; events: BucketedEvent[] };
}) {
  return (
    <div className="min-h-0 flex flex-col">
      <div className="mb-2 rounded-md bg-white/[0.03] px-3 py-1.5 shrink-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {day.label}
        </p>
      </div>
      <ScrollArea className="flex-1 min-h-0">
        <div className="space-y-0.5 pr-1">
          {day.events.length === 0 ? (
            <p className="px-3 py-2 text-[11px] text-muted-foreground/40">—</p>
          ) : (
            day.events.map((event) => {
              const kind = inferType(event.title);
              const span =
                event.dayIndex && event.dayTotal && event.dayTotal > 1
                  ? `day ${event.dayIndex} of ${event.dayTotal}`
                  : event.ongoing
                  ? "ongoing"
                  : null;

              const handleClick = async () => {
                // Per HIPAA boundary: do not log event title or sensitive data
                try {
                  await openInApp({
                    app: "outlook-calendar",
                    ref: event.id,
                    context: { start: new Date(event.start).toISOString() },
                  });
                } catch (error) {
                  // Fire-and-forget; error already logged in openInApp
                }
              };

              return (
                <div
                  key={event.id}
                  onClick={handleClick}
                  className="cursor-pointer flex items-start gap-2 rounded-lg px-3 py-2 text-xs hover:bg-white/10 transition-colors"
                >
                  <span className="font-mono text-muted-foreground/60 shrink-0 w-16 pt-0.5">
                    {event.isAllDay || event.ongoing ? "all-day" : formatTime(event.start)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate font-medium">{event.title}</span>
                      <Badge
                        variant="secondary"
                        className={`text-[10px] px-1.5 py-0 h-4 shrink-0 border-none ${
                          typeColors[kind] ?? ""
                        }`}
                      >
                        {kind.charAt(0).toUpperCase() + kind.slice(1)}
                      </Badge>
                    </div>
                    {span && (
                      <p className="text-muted-foreground/50 mt-0.5 text-[10px] italic">
                        {span}
                      </p>
                    )}
                    {event.location && (
                      <p className="text-muted-foreground/60 truncate mt-0.5">
                        {event.location}
                      </p>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
