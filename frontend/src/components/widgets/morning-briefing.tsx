"use client";

import { useEffect, useState } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { fetchBriefing } from "@/lib/api";
import { jarvisConfig } from "@/lib/jarvis-config";

type EventItem = { time: string; title: string; location: string };
type NextEvent = {
  in_minutes: number | null;
  title: string;
  location: string;
  time: string;
} | null;
type FolderRow = { name: string; unread: number };
type NowPlaying = { title: string; artist: string } | null;
type NBME = {
  latest_score?: number | null;
  latest_pct?: number | null;
  delta?: number | null;
  days_until_next?: number | null;
  next_exam?: string | null;
} | null;

type BriefingData = {
  greeting: string;
  now: string;
  anki: { due: number; streak_days?: number } | null;
  events_today: EventItem[] | null;
  next_event: NextEvent;
  unread_mail: number | null;
  mail_folders: FolderRow[] | null;
  unread_messages: number | null;
  now_playing: NowPlaying;
  nbme: NBME;
  errors: string[];
};

function trim(line: string, max = 60): string {
  return line.length <= max ? line : line.slice(0, max - 1) + "…";
}

/** True when the response has at least one renderable data point. */
function hasAnyData(d: BriefingData): boolean {
  return (
    !!d.anki ||
    !!d.next_event ||
    (d.events_today?.length ?? 0) > 0 ||
    d.unread_mail != null ||
    (d.mail_folders?.length ?? 0) > 0 ||
    d.unread_messages != null ||
    !!d.now_playing ||
    !!d.nbme
  );
}

