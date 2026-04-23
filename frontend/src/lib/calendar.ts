// Calendar helpers — multi-day-aware bucketing.
//
// Backend returns events as { title, start, end, location, isAllDay } where
// `start` / `end` are ISO 8601 strings (may or may not carry timezone).
// Multi-day rotations come back as a single event spanning many days; these
// helpers expand them across every overlapping calendar day so the Week view
// shows them on every day (not just the start day — that was the bug).

export interface RawCalendarEvent {
  title: string;
  start: string;
  end: string;
  location?: string;
  isAllDay?: boolean;
  event_id?: string;     // real outlook/calendar event ID
}

export interface BucketedEvent extends RawCalendarEvent {
  id: string;            // real event ID (fallback to composite if missing)
  ongoing?: boolean;     // event started before this day
  continues?: boolean;   // event continues past this day
  dayIndex?: number;     // 1-based day of event when spanning multiple days
  dayTotal?: number;     // total days the event spans
}

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function endOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(23, 59, 59, 999);
  return x;
}

function daysBetween(a: Date, b: Date): number {
  const MS = 24 * 60 * 60 * 1000;
  return Math.round((startOfDay(b).getTime() - startOfDay(a).getTime()) / MS);
}

/** Return events that OVERLAP the given calendar day (local time). */
export function eventsForDay(
  events: RawCalendarEvent[],
  day: Date,
): BucketedEvent[] {
  const dayStart = startOfDay(day);
  const dayEnd = endOfDay(day);

  const out: BucketedEvent[] = [];
  for (let i = 0; i < events.length; i++) {
    const ev = events[i];
    const s = new Date(ev.start);
    const e = new Date(ev.end);
    if (isNaN(s.getTime()) || isNaN(e.getTime())) continue;

    // Overlap test: event ends after day starts AND event starts before day ends.
    if (e <= dayStart || s >= dayEnd) continue;

    const ongoing = s < dayStart;        // started before today
    const continues = e > dayEnd;        // continues past today
    const spansMultipleDays = ongoing || continues;

    let dayIndex: number | undefined;
    let dayTotal: number | undefined;
    if (spansMultipleDays) {
      dayTotal = daysBetween(s, e) + 1;
      dayIndex = daysBetween(s, day) + 1;
    }

    out.push({
      ...ev,
      id: ev.event_id || `${i}-${dayStart.toISOString().slice(0, 10)}`,
      ongoing,
      continues,
      dayIndex,
      dayTotal,
    });
  }

  // Sort: all-day / ongoing first, then by start time.
  out.sort((a, b) => {
    const aAll = a.isAllDay || a.ongoing ? 0 : 1;
    const bAll = b.isAllDay || b.ongoing ? 0 : 1;
    if (aAll !== bAll) return aAll - bAll;
    return new Date(a.start).getTime() - new Date(b.start).getTime();
  });

  return out;
}

/** Group events into N consecutive days starting from `startDay`. */
export function groupByDay(
  events: RawCalendarEvent[],
  startDay: Date,
  numDays: number,
): { day: Date; label: string; events: BucketedEvent[] }[] {
  const result: { day: Date; label: string; events: BucketedEvent[] }[] = [];
  const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  for (let i = 0; i < numDays; i++) {
    const d = new Date(startDay);
    d.setDate(d.getDate() + i);
    result.push({
      day: d,
      label:
        i === 0
          ? "Today"
          : i === 1
          ? "Tomorrow"
          : `${dayNames[d.getDay()]} ${d.getMonth() + 1}/${d.getDate()}`,
      events: eventsForDay(events, d),
    });
  }
  return result;
}

/** Build an ISO range for the next N days starting now (local tz). */
export function rangeForNextDays(days: number): { start: string; end: string } {
  const now = new Date();
  const start = startOfDay(now);
  const end = new Date(start);
  end.setDate(end.getDate() + days);
  return { start: start.toISOString(), end: end.toISOString() };
}

/** Format a time like "8:00 AM" from an ISO string. */
export function formatTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
