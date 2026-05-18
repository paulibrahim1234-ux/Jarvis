"use client";

import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { useEffect, useState, useCallback } from "react";
import { BookOpen } from "lucide-react";
import {
  fetchUWorldData,
  refreshUWorld,
  fetchAnkiSuggestions,
  unsuspendAnkiCards,
  openUWorldQuestion,
  type UWorldSession,
  type UWorldWeakTopic,
  type UWorldIncorrect,
  type AnkiSuggestion,
} from "@/lib/api";
import { openInApp } from "@/lib/open-apps";
import Skeleton from "@/components/ui/skeleton";
import { EmptyState } from "./empty-state";
import { ErrorState } from "./error-state";

// Override via NEXT_PUBLIC_UWORLD_COURSE_ID if your USMLE course ID differs.
const COURSE_ID = process.env.NEXT_PUBLIC_UWORLD_COURSE_ID || "14842106";

function TrendIcon({ trend }: { trend: "improving" | "declining" | "stable" }) {
  if (trend === "improving")
    return <span className="text-emerald-400">&#x2191;</span>;
  if (trend === "declining")
    return <span className="text-red-400">&#x2193;</span>;
  return <span className="text-muted-foreground/40">&#x2014;</span>;
}

function scoreColor(score: number) {
  if (score >= 70) return "bg-emerald-500";
  if (score >= 50) return "bg-amber-500";
  return "bg-red-500";
}

function scoreTrackColor(score: number) {
  if (score >= 70) return "bg-emerald-500/10";
  if (score >= 50) return "bg-amber-500/10";
  return "bg-red-500/10";
}

// ── Inline expand panel ─────────────────────────────────────────────────────

interface WrongQGroup {
  system: string;
  questions: UWorldIncorrect[];
}

function groupBySystem(qs: UWorldIncorrect[]): WrongQGroup[] {
  const map = new Map<string, UWorldIncorrect[]>();
  for (const q of qs) {
    const key = q.uworld_system || "Unknown";
    const bucket = map.get(key) ?? [];
    bucket.push(q);
    map.set(key, bucket);
  }
  return Array.from(map.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([system, questions]) => ({ system, questions }));
}

interface SessionExpandPanelProps {
  session: UWorldSession;
  incorrects: UWorldIncorrect[];
  onClose: () => void;
}

