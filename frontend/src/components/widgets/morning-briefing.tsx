"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { CheckCircle2, ListTodo, CalendarDays, Mail, Bell, AlertTriangle } from "lucide-react";
import { fetchBriefing, BACKEND, addTodoReminder, completeTodoReminder, type BriefingTodo } from "@/lib/api";
import { jarvisConfig } from "@/lib/jarvis-config";
import { WidgetWrapper, type WidgetStatus } from "@/components/layout/widget-wrapper";
import Skeleton from "@/components/ui/skeleton";
import { EmptyState } from "@/components/widgets/empty-state";
import { ErrorState } from "@/components/widgets/error-state";
import {
  getInitialDensity,
  subscribeDensityChange,
  type Density,
} from "@/lib/density-store";

type EventItem = { time: string; title: string; location: string };
type ImportantEmail = {
  id?: string;
  subject: string;
  from: string;
  folder: string | null;
  score: number;
  score_reason?: string;
  date?: string | null;
};
// BriefingTodo is imported from lib/api — it carries the optional
// `source` ("manual" | "auto") and `source_email_id` fields used to
// render the <Mail> chip for auto-extracted tasks.

type BriefingData = {
  greeting: string;
  now: string;
  important_unread?: ImportantEmail[];
  todos?: BriefingTodo[];
  events_today: EventItem[] | null;
  errors: string[];
};

