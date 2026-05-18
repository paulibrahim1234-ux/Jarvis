"use client";

/**
 * TriageWidget — chief-of-staff 4-tier email + iMessage classifier.
 *
 * Layout (top to bottom):
 *   1. Stale banner (red, expanded by default) — items >48h without reply
 *   2. Action Required cards — sender, subject, excerpt toggle, draft reply + Copy
 *   3. Meeting Info — with optional "missing on calendar" yellow chip
 *   4. Info Only — collapsed by default (FYI / CC'd items)
 *   5. Skip — one-line summary at bottom (N archived: sender list)
 */

import { useState, useCallback, useEffect, useRef } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  Inbox,
  MessageSquare,
  AlertTriangle,
  Copy,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Check,
  Calendar,
  Mail,
  Plus,
  Layers,
  X,
} from "lucide-react";
import { fetchTriage, addTodoReminder } from "@/lib/api";
import type {
  TriageData,
  TriageActionItem,
  TriageMeetingItem,
  TriageInfoItem,
  TriageStaleItem,
} from "@/lib/api";
import { EmptyState } from "@/components/widgets/empty-state";
import { ErrorState } from "@/components/widgets/error-state";
import Skeleton from "@/components/ui/skeleton";

// ── Internal helpers ──────────────────────────────────────────────────────────

/** Copy text to clipboard and briefly show a checkmark. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      // WHY 1.5s: long enough to register visually, short enough to feel snappy.
      timerRef.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard denied — silently ignore; text is still visible to the user.
    }
  }, [text]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <button
      type="button"
      onClick={handleCopy}
      title="Copy draft reply"
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs border border-border hover:bg-[var(--surface-raised)] transition-colors shrink-0"
    >
      {copied ? (
        <Check className="h-3 w-3 text-green-500" aria-hidden />
      ) : (
        <Copy className="h-3 w-3" aria-hidden />
      )}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/**
 * MigrateButton — small "+ Task" button per triage item.
 *
 * Posts the synthesized task title to /widgets/todos/add (which writes to
 * Reminders.app via tools.reminders). The Reminders.app handler dedupes by
 * canonical title key, so re-clicking on a duplicate-looking item is harmless.
 *
 * After success, the parent's onMigrated() removes the item from view this
 * session — a fresh triage poll will exclude it once Reminders.app reports
 * the matching todo back through the briefing payload.
 */
function MigrateButton({
  title,
  onMigrated,
}: {
  title: string;
  onMigrated: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const handle = useCallback(async () => {
    if (busy || done) return;
    setBusy(true);
    try {
      await addTodoReminder(title);
      setDone(true);
      // Brief delay so the user sees the green check, then hide the item.
      setTimeout(onMigrated, 500);
    } catch {
      // Silent fail — user can retry. Avoid a noisy error toast for a soft
      // action; the item simply stays put.
      setBusy(false);
    }
  }, [title, busy, done, onMigrated]);

  return (
    <button
      type="button"
      onClick={handle}
      disabled={busy || done}
      title={done ? "Added to Tasks" : "Add to Tasks"}
      aria-label={done ? "Added to Tasks" : "Add to Tasks"}
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs border border-border hover:bg-[var(--surface-raised)] transition-colors shrink-0 disabled:opacity-60"
    >
      {done ? (
        <Check className="h-3 w-3 text-green-500" aria-hidden />
      ) : (
        <Plus className="h-3 w-3" aria-hidden />
      )}
      {done ? "Added" : "Task"}
    </button>
  );
}

/**
 * ClearButton — dismiss an item from triage for this session without adding it
 * to Tasks. Uses the same markMigrated() mechanism as MigrateButton so the item
 * disappears from view immediately. No backend call is made.
 *
 * WHY session-only: triage is regenerated fresh on each backend poll, so a
 * "cleared" item reappears next time the widget refetches. This is intentional —
 * it gives the user a quick way to declutter the current view without marking
 * anything as permanently done.
 */
function ClearButton({ onClear }: { onClear: () => void }) {
  return (
    <button
      type="button"
      onClick={onClear}
      title="Clear from triage"
      aria-label="Clear from triage"
      className="inline-flex items-center justify-center rounded p-0.5 text-[var(--ink-muted,hsl(var(--muted-foreground)))] hover:bg-[var(--surface-raised)] hover:text-foreground/70 transition-colors shrink-0"
    >
      <X className="h-3 w-3" aria-hidden />
    </button>
  );
}

/** Collapsible section wrapper — used for Info Only and Stale sections. */
function Collapsible({
  label,
  defaultOpen = false,
  children,
}: {
  label: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
        )}
        {label}
      </button>
      {open && <div className="mt-1">{children}</div>}
    </div>
  );
}

