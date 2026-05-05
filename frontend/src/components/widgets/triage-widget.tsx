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
} from "lucide-react";
import { fetchTriage } from "@/lib/api";
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

function StaleSection({ items }: { items: TriageStaleItem[] }) {
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
        {items.map((item, i) => (
          <div key={i} className="flex items-start gap-2 text-xs">
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
            <span className="text-muted-foreground">
              <span className="font-medium text-foreground">{item.sender}</span>
              {" — "}
              {item.subject_or_thread}
              <span className="ml-1 text-red-500">({item.days_stale}d)</span>
            </span>
          </div>
        ))}
      </div>
    </Collapsible>
  );
}

function ActionCard({ item }: { item: TriageActionItem }) {
  const [excerptOpen, setExcerptOpen] = useState(false);

  return (
    <div className="rounded-lg border border-border bg-[var(--surface-raised)] p-3 space-y-2">
      {/* Header row: sender + channel chip */}
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

function ActionRequiredSection({ items }: { items: TriageActionItem[] }) {
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
      {items.map((item, i) => (
        <ActionCard key={i} item={item} />
      ))}
    </div>
  );
}

function MeetingSection({ items }: { items: TriageMeetingItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {items.map((item, i) => (
        <div key={i} className="flex items-start gap-2 text-xs">
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
        </div>
      ))}
    </div>
  );
}

function InfoOnlySection({ items }: { items: TriageInfoItem[] }) {
  if (items.length === 0) return null;
  return (
    <Collapsible
      defaultOpen={false}
      label={`${items.length} FYI / info item${items.length !== 1 ? "s" : ""}`}
    >
      <div className="space-y-1 pl-5">
        {items.map((item, i) => (
          <div key={i} className="text-xs">
            <span className="font-medium">{item.sender}</span>
            <span className="text-muted-foreground"> — {item.summary}</span>
          </div>
        ))}
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

export function TriageWidget() {
  const [data, setData] = useState<TriageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  // refreshing tracks the user-triggered bust-cache flow separately so the
  // existing data stays visible (no flash-of-skeleton) during the re-fetch.
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (bust = false) => {
    try {
      if (bust) setRefreshing(true);
      else setLoading(true);
      setFetchError(null);
      const result = await fetchTriage({ bust });
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
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  const handleRefresh = useCallback(() => {
    // Bust the backend 5-min cache so a new Opus call fires immediately.
    load(true);
  }, [load]);

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

      <CardContent className="flex-1 overflow-y-auto space-y-3 pb-3">
        {loading && !data ? (
          <TriageSkeleton />
        ) : fetchError ? (
          <ErrorState message={fetchError} onRetry={() => load(false)} />
        ) : !data ? (
          <EmptyState icon={Inbox} title="No triage data" />
        ) : (
          <>
            {/* Stale items — red, expanded by default since they're urgent */}
            <StaleSection items={data.stale} />

            {/* Action required — highest signal, always visible */}
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                Action Required ({data.action_required.length})
              </p>
              <ActionRequiredSection items={data.action_required} />
            </div>

            {/* Meeting info — only rendered when present */}
            {data.meeting_info.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                  Meeting Info ({data.meeting_info.length})
                </p>
                <MeetingSection items={data.meeting_info} />
              </div>
            )}

            {/* Info only — FYI items, collapsed to reduce noise */}
            <InfoOnlySection items={data.info_only} />

            {/* Skip — lowest signal, one-liner at the very bottom */}
            <SkipSection
              count={data.skip_count}
              senders={data.skip_senders}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}