export function MorningBriefing() {
  const [data, setData] = useState<BriefingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | undefined>(undefined);
  const [widgetStatus, setWidgetStatus] = useState<WidgetStatus | undefined>(undefined);

  const [todos, setTodos] = useState<BriefingTodo[]>([]);
  const [newTodoText, setNewTodoText] = useState("");
  const [todoSubmitting, setTodoSubmitting] = useState(false);

  // Density state for compact gap reduction (F10)
  const [density, setDensityState] = useState<Density>("comfortable");
  useEffect(() => {
    setDensityState(getInitialDensity());
    return subscribeDensityChange((d) => setDensityState(d));
  }, []);

  // D2: mirror widgetStatus into a ref so the freshness effect can read the
  // current value without listing it as a dep (which caused restart loops).
  const statusRef = useRef(widgetStatus);
  useEffect(() => {
    statusRef.current = widgetStatus;
  }, [widgetStatus]);

  // D1: load accepts an AbortSignal so stale in-flight responses are ignored.
  const load = useCallback((signal?: AbortSignal) => {
    fetchBriefing()
      .then((d: BriefingData) => {
        if (signal?.aborted) return;
        setData(d);
        setTodos(d.todos ?? []);
        const now = Date.now();
        setLastUpdated(now);
        setWidgetStatus("fresh");
      })
      .catch(() => {
        if (signal?.aborted) return;
        setLoadFailed(true);
        setWidgetStatus("error");
      })
      .finally(() => {
        if (signal?.aborted) return;
        setLoading(false);
      });
  }, []);

  // D2: dep array is [lastUpdated] only; current status read via statusRef.
  useEffect(() => {
    if (!lastUpdated || statusRef.current === "error") return;
    const check = () => {
      const age = Date.now() - lastUpdated;
      setWidgetStatus(age < 5 * 60 * 1000 ? "fresh" : "stale");
    };
    check();
    const id = setInterval(check, 60_000);
    return () => clearInterval(id);
  }, [lastUpdated]);

  // D1: AbortController replaces the dead `cancelled` flag pattern.
  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    const id = setInterval(() => {
      if (document.visibilityState === "visible") load(ac.signal);
    }, 60_000);
    const onVis = () => {
      if (document.visibilityState === "visible") load(ac.signal);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      ac.abort();
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [load]);

  const addTodo = useCallback(async () => {
    const text = newTodoText.trim();
    if (!text || todoSubmitting) return;
    setTodoSubmitting(true);

    // Optimistic append with a temp id so the row appears instantly.
    // The real Reminders.app id arrives in the response; we patch the list
    // after 1 s via a full briefing refresh so the ids stay consistent.
    const tempId = `temp_${Date.now()}`;
    const optimistic: BriefingTodo = {
      id: tempId,
      text,
      done: false,
      due: null,
      created_at: new Date().toISOString(),
      source: "reminders",
    };
    setTodos((prev) => [...prev, optimistic]);
    setNewTodoText("");

    try {
      await addTodoReminder(text);
      // Refresh after 1 s so the Reminders.app-assigned id replaces the
      // temp id and bidirectional sync state is accurate.
      setTimeout(() => load(), 1000);
    } catch {
      // Rollback the optimistic item on failure.
      setTodos((prev) => prev.filter((t) => t.id !== tempId));
    } finally {
      setTodoSubmitting(false);
    }
  }, [newTodoText, todoSubmitting, load]);

  const toggleTodo = useCallback(async (todo: BriefingTodo) => {
    // Auto-extracted todos are ephemeral — no server-side storage to PATCH.
    // Optimistic local toggle is enough for the session.
    if (todo.id.startsWith("auto_")) {
      setTodos((prev) =>
        prev.map((t) => (t.id === todo.id ? { ...t, done: !t.done } : t)),
      );
      return;
    }

    // Reminders-backed todos: optimistically remove from the visible list
    // (completing a Reminders item means it's done — no "undo" pattern here),
    // then fire completeTodoReminder. The id used by the backend is the
    // Reminders.app item id, which lives in reminders_id when set by the
    // backend; fall back to id for backwards compat.
    if (todo.source === "reminders") {
      setTodos((prev) => prev.filter((t) => t.id !== todo.id));
      const remId = todo.reminders_id ?? todo.id;
      await completeTodoReminder(remId);
      return;
    }

    // Manual todos: toggle optimistically then PATCH the backend store.
    setTodos((prev) =>
      prev.map((t) => (t.id === todo.id ? { ...t, done: !t.done } : t)),
    );
    try {
      await fetch(`${BACKEND}/widgets/todos/${todo.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ done: !todo.done }),
      });
      load();
    } catch {
      setTodos((prev) =>
        prev.map((t) => (t.id === todo.id ? { ...t, done: todo.done } : t)),
      );
    }
  }, [load]);

  const deleteTodo = useCallback(async (id: string) => {
    setTodos((prev) => prev.filter((t) => t.id !== id));
    // Auto-extracted todos (id starts with "auto_") are ephemeral — they live
    // only in the briefing response and have no server-side storage entry.
    // Skip the DELETE call to avoid a noisy 404.
    if (id.startsWith("auto_")) return;
    try {
      await fetch(`${BACKEND}/widgets/todos/${id}`, { method: "DELETE" });
    } catch {
      load();
    }
  }, [load]);

  const firstName = jarvisConfig.firstName;
  const rawGreeting = data?.greeting ?? "Hello";
  const greeting = firstName ? `${rawGreeting}, ${firstName}` : rawGreeting;

  // Returns true when any error string from the backend contains `kind`.
  // WHY substring match instead of equality: backend error strings look like
  // "important_unread: timeout" — matching the key prefix covers all variants.
  const hasError = (kind: string) =>
    (data?.errors ?? []).some((e) => e.includes(kind));

  const emailError = hasError("important_unread");
  const calendarError = hasError("events_today") || hasError("calendar");
  // Any error key that isn't handled by a section-level banner gets collected
  // here for the generic top-of-widget pill.
  const genericErrors = (data?.errors ?? []).filter(
    (e) => !e.includes("important_unread") && !e.includes("events_today") && !e.includes("calendar"),
  );

  const importantEmails = (data?.important_unread ?? []).filter(
    (e) => e.score > 0,
  );
  const events = data?.events_today ?? [];
  const pendingTodos = todos.filter((t) => !t.done);

  const headlineParts: string[] = [];
  if (importantEmails.length > 0) {
    headlineParts.push(
      `${importantEmails.length} important email${importantEmails.length === 1 ? "" : "s"}`,
    );
  }
  if (pendingTodos.length > 0) {
    headlineParts.push(
      `${pendingTodos.length} todo${pendingTodos.length === 1 ? "" : "s"}`,
    );
  }
  if (events.length > 0) {
    headlineParts.push(
      `${events.length} event${events.length === 1 ? "" : "s"}`,
    );
  }
  // WHY: suppress "all caught up" when there are backend errors — claiming
  // "caught up" while email/calendar data failed to load is actively misleading.
  const anyError = (data?.errors ?? []).length > 0;
  const headline =
    !loading && headlineParts.length === 0
      ? anyError ? "some data couldn't load" : "you're all caught up"
      : headlineParts.join(" · ");

  if (loading && !data) {
    return (
      <WidgetWrapper>
        <Card
          className="group relative col-span-full h-full flex flex-col overflow-hidden rounded-xl border border-foreground/10 bg-card"
          style={{ padding: "var(--widget-density-pad)" }}
        >
          <div className="flex flex-col gap-3 p-2">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-16 w-full" />
          </div>
        </Card>
      </WidgetWrapper>
    );
  }

  // F8: show ErrorState when all fetches have failed and there is no cached data.
  if (loadFailed && !data) {
    return (
      <WidgetWrapper status={widgetStatus} lastUpdated={lastUpdated}>
        <Card
          className="group relative col-span-full h-full flex flex-col overflow-hidden rounded-xl border border-foreground/10 bg-card"
          style={{ padding: "var(--widget-density-pad)" }}
        >
          <ErrorState message="Couldn't load briefing" onRetry={() => load()} />
        </Card>
      </WidgetWrapper>
    );
  }

  return (
    <WidgetWrapper status={widgetStatus} lastUpdated={lastUpdated}>
    {/* F4: fade loaded content in instead of hard-swapping */}
    <Card
      className="animate-in fade-in duration-200 group relative col-span-full h-full flex flex-col overflow-hidden rounded-xl border border-foreground/10 bg-card hover:border-foreground/15 transition-colors"
      style={{ padding: "var(--widget-density-pad)" }}
    >
      <div className="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-emerald-400 via-blue-500 to-emerald-400 bg-[length:100%_200%] animate-[gradient-y_3s_ease-in-out_infinite]" />

      <CardHeader className="pl-6 p-5 pb-2 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 font-bold text-lg">
            J
          </div>
          <div>
            <CardTitle className="text-xl font-semibold tracking-tight">
              {greeting}.
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground flex items-center gap-1.5">
              {loading ? "Loading your briefing…" : headline}
              {!loading && loadFailed && !data && (
                <span
                  className="h-1.5 w-1.5 rounded-full inline-block flex-shrink-0"
                  style={{ backgroundColor: "var(--status-warn)" }}
                  title="Backend unreachable"
                />
              )}
            </p>
          </div>
        </div>
      </CardHeader>

      {/* no-drag: all interactive content (todo input, checkboxes, buttons)
          lives inside this scrollable CardContent. Marking the container
          prevents a slow-hold on any child from initiating a grid drag. */}
      {/* F9: scroll fade mask so content blends out before the edge */}
      <CardContent
        className={`no-drag pl-6 p-5 pt-3 flex-1 min-h-0 flex flex-col overflow-y-auto ${density === "compact" ? "gap-2" : "gap-4"}`}
        style={{
          WebkitMaskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)",
          maskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)",
        }}
      >
        {/* Generic error pill — shown for any backend error that doesn't have
            a section-level handler. Clicking retries the full briefing load. */}
        {!loading && genericErrors.length > 0 && (
          <button
            onClick={() => load()}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] transition-opacity hover:opacity-80"
            style={{ backgroundColor: "var(--status-warn-soft)", color: "var(--status-warn)" }}
          >
            <AlertTriangle className="h-3 w-3 flex-shrink-0" />
            Some data couldn&apos;t load · retry
          </button>
        )}

        {/* Section 1 — Important unread emails */}
        <section>
          <div className="flex items-center justify-between mb-1.5">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Important Email
            </h3>
            <span className="text-[10px] text-muted-foreground/60">
              {importantEmails.length} unread
            </span>
          </div>
          {/* WHY: when the backend signals an important_unread timeout, we show
              a warning banner instead of the "all caught up" empty state — the
              empty state would be a lie (we simply don't know). */}
          {emailError ? (
            <div
              className="flex items-center gap-2 px-3 py-2 rounded"
              style={{ backgroundColor: "var(--status-warn-soft)", color: "var(--status-warn)" }}
            >
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              <span className="text-xs">Couldn&apos;t load important emails (fetch timed out)</span>
            </div>
          ) : importantEmails.length === 0 ? (
            loading ? (
              <p className="text-xs text-muted-foreground/60 italic">checking…</p>
            ) : (
              <EmptyState icon={CheckCircle2} title="You're all caught up" />
            )
          ) : (
            <ul className="space-y-1">
              {importantEmails.slice(0, 4).map((e, i) => (
                <li
                  key={e.id ?? i}
                  className="flex items-start gap-2 text-xs"
                >
                  {/* bg-blue-400 intentional: iMessage/inbox-tinted indicator.
                      No semantic CSS var maps to this exact inbox-blue hue. */}
                  <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-400" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1 font-medium text-foreground/90">
                      <span className="truncate">{e.subject || "(no subject)"}</span>
                      {/* score_reason tooltip — title attribute is zero-dep and
                          renders fine in all browsers; no custom component needed */}
                      {e.score_reason && (
                        <span
                          className="flex-shrink-0 text-[9px] text-muted-foreground/50 cursor-default select-none"
                          title={e.score_reason}
                        >
                          (?)
                        </span>
                      )}
                    </div>
                    <div className="truncate text-[10px] text-muted-foreground/60">
                      {e.from || "—"}
                      {e.folder && e.folder !== "Inbox" ? ` · ${e.folder}` : ""}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Section 2 — Tasks list */}
        <section>
          <div className="flex items-center justify-between mb-1.5">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Tasks
            </h3>
            <span className="text-[10px] text-muted-foreground/60">
              {pendingTodos.length} pending
            </span>
          </div>
          {pendingTodos.length === 0 ? (
            <EmptyState icon={ListTodo} title="Nothing pending" />
          ) : (
            <ul className="space-y-1">
              {pendingTodos.slice(0, 5).map((t) => (
                <li key={t.id} className="flex items-start gap-2 text-xs group">
                  <button
                    onClick={() => toggleTodo(t)}
                    className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 rounded border border-foreground/20 hover:border-emerald-400 transition-colors"
                    aria-label={`Mark "${t.text}" done`}
                  />
                  <div className="flex-1 min-w-0">
                    <span className="text-foreground/85">{t.text}</span>
                    {/* Source provenance chips — <Bell> for Reminders.app,
                        <Mail> for Haiku-extracted auto tasks. "manual" gets
                        no chip so the common case stays visually clean. */}
                    {t.source === "reminders" && (
                      <span
                        className="ml-1.5 inline-flex items-center gap-0.5 px-1 py-0 rounded text-[9px] bg-orange-500/10 text-orange-400 border border-orange-400/20 align-middle"
                        title="From Reminders.app"
                      >
                        <Bell className="h-2.5 w-2.5 flex-shrink-0" />
                        reminders
                      </span>
                    )}
                    {t.source === "auto" && (
                      <span
                        className="ml-1.5 inline-flex items-center gap-0.5 px-1 py-0 rounded text-[9px] bg-blue-500/10 text-blue-400 border border-blue-400/20 align-middle"
                        title="Auto-extracted from email"
                      >
                        <Mail className="h-2.5 w-2.5 flex-shrink-0" />
                        email
                      </span>
                    )}
                    {t.due && (
                      <span
                        className="ml-2 text-[10px]"
                        style={{ color: "var(--status-warn)" }}
                      >
                        due {t.due}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => deleteTodo(t.id)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground/50 hover:text-red-400 text-[11px]"
                    aria-label="Delete"
                    title="Delete"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void addTodo();
            }}
            className="mt-2 flex items-center gap-1"
          >
            <input
              type="text"
              value={newTodoText}
              onChange={(e) => setNewTodoText(e.target.value)}
              placeholder="Add a todo…"
              disabled={todoSubmitting}
              className="flex-1 text-xs bg-foreground/[0.04] border border-foreground/10 rounded px-2 py-1 placeholder:text-muted-foreground/50 focus:outline-none focus:border-foreground/25"
              maxLength={500}
            />
            <button
              type="submit"
              disabled={!newTodoText.trim() || todoSubmitting}
              className="text-[11px] px-2 py-1 rounded bg-foreground/5 hover:bg-foreground/10 text-foreground/70 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Add
            </button>
          </form>
        </section>

        {/* Section 3 — Today's calendar */}
        <section>
          <div className="flex items-center justify-between mb-1.5">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Today&apos;s Calendar
            </h3>
            <span className="text-[10px] text-muted-foreground/60">
              {events.length} event{events.length === 1 ? "" : "s"}
            </span>
          </div>
          {/* WHY: when the backend signals a calendar fetch failure, show an
              actionable error instead of "No events today" (which would be a
              lie). The "Open Calendar.app" hint lets the user self-serve. */}
          {calendarError ? (
            <div
              className="flex items-center justify-between gap-2 px-3 py-2 rounded"
              style={{ backgroundColor: "var(--status-warn-soft)", color: "var(--status-warn)" }}
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                <span className="text-xs">Calendar fetch failed</span>
              </div>
              <button
                onClick={() => {
                  // WHY open -a Calendar via the backend rather than a deep link:
                  // the frontend is sandboxed in the browser — it cannot spawn
                  // native processes. The backend has shell access.
                  fetch(`${BACKEND}/widgets/open-app`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ app: "Calendar" }),
                  }).catch(() => {});
                }}
                className="text-[10px] underline underline-offset-2 hover:opacity-70 transition-opacity flex-shrink-0"
              >
                Open Calendar.app
              </button>
            </div>
          ) : events.length === 0 ? (
            loading ? (
              <p className="text-xs text-muted-foreground/60 italic">checking…</p>
            ) : (
              <EmptyState icon={CalendarDays} title="No events today" />
            )
          ) : (
            <ul className="space-y-1">
              {/* D6: key by composite time+title instead of array index */}
              {events.map((e) => (
                <li key={`${e.time}-${e.title}`} className="flex items-start gap-2 text-xs">
                  <span className="mt-0.5 inline-block min-w-[3.5rem] text-[10px] uppercase tracking-wider text-muted-foreground/70 font-mono tabular-nums">
                    {e.time}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="truncate font-medium text-foreground/90">
                      {e.title}
                    </div>
                    {e.location && (
                      <div className="truncate text-[10px] text-muted-foreground/60">
                        @ {e.location}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Spacer keeps content top-aligned */}
        <div className="flex-1" />
      </CardContent>
    </Card>
    </WidgetWrapper>
  );
}
