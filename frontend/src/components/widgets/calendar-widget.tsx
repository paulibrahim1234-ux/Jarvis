"use client";

import { useRef, useState, useEffect, useMemo } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import Skeleton from "@/components/ui/skeleton";
import { ErrorState } from "./error-state";
import { fetchCalendar } from "@/lib/api";
import { openInApp } from "@/lib/open-apps";

type EventType = "lecture" | "clinical" | "exam" | "meeting" | "personal" | "rotation";

interface LiveEvent {
  id: string;
  title: string;
  time: string;          // "9:00 AM - 10:00 AM" or "9:00 AM"
  startLabel: string;    // "9:00 AM"
  location: string;
  calendar: string;      // raw calendar name ("Work", "Rotation", "Outlook" …)
  type: EventType;
  start: Date;
  end: Date | null;      // null for all-day / unknown end
  dayKey: string;        // YYYY-MM-DD of START — for jumping to "now"
  dayLabel: string;      // legacy single-day label (unused after groupByDay rewrite)
}

interface BucketedEvent extends LiveEvent {
  bucketKey: string;        // unique per (event, day) pair
  ongoing: boolean;         // started before this day
  continues: boolean;       // continues past this day
  dayIndex?: number;        // 1-based day within the event's full span
  dayTotal?: number;        // total days the event spans
}

interface DayGroup {
  key: string;
  label: string;
  date: Date;
  events: BucketedEvent[];
}

// Event-type color (icon-ish tag).
const typeColors: Record<EventType, string> = {
  lecture:  "bg-blue-500/10    text-blue-400",
  clinical: "bg-emerald-500/10 text-emerald-400",
  exam:     "bg-red-500/10     text-red-400",
  meeting:  "bg-amber-500/10   text-amber-400",
  personal: "bg-purple-500/10  text-purple-400",
  rotation: "bg-cyan-500/10    text-cyan-400",
};

// Calendar source tag — subtle, distinct from event type.
// Deterministic hash for unknown calendar names so a future "Classes" still gets a stable color.
const calendarPalette = [
  "bg-sky-500/10      text-sky-300      ring-sky-400/20",
  "bg-rose-500/10     text-rose-300     ring-rose-400/20",
  "bg-violet-500/10   text-violet-300   ring-violet-400/20",
  "bg-teal-500/10     text-teal-300     ring-teal-400/20",
  "bg-orange-500/10   text-orange-300   ring-orange-400/20",
  "bg-fuchsia-500/10  text-fuchsia-300  ring-fuchsia-400/20",
  "bg-lime-500/10     text-lime-300     ring-lime-400/20",
];
const calendarFixed: Record<string, string> = {
  Work:        "bg-slate-500/10   text-slate-300   ring-slate-400/20",
  Rotation:    "bg-cyan-500/10    text-cyan-300    ring-cyan-400/20",
  School:      "bg-blue-500/10    text-blue-300    ring-blue-400/20",
  Classes:     "bg-indigo-500/10  text-indigo-300  ring-indigo-400/20",
  Family:      "bg-pink-500/10    text-pink-300    ring-pink-400/20",
  Europe:      "bg-amber-500/10   text-amber-300   ring-amber-400/20",
  Outlook:     "bg-purple-500/10  text-purple-300  ring-purple-400/20",
};

function calendarColor(name: string): string {
  if (calendarFixed[name]) return calendarFixed[name];
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return calendarPalette[Math.abs(h) % calendarPalette.length];
}

function classify(calName: string, title: string): EventType {
  const t = (title || "").toLowerCase();
  const c = (calName || "").toLowerCase();
  if (/exam|nbme|comat|shelf|examsoft|osce/.test(t)) return "exam";
  if (c === "rotation") return "rotation";
  if (/lecture|grand rounds|rounds|report|conference|residency fair|csl/.test(t)) return "lecture";
  if (/or |clinical|rotation|patient|hernia|obs|appt|doctor|drs|apt/.test(t)) return "clinical";
  if (/meet|director|advisor|standup|zoom/.test(t)) return "meeting";
  if (/school|class/.test(c)) return "lecture";
  return "personal";
}