function SessionExpandPanel({ session, incorrects, onClose }: SessionExpandPanelProps) {
  // Anki inline panel state
  const [ankiLoading, setAnkiLoading] = useState(false);
  const [ankiCards, setAnkiCards] = useState<AnkiSuggestion[] | null>(null);
  const [ankiSelected, setAnkiSelected] = useState<Set<number>>(new Set());
  const [ankiMsg, setAnkiMsg] = useState<string | null>(null);
  const [ankiSubmitting, setAnkiSubmitting] = useState(false);
  const [ankiToast, setAnkiToast] = useState<string | null>(null);

  // Filter wrong questions to this session by test_id
  const sessionWrong = session.test_id
    ? incorrects.filter((q) => q.test_id === session.test_id)
    : [];

  const groups = groupBySystem(sessionWrong);

  // UWorld deep-link: use test results overview (no seq segment).
  // The /seq form (e.g. /results/{course}/{test_id}/0) only shows the
  // loading spinner because seq=0 doesn't resolve to a real question.
  // Dropping the segment lands on the test overview page correctly.
  const testResultsUrl = session.test_id
    ? `https://apps.uworld.com/courseapp/usmle/v50/en-US/performance/test/results/${COURSE_ID}/${session.test_id}`
    : null;

  // Fetch Anki suggestions for exactly this session's wrong QIDs.
  // Uses the qid_filter param to avoid pulling all 250+ suggestions and
  // then doing a client-side count that was previously cut off by the limit.
  const handleAnkiSuggest = async () => {
    if (ankiLoading) return;
    setAnkiLoading(true);
    setAnkiMsg(null);
    setAnkiCards(null);
    setAnkiSelected(new Set());
    try {
      const sessionQids = sessionWrong.map((q) => q.uworld_qid);
      const result = await fetchAnkiSuggestions({ qidFilter: sessionQids });
      if (!result.available && !result.suggestions?.length) {
        setAnkiMsg("Anki not reachable — is AnkiConnect running?");
        setAnkiCards([]);
      } else if (result.suggestions.length === 0) {
        setAnkiMsg("No suspended Anki cards matched for this session");
        setAnkiCards([]);
      } else {
        setAnkiCards(result.suggestions);
        // Auto-select all cards so the user can unsuspend with one click
        setAnkiSelected(new Set(result.suggestions.map((s) => s.card_id)));
      }
    } catch {
      setAnkiMsg("Error reaching Anki suggestions");
      setAnkiCards([]);
    } finally {
      setAnkiLoading(false);
    }
  };

  const toggleAnkiCard = (id: number) => {
    setAnkiSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleUnsuspend = async () => {
    if (ankiSelected.size === 0 || ankiSubmitting) return;
    setAnkiSubmitting(true);
    try {
      const ids = Array.from(ankiSelected);
      const res = await unsuspendAnkiCards(ids);
      if (res.errors && res.errors.length > 0) {
        setAnkiToast(`Unsuspended ${res.unsuspended}. Errors: ${res.errors.join("; ")}`);
      } else {
        setAnkiToast(`Unsuspended ${res.unsuspended} card${res.unsuspended === 1 ? "" : "s"}`);
      }
      // Remove unsuspended cards from the list
      const unsuspendedIds = new Set(ids);
      setAnkiCards((prev) => (prev ?? []).filter((c) => !unsuspendedIds.has(c.card_id)));
      setAnkiSelected(new Set());
    } catch (e) {
      setAnkiToast(e instanceof Error ? e.message : "Unsuspend failed");
    } finally {
      setAnkiSubmitting(false);
      setTimeout(() => setAnkiToast(null), 4000);
    }
  };

  // ESC closes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="mt-1 mb-2 rounded-lg border border-foreground/10 bg-foreground/[0.03] px-3 py-3 text-xs">
      {/* Header row — single "Open in UWorld" affordance lives here, not
          duplicated per system group. (Was previously rendered inside
          groups.map() which produced N copies all linking to the same
          test results URL.) */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <span className="font-semibold text-foreground/90">
            Test of {session.date}
          </span>
          {session.topics.length > 0 && (
            <span className="text-muted-foreground/70">
              {" "}— {session.topics.join(", ")}
            </span>
          )}
          {session.correct != null && session.total != null && (
            <span className="text-muted-foreground/70">
              {" "}— {session.correct}/{session.total}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {testResultsUrl && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                // Navigate the existing UWorld tab in Comet rather than
                // spawning a new tab (which loses session warmth and
                // sometimes triggers the loading spinner).
                void openUWorldQuestion(testResultsUrl);
              }}
              className="text-[10px] text-blue-400/80 hover:text-blue-400 transition-colors cursor-pointer"
              title="Opens test results overview in your UWorld tab"
            >
              Open in UWorld ↗
            </button>
          )}
          <button
            onClick={onClose}
            className="text-muted-foreground/50 hover:text-muted-foreground transition-colors text-sm leading-none"
            aria-label="Collapse"
          >
            ×
          </button>
        </div>
      </div>

      {!session.test_id ? (
        <p className="text-muted-foreground/50 italic">(no detail available)</p>
      ) : sessionWrong.length === 0 ? (
        <p className="text-muted-foreground/50 italic">No wrong questions recorded for this session</p>
      ) : (
        <>
          {/* Wrong questions grouped by system */}
          <div className="space-y-3">
            {groups.map((g) => (
              <div key={g.system}>
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-foreground/80 uppercase tracking-wide text-[10px]">
                    {g.system}
                  </span>
                </div>
                <div className="space-y-0.5 pl-1">
                  {g.questions.map((q) => {
                    // Per-question deep-link is now valid because test_seq
                    // is set to the question's 1-based position in the test
                    // (used to be the session's percentile, which UWorld
                    // treated as an out-of-range seq and showed the loader).
                    const qUrl =
                      session.test_id && q.test_seq != null
                        ? `https://apps.uworld.com/courseapp/usmle/v50/en-US/performance/test/results/${COURSE_ID}/${session.test_id}/${q.test_seq}`
                        : null;
                    const className = qUrl
                      ? "flex items-center gap-2 cursor-pointer hover:bg-foreground/5 rounded px-1 -mx-1 transition-colors"
                      : "flex items-center gap-2";
                    return (
                      <div
                        key={q.uworld_qid}
                        role={qUrl ? "button" : undefined}
                        tabIndex={qUrl ? 0 : undefined}
                        onClick={qUrl ? () => void openUWorldQuestion(qUrl) : undefined}
                        onKeyDown={qUrl ? (e) => { if (e.key === "Enter") void openUWorldQuestion(qUrl); } : undefined}
                        className={className}
                        title={qUrl ? "Open this question in your UWorld tab" : undefined}
                      >
                        <span className="text-foreground/80">{q.uworld_topic_name || q.uworld_topic}</span>
                        <span className="text-muted-foreground/40 font-mono text-[10px] shrink-0">
                          #{q.uworld_qid}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          {/* Anki suggestions — inline card list with checkboxes + unsuspend button */}
          <div className="mt-3 border-t border-foreground/5 pt-3">
            {ankiCards === null ? (
              /* Not loaded yet — show the trigger button */
              <Button
                variant="ghost"
                size="xs"
                className="text-xs h-6 px-2 text-amber-300/80 hover:text-amber-300"
                onClick={handleAnkiSuggest}
                disabled={ankiLoading}
              >
                {ankiLoading ? "Checking Anki…" : "Suggest Anki cards"}
              </Button>
            ) : ankiCards.length === 0 ? (
              /* Loaded but empty */
              <span className="text-[10px] text-muted-foreground/60">
                {ankiMsg ?? "No suspended Anki cards matched for this session"}
              </span>
            ) : (
              /* Loaded with cards — show checkboxes + unsuspend */
              <div className="space-y-1.5">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-amber-300/80 font-medium uppercase tracking-wide">
                    Anki — {ankiCards.length} suspended card{ankiCards.length === 1 ? "" : "s"}
                  </span>
                  <button
                    onClick={() => {
                      if (ankiSelected.size === ankiCards.length) {
                        setAnkiSelected(new Set());
                      } else {
                        setAnkiSelected(new Set(ankiCards.map((c) => c.card_id)));
                      }
                    }}
                    className="text-[10px] text-muted-foreground/50 hover:text-muted-foreground transition-colors"
                  >
                    {ankiSelected.size === ankiCards.length ? "Deselect all" : "Select all"}
                  </button>
                </div>
                {ankiCards.map((card) => {
                  const checked = ankiSelected.has(card.card_id);
                  return (
                    <label
                      key={card.card_id}
                      className={`flex items-start gap-2 px-2 py-1.5 rounded-md cursor-pointer border transition-colors ${
                        checked
                          ? "bg-emerald-500/10 border-emerald-500/25"
                          : "bg-foreground/[0.02] border-foreground/5 hover:bg-foreground/[0.04]"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleAnkiCard(card.card_id)}
                        className="mt-0.5 accent-emerald-500 shrink-0"
                      />
                      <div className="min-w-0">
                        <div className="truncate text-[11px] text-foreground/80">
                          {card.front || <span className="italic text-muted-foreground">(no preview)</span>}
                        </div>
                        <div className="mt-0.5 text-[10px] text-muted-foreground/50">
                          UW {card.uworld_qid}
                          {card.uworld_topic && ` · ${card.uworld_topic}`}
                        </div>
                      </div>
                    </label>
                  );
                })}
                {ankiToast && (
                  <div className="text-[10px] text-emerald-400 text-center py-1">{ankiToast}</div>
                )}
                <button
                  onClick={handleUnsuspend}
                  disabled={ankiSelected.size === 0 || ankiSubmitting}
                  className={`mt-1 w-full py-1.5 rounded-md text-[11px] font-medium transition-colors ${
                    ankiSelected.size === 0 || ankiSubmitting
                      ? "bg-foreground/5 text-muted-foreground cursor-not-allowed"
                      : "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30"
                  }`}
                >
                  {ankiSubmitting
                    ? "Unsuspending…"
                    : `Unsuspend${ankiSelected.size > 0 ? ` ${ankiSelected.size}` : ""} card${ankiSelected.size === 1 ? "" : "s"}`}
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── Session row ─────────────────────────────────────────────────────────────

interface SessionRowProps {
  session: UWorldSession;
  incorrects: UWorldIncorrect[];
  isExpanded: boolean;
  onToggle: () => void;
}

function SessionRow({ session, incorrects, isExpanded, onToggle }: SessionRowProps) {
  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => e.key === "Enter" && onToggle()}
        className={`flex items-center justify-between rounded-lg px-3 py-2.5 [body.density-compact_&]:py-1.5 cursor-pointer transition-colors ${
          isExpanded ? "bg-foreground/8 hover:bg-foreground/10" : "hover:bg-foreground/5"
        }`}
        aria-expanded={isExpanded}
      >
        <div className="space-y-0.5">
          <div className="text-sm font-medium">{session.topics.join(", ")}</div>
          <div className="text-xs text-muted-foreground/60">{session.date}</div>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-right">
            <div className="text-sm font-semibold tabular-nums">
              {session.score}%
            </div>
            <div className="text-xs text-muted-foreground/60">
              {session.correct != null && session.total != null
                ? `${session.correct}/${session.total}`
                : "—"}
            </div>
          </div>
          <span className="text-muted-foreground/40 text-xs">
            {isExpanded ? "▾" : "▸"}
          </span>
        </div>
      </div>
      {isExpanded && (
        <SessionExpandPanel
          session={session}
          incorrects={incorrects}
          onClose={onToggle}
        />
      )}
    </div>
  );
}

// ── Session list ─────────────────────────────────────────────────────────────

function SessionList({
  sessions,
  incorrects,
}: {
  sessions: UWorldSession[];
  incorrects: UWorldIncorrect[];
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // D4: stable reference so ESC effect in SessionExpandPanel doesn't
  // re-register on every render.
  const toggle = useCallback((id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  if (sessions.length === 0) {
    return (
      <EmptyState icon={BookOpen} title="No recent sessions" className="py-4" />
    );
  }

  return (
    <div className="space-y-1">
      {sessions.map((s) => {
        const onToggle = () => toggle(s.id);
        return (
          <SessionRow
            key={s.id}
            session={s}
            incorrects={incorrects}
            isExpanded={expandedId === s.id}
            onToggle={onToggle}
          />
        );
      })}
    </div>
  );
}

// ── Weak topics ───────────────────────────────────────────────────────────────

function WeakTopicsSection({ topics }: { topics: UWorldWeakTopic[] }) {
  if (topics.length === 0) return null;
  return (
    <div className="mt-4 space-y-3 border-t border-foreground/5 pt-4">
      <h4 className="text-[13px] font-semibold tracking-[-0.02em] text-muted-foreground">
        Weak Topics
      </h4>
      {topics.map((t) => (
        <div key={t.topic} className="space-y-1.5 rounded-lg px-3 py-2 hover:bg-foreground/5 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-sm">{t.topic}</span>
            <div className="flex items-center gap-1.5">
              <span className="text-sm tabular-nums font-medium">{t.score}%</span>
              <TrendIcon trend={t.trend} />
            </div>
          </div>
          <div className={`relative h-1.5 w-full overflow-hidden rounded-full ${scoreTrackColor(t.score)}`}>
            <div
              className={`h-full rounded-full ${scoreColor(t.score)} transition-transform duration-500 ease-out origin-left`}
              style={{ transform: `scaleX(${t.score / 100})`, width: '100%' }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main widget ───────────────────────────────────────────────────────────────

export function UWorldWidget() {
  const [sessions, setSessions] = useState<UWorldSession[]>([]);
  const [weakTopics, setWeakTopics] = useState<UWorldWeakTopic[]>([]);
  const [incorrects, setIncorrects] = useState<UWorldIncorrect[]>([]);
  const [launching, setLaunching] = useState(false);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [dataSource, setDataSource] = useState<string | null>(null);
  const [loggedOut, setLoggedOut] = useState(false);
  const [staleData, setStaleData] = useState(false);

  const handleLaunchUWorld = async () => {
    setLaunching(true);
    try {
      await openInApp({ app: "uworld", ref: "dashboard" });
    } catch (error) {
      console.error("Failed to launch UWorld:", error);
    } finally {
      setLaunching(false);
    }
  };

  const loadData = useCallback(() => {
    // TODO(status-dot): wire dataAge from fetchUWorldData — record fetch
    // timestamp on success, pass status/lastUpdated to WidgetWrapper.
    setFetchError(false);
    return fetchUWorldData()
      .then((data) => {
        setSessions(data.sessions ?? []);
        setWeakTopics(data.weak_topics ?? []);
        setIncorrects(data.incorrect ?? []);
        setDataSource(data.source ?? null);
        setStaleData(data.stale_data ?? false);
      })
      .catch((e) => {
        console.error("Failed to fetch UWorld data:", e);
        setFetchError(true);
      });
  }, []);

  useEffect(() => {
    loadData().finally(() => setLoading(false));
  }, [loadData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshMsg(null);
    setLoggedOut(false);
    try {
      const result = await refreshUWorld();
      if (result.status === "logged_out") {
        setLoggedOut(true);
        setRefreshMsg(result.message ?? "Not logged in to UWorld in your browser.");
      } else if (result.status === "js_disabled") {
        setRefreshMsg(result.message ?? "Browser JavaScript from Apple Events is disabled. Enable it in View > Developer > Allow JavaScript from Apple Events.");
      } else if (result.status === "error") {
        setRefreshMsg(result.message ?? "Refresh failed.");
      } else {
        if (result.sessions.length > 0) {
          setSessions(result.sessions);
          setWeakTopics(result.weak_topics);
          setDataSource(result.source ?? "scraped");
          setRefreshMsg(`Loaded ${result.sessions.length} session(s) from UWorld.`);
          // Re-fetch to get full payload including incorrects
          await loadData();
        } else {
          await loadData();
          setRefreshMsg(result.message ?? "Refresh complete.");
        }
      }
    } catch (e) {
      setRefreshMsg(String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const hasData = sessions.length > 0 || weakTopics.length > 0;
  const uworldSessions = sessions.filter((s) => s.platform === "uworld");
  const trueLearnSessions = sessions.filter((s) => s.platform === "truelearn");

  return (
    <Card
      className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card hover:border-foreground/15 transition-colors"
      style={{ padding: "var(--widget-density-pad)" }}
    >
      <CardHeader className="p-5 pb-3 flex flex-row items-center justify-between">
        <div className="flex items-center gap-2">
          <CardTitle className="text-[13px] font-semibold tracking-[-0.02em] text-muted-foreground">
            QBank
          </CardTitle>
          {dataSource === "stub" && (
            <span className="text-xs text-amber-400/70 font-normal">(sample data)</span>
          )}
          {dataSource === "scraped" && (
            <span className="text-xs text-emerald-400/70 font-normal">(live)</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            onClick={handleRefresh}
            disabled={refreshing}
            variant="ghost"
            size="xs"
            className="cursor-pointer text-xs"
            title="Pull latest scores from UWorld"
          >
            {refreshing ? "Refreshing..." : "Refresh"}
          </Button>
          <Button
            onClick={handleLaunchUWorld}
            disabled={launching}
            variant="ghost"
            size="xs"
            className="cursor-pointer"
          >
            {launching ? "Opening..." : "Open"}
          </Button>
        </div>
      </CardHeader>

      {/* Stale data warning */}
      {staleData && !refreshMsg && (
        <div className="mx-5 mb-2 rounded-md px-3 py-2 text-xs bg-amber-500/10 text-amber-300">
          <span className="font-medium">Question counts unavailable</span> — log into UWorld in Comet and click <span className="font-medium">Refresh</span> to load real data.
        </div>
      )}

      {/* Status / message bar */}
      {refreshMsg && (
        <div className={`mx-5 mb-2 rounded-md px-3 py-2 text-xs ${loggedOut ? "bg-amber-500/10 text-amber-300" : "bg-foreground/5 text-muted-foreground"}`}>
          {loggedOut && (
            <span className="font-medium">Not logged in — </span>
          )}
          {refreshMsg}
          {loggedOut && (
            <> <a href="https://www.uworld.com" target="_blank" rel="noreferrer" className="underline">Open UWorld</a> to sign in, then Refresh.</>
          )}
        </div>
      )}

      <CardContent className="flex-1 min-h-0 p-5 pt-0 flex flex-col">
        {loading ? (
          // Skeleton silhouette: header row + score bar + session list rows
          <div className="flex flex-col gap-3 pt-1">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : fetchError ? (
          // F8 — surface fetch failures instead of silently showing nothing
          <ErrorState
            message="Couldn't load UWorld"
            onRetry={() => { void loadData(); }}
          />
        ) : !hasData ? (
          // F4 fade-in applies here too since we just left loading
          <div className="animate-in fade-in duration-200 flex flex-col items-center justify-center gap-4 py-8 text-center">
            <div>
              <p className="text-sm text-muted-foreground">No QBank data yet</p>
              <p className="text-xs text-muted-foreground/70 mt-1">
                Log in to UWorld in your browser, then click Refresh
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                onClick={handleRefresh}
                disabled={refreshing}
                variant="default"
                size="sm"
                className="cursor-pointer"
              >
                {refreshing ? "Refreshing..." : "Refresh"}
              </Button>
              <Button
                onClick={handleLaunchUWorld}
                disabled={launching}
                variant="ghost"
                size="sm"
                className="cursor-pointer"
              >
                {launching ? "Opening..." : "Open UWorld"}
              </Button>
            </div>
          </div>
        ) : (
          // F4 — fade in when skeleton gives way to real content
          <Tabs defaultValue="uworld" className="animate-in fade-in duration-200 flex-1 min-h-0 flex flex-col">
            {/* F10 — density-compact tightens the tab row gap */}
            <TabsList className="mb-3 [body.density-compact_&]:mb-1.5 bg-foreground/5 border border-foreground/5 shrink-0">
              <TabsTrigger value="uworld" className="text-xs data-[state=active]:bg-foreground/10">
                UWorld {uworldSessions.length > 0 && <span className="ml-1 text-muted-foreground/50">({uworldSessions.length})</span>}
              </TabsTrigger>
              {/* Only show TrueLearn tab when there's data — hides the
                  always-empty placeholder for users who don't use it. */}
              {trueLearnSessions.length > 0 && (
                <TabsTrigger value="truelearn" className="text-xs data-[state=active]:bg-foreground/10">
                  TrueLearn <span className="ml-1 text-muted-foreground/50">({trueLearnSessions.length})</span>
                </TabsTrigger>
              )}
            </TabsList>
            {/* no-drag on each ScrollArea: the session rows are
                role='button' elements that already match draggableCancel,
                but the scrollable viewport itself is a plain div that could
                still initiate a drag on a slow press. */}
            <TabsContent value="uworld" className="flex-1 min-h-0 mt-0">
              <ScrollArea className="no-drag h-full">
                <SessionList sessions={uworldSessions} incorrects={incorrects} />
                <WeakTopicsSection topics={weakTopics} />
              </ScrollArea>
            </TabsContent>
            {trueLearnSessions.length > 0 && (
              <TabsContent value="truelearn" className="flex-1 min-h-0 mt-0">
                <ScrollArea className="no-drag h-full">
                  <SessionList sessions={trueLearnSessions} incorrects={incorrects} />
                </ScrollArea>
              </TabsContent>
            )}
          </Tabs>
        )}
      </CardContent>
    </Card>
  );
}