/** Small inline chip for channel badges and calendar warnings. */
function Chip({
  children,
  variant = "default",
}: {
  children: React.ReactNode;
  variant?: "default" | "yellow" | "red" | "blue";
}) {
  const colours: Record<string, string> = {
    default: "bg-[var(--surface-raised)] text-muted-foreground",
    yellow:
      "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400 border border-yellow-500/30",
    red: "bg-red-500/15 text-red-700 dark:text-red-400 border border-red-500/30",
    blue: "bg-blue-500/15 text-blue-700 dark:text-blue-400 border border-blue-500/30",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${colours[variant]}`}
    >
      {children}
    </span>
  );
}

// ── Section renderers ─────────────────────────────────────────────────────────

function StaleSection({ items, onMigrate, onClear }: { items: TriageStaleItem[]; onMigrate: (id: string) => void; onClear: (id: string) => void }) {
  if (items.length === 0) return null;
  return (
    <Collapsible
      defaultOpen={true}
      label={
        <span className="flex items-center gap-1.5">
          <AlertTriangle className="h-3.5 w-3.5 text-red-500" aria-hidden />
          <span className="text-red-600 dark:text-red-400">
            {items.length} item{items.length !== 1 ? "s" : ""} &gt;48h without
            reply
          </span>
        </span>
      }
    >
      <div className="space-y-1 pl-5">
        {items.map((item) => {
          const taskTitle = `Follow up with ${item.sender}: ${item.subject_or_thread} (stale ${item.days_stale}d)`;
          return (
            <div key={staleId(item)} className="flex items-start gap-2 text-xs group">
              {item.channel === "imessage" ? (
                <MessageSquare
                  className="h-3 w-3 mt-0.5 shrink-0 text-muted-foreground"
                  aria-hidden
                />
              ) : (
                <Mail
                  className="h-3 w-3 mt-0.5 shrink-0 text-muted-foreground"
                  aria-hidden
                />
              )}
              <span className="text-muted-foreground min-w-0 flex-1">
                <span className="font-medium text-foreground">{item.sender}</span>
                {" — "}
                {item.subject_or_thread}
                <span className="ml-1 text-red-500">({item.days_stale}d)</span>
              </span>
              <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 shrink-0">
                <MigrateButton title={taskTitle} onMigrated={() => onMigrate(staleId(item))} />
                <ClearButton onClear={() => onClear(staleId(item))} />
              </div>
            </div>
          );
        })}
      </div>
    </Collapsible>
  );
}

function ActionCard({ item, onMigrate, onClear }: { item: TriageActionItem; onMigrate: () => void; onClear: () => void }) {
  const [excerptOpen, setExcerptOpen] = useState(false);
  // Synthesize a clear, action-shaped task title — matches how a person would
  // write it themselves on a sticky note ("Reply to X re: Y").
  const taskTitle = `Reply to ${item.sender}: ${item.subject_or_thread}`;

  return (
    <div className="rounded-lg border border-border bg-[var(--surface-raised)] p-3 space-y-2">
      {/* Header row: sender + channel chip + migrate button (top-right) */}
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-semibold truncate">{item.sender}</span>
            <Chip variant={item.channel === "imessage" ? "blue" : "default"}>
              {item.channel === "imessage" ? (
                <>
                  <MessageSquare className="h-2.5 w-2.5" aria-hidden />
                  iMessage
                </>
              ) : (
                <>
                  <Mail className="h-2.5 w-2.5" aria-hidden />
                  Email
                </>
              )}
            </Chip>
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-1">
            {item.subject_or_thread}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <MigrateButton title={taskTitle} onMigrated={onMigrate} />
          <ClearButton onClear={onClear} />
        </div>
      </div>

      {/* Excerpt — collapsed by default to save vertical space */}
      {item.excerpt && (
        <div>
          <button
            type="button"
            onClick={() => setExcerptOpen((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {excerptOpen ? (
              <ChevronDown className="h-3 w-3" aria-hidden />
            ) : (
              <ChevronRight className="h-3 w-3" aria-hidden />
            )}
            {excerptOpen ? "Hide excerpt" : "Show excerpt"}
          </button>
          {excerptOpen && (
            <p className="mt-1 pl-4 text-[11px] text-muted-foreground italic border-l-2 border-border">
              {item.excerpt}
            </p>
          )}
        </div>
      )}

      {/* Draft reply with copy button */}
      <div className="rounded bg-[var(--surface-base)] border border-border p-2">
        <div className="flex items-start justify-between gap-2">
          <p className="text-[11px] leading-relaxed flex-1">{item.draft_reply}</p>
          <CopyButton text={item.draft_reply} />
        </div>
      </div>
    </div>
  );
}

function ActionRequiredSection({ items, onMigrate, onClear }: { items: TriageActionItem[]; onMigrate: (id: string) => void; onClear: (id: string) => void }) {
  if (items.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No action items"
        hint="Nothing waiting on your reply"
        className="py-4"
      />
    );
  }
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <ActionCard
          // Stable identity key so MigrateButton state stays bound to the item
          // (not the array slot) — without this, removing one item would leave
          // the next item's MigrateButton showing a stale "✓ Added" badge
          // because React reuses the component at key=0.
          key={actionId(item)}
          item={item}
          onMigrate={() => onMigrate(actionId(item))}
          onClear={() => onClear(actionId(item))}
        />
      ))}
    </div>
  );
}

function MeetingSection({ items, onMigrate, onClear }: { items: TriageMeetingItem[]; onMigrate: (id: string) => void; onClear: (id: string) => void }) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {items.map((item) => {
        const taskTitle = item.datetime_hint
          ? `Confirm meeting: ${item.sender} — ${item.subject} (${item.datetime_hint})`
          : `Confirm meeting: ${item.sender} — ${item.subject}`;
        return (
          <div key={meetingId(item)} className="flex items-start gap-2 text-xs">
            <Calendar
              className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground"
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="font-medium">{item.sender}</span>
                {/* WHY yellow chip: draws attention to items that need manual
                    calendar verification without blocking the widget render. */}
                {item.needs_calendar_check && (
                  <Chip variant="yellow">missing on calendar</Chip>
                )}
              </div>
              <p className="text-muted-foreground line-clamp-1">{item.subject}</p>
              {item.datetime_hint && (
                <p className="text-muted-foreground/70 text-[10px]">
                  {item.datetime_hint}
                </p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <MigrateButton title={taskTitle} onMigrated={() => onMigrate(meetingId(item))} />
              <ClearButton onClear={() => onClear(meetingId(item))} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function InfoOnlySection({ items, onMigrate, onClear }: { items: TriageInfoItem[]; onMigrate: (id: string) => void; onClear: (id: string) => void }) {
  if (items.length === 0) return null;
  return (
    <Collapsible
      defaultOpen={false}
      label={`${items.length} FYI / info item${items.length !== 1 ? "s" : ""}`}
    >
      <div className="space-y-1 pl-5">
        {items.map((item) => {
          const taskTitle = `${item.sender} — ${item.subject}`;
          return (
            <div key={infoId(item)} className="flex items-start gap-2 text-xs group">
              <div className="min-w-0 flex-1">
                <span className="font-medium">{item.sender}</span>
                <span className="text-muted-foreground"> — {item.summary}</span>
              </div>
              {/* opacity-0 + group-hover keeps the row clean when the user is
                  scanning; the migrate + clear buttons reveal on hover so they're
                  there when needed without crowding the FYI list. */}
              <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 shrink-0">
                <MigrateButton title={taskTitle} onMigrated={() => onMigrate(infoId(item))} />
                <ClearButton onClear={() => onClear(infoId(item))} />
              </div>
            </div>
          );
        })}
      </div>
    </Collapsible>
  );
}

function SkipSection({
  count,
  senders,
}: {
  count: number;
  senders: string[];
}) {
  if (count === 0) return null;
  // Show up to 5 representative senders; truncate the rest to a count.
  const preview = senders.slice(0, 5).join(", ");
  const more = count - senders.slice(0, 5).length;
  return (
    <p className="text-[10px] text-muted-foreground/60 pt-1 border-t border-border">
      {count} archived: {preview}
      {more > 0 ? ` +${more} more` : ""}
    </p>
  );
}

// ── Skeleton loader ───────────────────────────────────────────────────────────

function TriageSkeleton() {
  return (
    <div className="space-y-3 animate-in fade-in duration-200">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="rounded-lg border border-border p-3 space-y-2"
        >
          <Skeleton className="h-3.5 w-32" />
          <Skeleton className="h-3 w-48" />
          <Skeleton className="h-10 w-full" />
        </div>
      ))}
    </div>
  );
}

// ── Main widget ───────────────────────────────────────────────────────────────

// Stable per-item ids so the migrated Set survives re-renders + cache reuse.
// Sender + subject is enough to identify a triage item across a single session;
// triage data is regenerated by Haiku each refresh so deep equality isn't
// available to us.
function actionId(i: TriageActionItem) { return `act:${i.sender}::${i.subject_or_thread}`; }
function meetingId(i: TriageMeetingItem) { return `mtg:${i.sender}::${i.subject}`; }
function infoId(i: TriageInfoItem) { return `info:${i.sender}::${i.subject}`; }
function staleId(i: TriageStaleItem) { return `stl:${i.sender}::${i.subject_or_thread}`; }

// ── Tab definitions ───────────────────────────────────────────────────────────

type TriageTab = "all" | "email" | "imessage";

const TRIAGE_TABS: { key: TriageTab; label: string; icon: React.ElementType }[] = [
  { key: "all",      label: "All",      icon: Layers },
  { key: "email",    label: "Email",    icon: Mail },
  { key: "imessage", label: "Messages", icon: MessageSquare },
];

export function TriageWidget() {
  const [data, setData] = useState<TriageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  // refreshing tracks the user-triggered bust-cache flow separately so the
  // existing data stays visible (no flash-of-skeleton) during the re-fetch.
  const [refreshing, setRefreshing] = useState(false);
  // Active source tab — "all" | "email" | "imessage". Each tab has its own
  // backend cache key (triage:all / triage:email / triage:imessage) so
  // switching tabs doesn't pollute each other's result.
  const [tab, setTab] = useState<TriageTab>("all");
  // Session-level set of item ids the user migrated to Tasks OR cleared.
  // GLOBAL across tabs — items migrated/cleared in Email tab stay hidden when
  // switching to All tab (same actionId / meetingId keys are used regardless
  // of source). WHY a single set: clearing and migrating both mean "hide this
  // item now"; using one set keeps filtering logic in one place.
  const [migrated, setMigrated] = useState<Set<string>>(new Set());
  const markMigrated = useCallback((id: string) => {
    setMigrated((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);
  // markCleared is identical in effect to markMigrated — it adds to the same
  // hidden set — but named separately so call sites read clearly at a glance.
  const markCleared = useCallback((id: string) => {
    setMigrated((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);

  const load = useCallback(async (bust = false, source: TriageTab = tab) => {
    try {
      if (bust) setRefreshing(true);
      else setLoading(true);
      setFetchError(null);
      const result = await fetchTriage({ bust, source });
      // The backend can return an error key with HTTP 200 (soft failure).
      // Only treat it as a hard error if there's also no action_required data.
      if (result.error && !result.action_required?.length) {
        setFetchError(result.error);
      } else {
        setData(result);
      }
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [tab]);

  // Initial load.
  useEffect(() => {
    load(false);
  }, [load]);

  // Refetch when tab changes (load depends on tab via useCallback, so this
  // fires whenever tab changes and load is recreated with the new tab value).
  useEffect(() => {
    setData(null);
    setLoading(true);
    load(false, tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const handleRefresh = useCallback(() => {
    // Bust the backend 5-min cache so a new Haiku call fires immediately.
    // Pass current tab so the right per-source cache key is busted.
    load(true, tab);
  }, [load, tab]);

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="pb-2 shrink-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-1.5">
            <Inbox className="h-4 w-4" aria-hidden />
            Triage
          </CardTitle>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={loading || refreshing}
            title="Refresh triage (busts 5-min cache)"
            className="rounded p-1 hover:bg-[var(--surface-raised)] transition-colors disabled:opacity-40"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
              aria-hidden
            />
          </button>
        </div>
      </CardHeader>

      {/* Tab strip — "All" | "Email" | "Messages" */}
      <div className="px-4 pb-1.5 flex gap-1 shrink-0">
        {TRIAGE_TABS.map((t) => {
          const active = tab === t.key;
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              title={t.label}
              className={
                "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] transition-colors " +
                (active
                  ? "bg-foreground/10 text-foreground"
                  : "bg-foreground/[0.02] text-muted-foreground hover:bg-foreground/5 hover:text-foreground/80")
              }
            >
              <Icon className="h-3 w-3 shrink-0" aria-hidden />
              {t.label}
            </button>
          );
        })}
      </div>

      <CardContent className="flex-1 overflow-y-auto space-y-3 pb-3">
        {loading && !data ? (
          <TriageSkeleton />
        ) : fetchError ? (
          <ErrorState message={fetchError} onRetry={() => load(false)} />
        ) : !data ? (
          <EmptyState icon={Inbox} title="No triage data" />
        ) : (
          <>
            {/* Filter out items the user already migrated to Tasks this
                session. Counts in section headers reflect post-filter length
                so they stay accurate as the user clicks "Task" buttons. */}
            {(() => {
              const visibleStale = data.stale.filter((i) => !migrated.has(staleId(i)));
              const visibleAction = data.action_required.filter((i) => !migrated.has(actionId(i)));
              const visibleMeeting = data.meeting_info.filter((i) => !migrated.has(meetingId(i)));
              const visibleInfo = data.info_only.filter((i) => !migrated.has(infoId(i)));

              // Per-tab empty state (W6): if all sections are empty for this
              // tab, show a clear message instead of a blank widget.
              const totalVisible =
                visibleStale.length +
                visibleAction.length +
                visibleMeeting.length +
                visibleInfo.length;
              if (totalVisible === 0) {
                const emptyMsg =
                  tab === "email"
                    ? "No emails to triage"
                    : tab === "imessage"
                    ? "No messages to triage"
                    : "Nothing to triage";
                const emptyHint =
                  tab === "email"
                    ? "All emails are either read or auto-archived"
                    : tab === "imessage"
                    ? "No unread iMessage threads need attention"
                    : "All channels are clear";
                const EmptyIcon = tab === "email" ? Mail : tab === "imessage" ? MessageSquare : Inbox;
                return (
                  <EmptyState
                    icon={EmptyIcon}
                    title={emptyMsg}
                    hint={emptyHint}
                    className="py-8"
                  />
                );
              }

              return (
                <>
                  {/* Stale items — red, expanded by default since they're urgent */}
                  <StaleSection items={visibleStale} onMigrate={markMigrated} onClear={markCleared} />

                  {/* Action required — highest signal, always visible */}
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                      Action Required ({visibleAction.length})
                    </p>
                    <ActionRequiredSection items={visibleAction} onMigrate={markMigrated} onClear={markCleared} />
                  </div>

                  {/* Meeting info — only rendered when present */}
                  {visibleMeeting.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                        Meeting Info ({visibleMeeting.length})
                      </p>
                      <MeetingSection items={visibleMeeting} onMigrate={markMigrated} onClear={markCleared} />
                    </div>
                  )}

                  {/* Info only — FYI items, collapsed to reduce noise */}
                  <InfoOnlySection items={visibleInfo} onMigrate={markMigrated} onClear={markCleared} />

                  {/* Skip — lowest signal, one-liner at the very bottom */}
                  <SkipSection
                    count={data.skip_count}
                    senders={data.skip_senders}
                  />
                </>
              );
            })()}
          </>
        )}
      </CardContent>
    </Card>
  );
}