function parseDate(raw: string | undefined): Date | null {
  if (!raw) return null;
  // Backend normalizes \u202f/\u00a0 already, but keep belt-and-suspenders on the client
  // in case an old cached response or raw AppleScript string ever hits this code path.
  const cleaned = raw
    .replace(/\u202f/g, " ")
    .replace(/\u00a0/g, " ")
    .replace(" at ", " ");
  const d = new Date(cleaned);
  return isNaN(d.getTime()) ? null : d;
}

function dayKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function dayLabel(d: Date, today0: Date): string {
  const ev0 = new Date(d);
  ev0.setHours(0, 0, 0, 0);
  const diff = Math.round((ev0.getTime() - today0.getTime()) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  if (diff > 0 && diff < 7) {
    return d.toLocaleDateString([], { weekday: "long" });
  }
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function cleanLocation(loc: string | null | undefined): string {
  if (!loc) return "";
  const cleaned = loc
    .replace(/Building:\s*/i, "")
    .replace(/\s*Room:\s*/i, " · ")
    .replace(/---/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  // If the cleaned string is just a separator or empty, return ""
  return cleaned === "·" || cleaned === "" ? "" : cleaned;
}

function formatEvent(
  e: Record<string, string>,
  i: number,
  today0: Date,
): LiveEvent | null {
  const start = parseDate(e.start);
  if (!start) return null;
  const end = parseDate(e.end);
  const fmtTime = (d: Date) =>
    d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const startLabel = fmtTime(start);
  const time = end ? `${startLabel} - ${fmtTime(end)}` : startLabel;
  const cal = e.calendar || "";

  return {
    id: (e.event_id as string) || String(i),
    title: e.title || "(untitled)",
    time,
    startLabel,
    location: e.location || "",
    calendar: cal,
    type: classify(cal, e.title || ""),
    start,
    end,
    dayKey: dayKey(start),
    dayLabel: dayLabel(start, today0),
  };
}

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function daysBetween(a: Date, b: Date): number {
  return Math.round(
    (startOfDay(b).getTime() - startOfDay(a).getTime()) / 86_400_000,
  );
}

/**
 * Multi-day-aware grouping. A week-long rotation now shows up under EVERY
 * day it overlaps, with a "day N of M" subtitle. Fixes the bug where CSLL
 * (start=Mon 7am, end=Fri 5pm) only appeared on Monday.
 *
 * For each event:
 *   - If it spans only one calendar day → bucket it under that day, no annotation.
 *   - If it spans multiple days → bucket under EACH overlapping day, tagged
 *     with `ongoing` / `continues` flags + `day N of M`.
 */
function groupByDay(events: LiveEvent[], today0: Date): DayGroup[] {
  const map = new Map<string, DayGroup>();

  function bucketFor(d: Date): DayGroup {
    const k = dayKey(d);
    let g = map.get(k);
    if (!g) {
      g = {
        key: k,
        label: dayLabel(d, today0),
        date: startOfDay(d),
        events: [],
      };
      map.set(k, g);
    }
    return g;
  }

  for (const ev of events) {
    const s = ev.start;
    const e = ev.end ?? ev.start; // treat unknown end as same-day
    const sDay = startOfDay(s);
    const eDay = startOfDay(e);
    const span = Math.max(0, daysBetween(sDay, eDay));

    if (span === 0) {
      // Single-day event.
      const b = bucketFor(s);
      b.events.push({
        ...ev,
        bucketKey: `${ev.id}@${b.key}`,
        ongoing: false,
        continues: false,
      });
      continue;
    }

    // Multi-day event — copy under each overlapping day.
    const total = span + 1;
    for (let i = 0; i <= span; i++) {
      const day = new Date(sDay);
      day.setDate(day.getDate() + i);
      const b = bucketFor(day);
      b.events.push({
        ...ev,
        bucketKey: `${ev.id}@${b.key}`,
        ongoing: i > 0,
        continues: i < span,
        dayIndex: i + 1,
        dayTotal: total,
      });
    }
  }

  const groups = Array.from(map.values()).sort(
    (a, b) => a.date.getTime() - b.date.getTime(),
  );
  // Sort within day: all-day / ongoing first, then by start time.
  for (const g of groups) {
    g.events.sort((a, b) => {
      const aOng = a.ongoing ? 0 : 1;
      const bOng = b.ongoing ? 0 : 1;
      if (aOng !== bOng) return aOng - bOng;
      return a.start.getTime() - b.start.getTime();
    });
  }
  return groups;
}

export function CalendarWidget() {
  const contentRef = useRef<HTMLDivElement>(null);
  const nowAnchorRef = useRef<HTMLDivElement>(null);
  const hasScrolledRef = useRef(false);

  const [containerWidth, setContainerWidth] = useState(0);
  const [containerHeight, setContainerHeight] = useState(0);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [status, setStatus] = useState<"loading" | "live" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [calendarCounts, setCalendarCounts] = useState<Record<string, number>>({});
  const [selectedCal, setSelectedCal] = useState<string>("All");
  const [expandedEvent, setExpandedEvent] = useState<BucketedEvent | null>(null);
  // Ref tracks whether we have any events loaded — avoids stale-closure reads
  // of `events` state inside the polling useEffect (which has [] deps).
  const hasEventsRef = useRef(false);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
        setContainerHeight(entry.contentRect.height);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const load = async () => {
      // Recompute today at every refresh so label transitions across midnight.
      const today0 = new Date();
      today0.setHours(0, 0, 0, 0);

      try {
        const data = await fetchCalendar();
        if (!data.available) {
          // Preserve previously-rendered events on a transient backend
          // failure (Calendar.app wedged, AppleScript timeout, etc).
          // Only flip to "error" when we have NOTHING to show; otherwise
          // keep the live data and surface the issue with a small badge.
          // Use hasEventsRef (not `events` state) to avoid the stale-closure
          // bug where events.length is always 0 inside this [] dep effect.
          setErrorMsg(data.error || "Calendar unavailable");
          if (!hasEventsRef.current) setStatus("error");
          // status stays "live" with stale data otherwise
          return;
        }
        const raw: Record<string, string>[] = data.events || [];
        const mapped: LiveEvent[] = raw
          .map((e, i) => formatEvent(e, i, today0))
          .filter((x): x is LiveEvent => x !== null)
          .sort((a, b) => a.start.getTime() - b.start.getTime());

        const counts: Record<string, number> = {};
        for (const ev of mapped) counts[ev.calendar] = (counts[ev.calendar] || 0) + 1;
        setCalendarCounts(counts);
        setEvents(mapped);
        hasEventsRef.current = mapped.length > 0;
        setStatus("live");
        setErrorMsg("");
      } catch (err) {
        // Same rule: don't wipe events on transient network errors.
        setErrorMsg(err instanceof Error ? err.message : "network error");
        if (!hasEventsRef.current) setStatus("error");
      }
    };
    load();
    // Calendar AppleScript is heavy; backend caches 90s but polling more
    // often than 5min just heats the cache for no payoff.
    const id = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      load();
    }, 300_000);
    return () => clearInterval(id);
  }, []);

  const filteredEvents = useMemo(() => {
    if (selectedCal === "All") return events;
    return events.filter((e) => (e.calendar || "Other") === selectedCal);
  }, [events, selectedCal]);

  const groups = useMemo(() => {
    const t0 = new Date();
    t0.setHours(0, 0, 0, 0);
    return groupByDay(filteredEvents, t0);
  }, [filteredEvents]);

  // On first successful render, scroll the "now" anchor into view so the user
  // sees the next upcoming event instead of the top of a 30-day list.
  useEffect(() => {
    if (hasScrolledRef.current) return;
    if (status !== "live" || events.length === 0) return;
    const node = nowAnchorRef.current;
    if (!node) return;
    // rAF so the list has laid out.
    requestAnimationFrame(() => {
      node.scrollIntoView({ block: "start", behavior: "auto" });
      hasScrolledRef.current = true;
    });
  }, [status, events.length, groups]);

  const isWide = containerWidth > 500;
  // Landscape mode: widget is wider than tall (pulled to a horizontal slot).
  // Threshold 1.4 catches most wide-short configurations without false-positives
  // on squarish widgets. Requires a minimum width so tiny containers don't flip.
  const isLandscape =
    containerWidth > 400 &&
    containerHeight > 0 &&
    containerWidth / containerHeight > 1.4;
  const isLive = status === "live";

  // Index of the first group that is today-or-later (the "now" line).
  const nowIdx = useMemo(() => {
    const today0 = new Date();
    today0.setHours(0, 0, 0, 0);
    const t = today0.getTime();
    return groups.findIndex((g) => g.date.getTime() >= t);
  }, [groups]);

  const calendarNames = Object.keys(calendarCounts).sort();

  // ESC closes the inline event modal
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpandedEvent(null);
    };
    document.addEventListener("keydown", handleEsc);
    return () => document.removeEventListener("keydown", handleEsc);
  }, []);

  return (
    <Card className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card hover:border-foreground/15 transition-colors">
      <CardHeader className="p-5 pb-3">
        <CardTitle className="text-[13px] font-semibold tracking-[-0.02em] text-muted-foreground flex items-center gap-2 flex-wrap">
          Upcoming
          {isLive ? (
            <>
              <span className="h-1.5 w-1.5 rounded-full inline-block" style={{ background: "var(--status-live)" }} title="Live" />
              <span className="sr-only">live</span>
              <span className="text-[10px] normal-case font-normal text-muted-foreground/60">
                · {events.length} events · next 30 days
              </span>
              {calendarNames.length > 0 && (
                <span className="flex gap-1 ml-1 flex-wrap">
                  <button
                    type="button"
                    onClick={() => setSelectedCal("All")}
                    className={
                      "text-[9px] normal-case font-normal px-1.5 py-0.5 rounded ring-1 transition-colors " +
                      (selectedCal === "All"
                        ? "ring-white/40 bg-foreground/15 text-foreground"
                        : "ring-white/10 bg-foreground/[0.02] text-muted-foreground hover:bg-foreground/5")
                    }
                  >
                    All {events.length}
                  </button>
                  {calendarNames.map((n) => {
                    const active = selectedCal === n;
                    return (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setSelectedCal(active ? "All" : n)}
                        title={`${calendarCounts[n]} event${calendarCounts[n] === 1 ? "" : "s"} from ${n} (click to ${active ? "show all" : "filter"})`}
                        className={
                          "text-[9px] normal-case font-normal px-1.5 py-0.5 rounded ring-1 transition-colors " +
                          (active
                            ? `${calendarColor(n)} ring-white/40`
                            : `${calendarColor(n)} opacity-60 hover:opacity-100`)
                        }
                      >
                        {n} {calendarCounts[n]}
                      </button>
                    );
                  })}
                </span>
              )}
            </>
          ) : status === "loading" ? (
            <>
              <span className="text-[10px] normal-case font-normal text-muted-foreground/50">loading…</span>
              <span className="sr-only">loading</span>
            </>
          ) : (
            <>
              <span
                className="h-1.5 w-1.5 rounded-full inline-block"
                style={{ background: "var(--status-warn)" }}
                title={errorMsg}
              />
              <span className="sr-only">error</span>
            </>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent ref={contentRef} className="flex-1 min-h-0 p-5 pt-0">
        {status === "loading" && (
          <div className="space-y-3 pt-1" aria-hidden>
            {[0, 1, 2].map((g) => (
              <div key={g} className="space-y-1.5">
                <Skeleton className="h-3 w-20" />
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex gap-2 px-2 py-1.5">
                    <Skeleton className="h-3 w-12 shrink-0" />
                    <Skeleton className="h-3 flex-1" />
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
        {status === "error" && (
          <ErrorState
            message={
              errorMsg.toLowerCase().includes("timeout")
                ? "Calendar fetch timed out"
                : errorMsg.toLowerCase().includes("network") || errorMsg.toLowerCase().includes("offline")
                ? "Backend unreachable"
                : errorMsg || "Calendar unavailable"
            }
            onRetry={() => {
              setStatus("loading");
              setErrorMsg("");
            }}
          />
        )}
        {isLive && events.length === 0 && (
          <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
            No upcoming events in the next 30 days.
          </div>
        )}
        {isLive && events.length > 0 && isLandscape && (
          <WeekGrid groups={groups} nowIdx={nowIdx} onExpandEvent={setExpandedEvent} />
        )}
        {isLive && events.length > 0 && !isLandscape && (
          <ScrollArea className="h-full">
            <div className="space-y-4 pr-1">
              {groups.map((g, gi) => (
                <div key={g.key} className="space-y-1.5">
                  {/* Sticky-ish day header */}
                  <div
                    ref={gi === nowIdx ? nowAnchorRef : undefined}
                    className="flex items-baseline gap-2 sticky top-0 bg-card/95 backdrop-blur-sm z-10 pt-0.5 pb-1 border-b border-foreground/5"
                  >
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-foreground/80">
                      {g.label}
                    </span>
                    <span className="text-[10px] text-muted-foreground/60">
                      {g.date.toLocaleDateString([], { month: "short", day: "numeric" })}
                    </span>
                    <span className="text-[10px] text-muted-foreground/40 ml-auto">
                      {g.events.length} event{g.events.length === 1 ? "" : "s"}
                    </span>
                  </div>

                  {/* Events for this day */}
                  <div
                    className={isWide ? "grid gap-2" : "space-y-1"}
                    style={
                      isWide
                        ? { gridTemplateColumns: `repeat(auto-fill, minmax(220px, 1fr))` }
                        : undefined
                    }
                  >
                    {g.events.map((event) => (
                      <EventRow key={event.bucketKey} event={event} wide={isWide} onExpand={setExpandedEvent} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>

      {/* Cmd+click / Shift+click inline event detail modal */}
      {expandedEvent && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Event: ${expandedEvent.title}`}
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center animate-in fade-in duration-150"
          onClick={(e) => { if (e.target === e.currentTarget) setExpandedEvent(null); }}
        >
          <div
            className="bg-card border border-foreground/10 rounded-xl p-5 w-80 max-w-[90vw] space-y-2 animate-in fade-in zoom-in-95 duration-200 ease-out"
            style={{ boxShadow: "var(--shadow-card-hover)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <p className="font-semibold text-sm text-foreground leading-snug">{expandedEvent.title}</p>
            {expandedEvent.calendar && (
              <p className="text-[11px] text-muted-foreground/70">{expandedEvent.calendar}</p>
            )}
            <p className="text-[11px] text-muted-foreground">{expandedEvent.startLabel}</p>
            {expandedEvent.location && (
              <p className="text-[11px] text-muted-foreground truncate">{expandedEvent.location}</p>
            )}
            <button
              className="mt-1 text-[11px] text-muted-foreground/50 hover:text-muted-foreground transition-colors"
              onClick={() => setExpandedEvent(null)}
            >
              Close (ESC)
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}

// ── Horizontal week-grid (landscape mode) ────────────────────────────────────
// Shows the next 7 days as side-by-side columns. Each column has a day header
// and lists up to ~4 events; overflow is scrollable per-column.

const WEEK_DAYS = 7;

function WeekGrid({
  groups,
  nowIdx,
  onExpandEvent,
}: {
  groups: DayGroup[];
  nowIdx: number;
  onExpandEvent?: (ev: BucketedEvent) => void;
}) {
  // Take the slice of groups that are today-or-later, up to 7 days.
  const startSlice = nowIdx >= 0 ? nowIdx : 0;
  const slice = groups.slice(startSlice, startSlice + WEEK_DAYS);

  // If we have fewer than 7 days with events, pad with empty day buckets
  // so the grid always shows 7 columns.
  const today0 = new Date();
  today0.setHours(0, 0, 0, 0);

  const columns: DayGroup[] = [];
  for (let i = 0; i < WEEK_DAYS; i++) {
    const target = new Date(today0);
    target.setDate(target.getDate() + i);
    const targetKey = dayKey(target);
    const found = slice.find((g) => g.key === targetKey);
    if (found) {
      columns.push(found);
    } else {
      columns.push({
        key: targetKey,
        label: dayLabel(target, today0),
        date: target,
        events: [],
      });
    }
  }

  return (
    <div className="h-full grid gap-1" style={{ gridTemplateColumns: `repeat(${WEEK_DAYS}, 1fr)` }}>
      {columns.map((col, ci) => {
        const isToday = ci === 0;
        return (
          <div key={col.key} className="flex flex-col min-h-0 overflow-hidden">
            {/* Day header */}
            <div
              className={`shrink-0 px-1 py-0.5 mb-1 border-b text-center ${
                isToday ? "border-emerald-500/40" : "border-foreground/5"
              }`}
            >
              <div
                className={`text-[10px] font-semibold uppercase tracking-wide ${
                  isToday ? "text-emerald-400" : "text-foreground/70"
                }`}
              >
                {col.label}
              </div>
              <div className="text-[9px] text-muted-foreground/50">
                {col.date.toLocaleDateString([], { month: "short", day: "numeric" })}
              </div>
            </div>
            {/* Events */}
            <div className="flex-1 min-h-0 overflow-y-auto space-y-0.5 pr-0.5">
              {col.events.length === 0 ? (
                <div className="text-[9px] text-muted-foreground/30 text-center pt-2">—</div>
              ) : (
                col.events.map((ev) => (
                  <WeekEventChip key={ev.bucketKey} event={ev} onExpand={onExpandEvent} />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function WeekEventChip({
  event,
  onExpand,
}: {
  event: BucketedEvent;
  onExpand?: (ev: BucketedEvent) => void;
}) {
  const typeCls = typeColors[event.type];
  const timeLabel = event.ongoing ? "all-day" : event.startLabel;

  const handleClick = async (e: React.MouseEvent) => {
    if (e.metaKey || e.shiftKey) {
      onExpand?.(event);
      return;
    }
    try {
      await openInApp({
        app: "outlook-calendar",
        ref: event.id,
        context: { start: event.start.toISOString() },
      });
    } catch {
      // fire-and-forget
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onExpand?.(event); } }}
      className={`cursor-pointer rounded px-1.5 py-1 text-[10px] leading-snug hover:bg-foreground/10 transition-colors ${typeCls} bg-transparent`}
    >
      <div className="font-medium truncate">{event.title}</div>
      <div className="text-[9px] opacity-70 truncate">{timeLabel}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function EventRow({
  event,
  wide,
  onExpand,
}: {
  event: BucketedEvent;
  wide: boolean;
  onExpand?: (ev: BucketedEvent) => void;
}) {
  const calCls = calendarColor(event.calendar);
  const typeCls = typeColors[event.type];

  // Multi-day annotation. Examples: "all-day · day 3 of 5", "all-day".
  const spanLabel =
    event.dayIndex && event.dayTotal && event.dayTotal > 1
      ? `day ${event.dayIndex} of ${event.dayTotal}`
      : "";
  // For ongoing days within a multi-day event, prefer "all-day" over a
  // start time that doesn't apply to this particular day.
  const timeLabel = event.ongoing ? "all-day" : event.startLabel;

  const handleClick = async (e: React.MouseEvent) => {
    if (e.metaKey || e.shiftKey) {
      onExpand?.(event);
      return;
    }
    // Per HIPAA boundary: do not log event title or sensitive data
    try {
      await openInApp({
        app: "outlook-calendar",
        ref: event.id,
        context: { start: event.start.toISOString() },
      });
    } catch (error) {
      // Fire-and-forget; error already logged in openInApp
    }
  };

  if (wide) {
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={handleClick}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onExpand?.(event); } }}
        className="cursor-pointer rounded-lg border border-foreground/5 bg-foreground/[0.02] p-3 hover:bg-foreground/10 transition-colors"
      >
        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
          <Badge className={`${typeCls} border-none text-[10px] capitalize`}>
            {event.type}
          </Badge>
          {event.calendar && (
            <span className={`text-[9px] px-1.5 py-0.5 rounded ring-1 ${calCls}`}>
              {event.calendar}
            </span>
          )}
          <span className="font-mono text-[11px] text-muted-foreground ml-auto">
            {timeLabel}
          </span>
        </div>
        <p className="text-sm font-medium leading-snug">{event.title}</p>
        {spanLabel && (
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mt-0.5">
            {spanLabel}
          </p>
        )}
        {event.location && (
          <p className="text-xs text-muted-foreground mt-1 truncate">{cleanLocation(event.location)}</p>
        )}
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onExpand?.(event); } }}
      className="cursor-pointer flex items-start gap-3 rounded-lg px-3 py-2 hover:bg-foreground/10 transition-colors"
    >
      <div className="min-w-[68px] pt-0.5 font-mono text-xs text-muted-foreground">
        {timeLabel}
      </div>
      <div className="flex-1 space-y-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium truncate">{event.title}</span>
          {spanLabel && (
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 shrink-0">
              · {spanLabel}
            </span>
          )}
          <Badge
            className={`${typeCls} border-none text-[10px] capitalize shrink-0`}
          >
            {event.type}
          </Badge>
          {event.calendar && (
            <span className={`text-[9px] px-1.5 py-0.5 rounded ring-1 shrink-0 ${calCls}`}>
              {event.calendar}
            </span>
          )}
        </div>
        {event.location && (
          <p className="text-xs text-muted-foreground truncate">{cleanLocation(event.location)}</p>
        )}
      </div>
    </div>
  );
}