export function MorningBriefing() {
  const [data, setData] = useState<BriefingData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetchBriefing()
        .then((d: BriefingData) => {
          if (!cancelled) setData(d);
        })
        .catch(() => {
          // Keep the last-good payload on a transient refresh failure.
          // Previous code did `if (!cancelled && !data) setData(null)`, but
          // `data` was closure-captured from the initial render (always null)
          // so EVERY failed refresh wiped the widget. The 60s polling will
          // recover on the next successful fetch.
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };
    load();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 60_000);
    const onVis = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const firstName = jarvisConfig.firstName;
  const rawGreeting = data?.greeting ?? "Hello";
  // "Good afternoon, <name>." — append name if configured
  const greeting = firstName
    ? `${rawGreeting}, ${firstName}`
    : rawGreeting;

  const next = data?.next_event;
  const events = data?.events_today ?? [];
  const anki = data?.anki;
  const folders = data?.mail_folders ?? [];
  const unreadMail = data?.unread_mail;
  const unreadMsg = data?.unread_messages;
  const np = data?.now_playing;
  const nbme = data?.nbme;
  const errors = data?.errors ?? [];

  // ── Top highlight ─────────────────────────────────────────────────────────
  let highlight = "";
  if (next && typeof next.in_minutes === "number" && next.in_minutes <= 30) {
    // Urgent: event in <30 min — show with stronger signal
    const mins = next.in_minutes;
    const rel = mins <= 0 ? "now" : `in ${mins} min`;
    const where = next.location ? ` @ ${next.location}` : "";
    highlight = `${next.title}${where} — ${rel}`;
  } else if (next && typeof next.in_minutes === "number" && next.in_minutes <= 120) {
    const mins = next.in_minutes;
    const rel =
      mins < 60
        ? `in ${mins} min`
        : `in ${Math.floor(mins / 60)}h ${mins % 60}m`;
    highlight = `${next.title} ${rel}`;
  } else if (next?.title) {
    highlight = `next: ${next.time} — ${next.title}`;
  } else if (events.length > 0) {
    highlight = `${events.length} event${events.length === 1 ? "" : "s"} today`;
  } else if (data && hasAnyData(data)) {
    // Summarise whatever is available
    const parts: string[] = [];
    if (anki?.due != null && anki.due > 0) parts.push(`${anki.due} due`);
    if (typeof unreadMsg === "number" && unreadMsg > 0)
      parts.push(`${unreadMsg} message${unreadMsg === 1 ? "" : "s"}`);
    const mail =
      unreadMail ??
      (folders.reduce((s, f) => s + f.unread, 0) || null);
    if (mail && mail > 0) parts.push(`${mail} unread`);
    highlight = parts.length > 0 ? parts.join(" · ") : "you're all caught up";
  } else if (!loading) {
    highlight = "you're all caught up";
  }

  // ── Detail lines ──────────────────────────────────────────────────────────
  const lines: { tag: string; text: string; urgent?: boolean }[] = [];

  if (next?.title) {
    const where = next.location ? ` @ ${next.location}` : "";
    const inMin =
      typeof next.in_minutes === "number" ? next.in_minutes : null;
    const when =
      inMin != null && inMin <= 120
        ? inMin <= 0
          ? "now"
          : `in ${inMin}m`
        : next.time;
    lines.push({
      tag: "EVENT",
      text: trim(`${when} — ${next.title}${where}`),
      urgent: inMin != null && inMin <= 30,
    });
  } else if (events.length > 0) {
    const e = events[0];
    lines.push({
      tag: "EVENT",
      text: trim(`${e.time} — ${e.title}${e.location ? ` @ ${e.location}` : ""}`),
    });
  }

  if (folders.length > 0) {
    const top = folders.slice(0, 3).map((f) => `${f.name}: ${f.unread}`).join(", ");
    lines.push({ tag: "MAIL", text: trim(top) });
  } else if (typeof unreadMail === "number" && unreadMail > 0) {
    lines.push({ tag: "MAIL", text: `${unreadMail} unread` });
  }

  if (typeof unreadMsg === "number" && unreadMsg > 0) {
    lines.push({
      tag: "MSG",
      text: `${unreadMsg} message${unreadMsg === 1 ? "" : "s"} waiting`,
    });
  }

  if (anki && anki.due >= 0) {
    const streak = anki.streak_days ?? 0;
    const streakBit = streak > 0 ? ` · ${streak}-day streak` : "";
    if (anki.due > 0 || streak > 0) {
      lines.push({
        tag: "ANKI",
        text: trim(`${anki.due} due${streakBit}`),
      });
    }
  }

  if (nbme && (nbme.latest_score != null || nbme.days_until_next != null)) {
    const parts: string[] = [];
    if (nbme.latest_score != null) {
      const pct = nbme.latest_pct != null ? ` (${nbme.latest_pct}%ile)` : "";
      const delta =
        nbme.delta != null
          ? ` · ${nbme.delta >= 0 ? "+" : ""}${nbme.delta}`
          : "";
      parts.push(`last ${nbme.latest_score}${pct}${delta}`);
    }
    if (nbme.days_until_next != null) {
      parts.push(`${nbme.days_until_next}d to ${nbme.next_exam || "next NBME"}`);
    }
    lines.push({ tag: "NBME", text: trim(parts.join(" · ")) });
  }

  if (np?.title) {
    lines.push({
      tag: "NOW",
      text: trim(`${np.title}${np.artist ? ` — ${np.artist}` : ""}`),
    });
  }

  const visibleLines = lines.slice(0, 6);
  const partialWithErrors =
    !loading && errors.length > 0 && (data ? hasAnyData(data) : false);

  return (
    <Card className="group relative col-span-full overflow-hidden rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <div className="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-emerald-400 via-blue-500 to-emerald-400 bg-[length:100%_200%] animate-[gradient-y_3s_ease-in-out_infinite]" />

      <CardHeader className="pl-6 p-5 pb-2">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 font-bold text-lg">
            J
          </div>
          <div>
            <CardTitle className="text-xl font-semibold tracking-tight">
              {greeting}.
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              {loading ? "Loading your briefing…" : highlight}
            </p>
          </div>
        </div>
      </CardHeader>

      <CardContent className="pl-6 p-5 pt-3">
        {!loading && visibleLines.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No data yet — make sure Anki, Outlook, and Calendar.app are open.
          </p>
        ) : (
          <>
            <ul className="space-y-1.5">
              {visibleLines.map((l, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-sm font-mono"
                >
                  <span
                    className={`mt-0.5 inline-block min-w-[3rem] rounded px-1 py-0 text-[9px] uppercase tracking-wider ${
                      l.urgent
                        ? "bg-amber-500/15 text-amber-400"
                        : "bg-white/5 text-muted-foreground/60"
                    }`}
                  >
                    {l.tag}
                  </span>
                  <span className={l.urgent ? "text-foreground font-medium" : "text-foreground/85"}>
                    {l.text}
                  </span>
                </li>
              ))}
            </ul>
            {partialWithErrors && (
              <p className="mt-2 text-[10px] text-muted-foreground/50">
                some sources are warming up — refresh in 30s
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
