"use client";

import { useRef, useState, useEffect, useCallback } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  fetchAnkiStats,
  fetchAnkiSuggestions,
  unsuspendAnkiCards,
  refreshUWorld,
  rebuildAnkiQidIndex,
  getAnkiBuildIndexStatus,
  type AnkiSuggestion,
} from "@/lib/api";
import type { AnkiStats } from "@/lib/types";

function retentionColor(r: number) {
  if (r >= 90) return "text-emerald-400";
  if (r >= 80) return "text-amber-400";
  return "text-red-400";
}

// gradient stop color along red -> amber -> green at pct [0..100]
function progressGradient(pct: number) {
  if (pct >= 80) return "from-emerald-600 to-emerald-400";
  if (pct >= 40) return "from-amber-600 to-amber-400";
  return "from-red-600 to-amber-500";
}

function useContainerSize(ref: React.RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry)
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

type Tab = "stats" | "suggested";
type LiveStatus = "loading" | "live" | "closed" | "error";

// TS#8 — module-level constant; does not change between renders
const AUTO_ROUTE_KEY = "jarvis-anki-auto-route-shown-v1";

export function AnkiStatsWidget() {
  const [tab, setTab] = useState<Tab>("stats");
  const [stats, setStats] = useState<AnkiStats | null>(null);
  const [liveStatus, setLiveStatus] = useState<LiveStatus>("loading");
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Suggested tab state
  const [suggestions, setSuggestions] = useState<AnkiSuggestion[]>([]);
  const [suggestionsAvailable, setSuggestionsAvailable] = useState<
    boolean | null
  >(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    const load = () => {
      fetchAnkiStats()
        .then((data) => {
          if (data.error || data.available === false) {
            setFetchError(data.error ?? "Anki not connected");
            setLiveStatus("error");
            return;
          }

          const due = data.due ?? 0;
          const reviewedToday = data.reviewedToday ?? 0;
          const streak = data.streak ?? 0;
          const retention = data.retention ?? 0;
          const learning = data.learning ?? 0;
          const suspended = data.suspended ?? 0;
          const availableTotal = data.available_total ?? 0;
          const suggestedCount = data.suggested_count ?? 0;

          // Detect Anki actually closed (vs. user just having all cards
          // suspended). The old "all zeros = closed" heuristic was wrong:
          // an AnKing user with 43k suspended cards legitimately has 0 due
          // and 0 reviewed today. Now we check `suspended` — if it's > 0
          // then AnkiConnect IS reading the collection, the user just
          // doesn't have any active.
          const ankiClosed =
            data.available === true &&
            due === 0 &&
            reviewedToday === 0 &&
            streak === 0 &&
            retention === 0 &&
            suspended === 0 &&
            learning === 0;

          if (ankiClosed) {
            setLiveStatus("closed");
            setStats({
              due: 0,
              reviewedToday: 0,
              newCards: data.newCards ?? 0,
              streak: 0,
              retention: 0,
              learning: 0,
              suspended: 0,
              available_total: 0,
              suggested_count: 0,
            });
            return;
          }

          setStats({
            due,
            reviewedToday,
            newCards: data.newCards ?? 0,
            streak,
            retention,
            learning,
            suspended,
            available_total: availableTotal,
            suggested_count: suggestedCount,
          });
          setLiveStatus("live");
          setFetchError(null);
        })
        .catch(() => {
          setFetchError("Backend offline");
          setLiveStatus("error");
        });
    };
    load();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 60_000);
    return () => {
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadSuggestions = useCallback(async () => {
    setSuggestionsLoading(true);
    setSuggestionsError(null);
    try {
      const data = await fetchAnkiSuggestions();
      setSuggestions(data.suggestions ?? []);
      setSuggestionsAvailable(!!data.available);
      if (data.error) setSuggestionsError(data.error);
    } catch (e) {
      setSuggestionsAvailable(false);
      setSuggestionsError(
        e instanceof Error ? e.message : "Failed to load suggestions"
      );
    } finally {
      setSuggestionsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "suggested" && suggestionsAvailable === null) {
      loadSuggestions();
    }
  }, [tab, suggestionsAvailable, loadSuggestions]);

  const toggleSelected = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Re-run the full UWorld → Anki suggestion pipeline. Use case: user
  // just finished a UWorld exam, wants to see the freshly-missed cards
  // surfaced for unsuspend without restarting the backend.
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineMsg, setPipelineMsg] = useState<string | null>(null);
  // Timer refs so we can clear them on unmount and avoid a state update on an
  // already-unmounted component (which logs a React warning and is a leak).
  const pipelineMsgTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    return () => {
      if (pipelineMsgTimerRef.current !== null) clearTimeout(pipelineMsgTimerRef.current);
      if (toastTimerRef.current !== null) clearTimeout(toastTimerRef.current);
    };
  }, []);
  const handleRefreshPipeline = useCallback(async () => {
    if (pipelineRunning) return;
    setPipelineRunning(true);
    setPipelineMsg("Scraping UWorld history…");
    try {
      // Step 1: rescrape UWorld so uworld_history.json reflects today's exam.
      try {
        await refreshUWorld();
      } catch (e) {
        // Don't block on UWorld scrape failures — it's the slowest step
        // and may need browser focus. The user can still rebuild the
        // Anki index against existing scrape data.
        setPipelineMsg(`UWorld scrape skipped (${e instanceof Error ? e.message : "error"}); continuing…`);
      }

      // Step 2: kick off the Anki QID index rebuild (background thread on backend).
      setPipelineMsg("Re-indexing Anki cards…");
      await rebuildAnkiQidIndex();

      // Step 3: poll status until done (or 60s budget).
      const startedAt = Date.now();
      while (Date.now() - startedAt < 60_000) {
        await new Promise((r) => setTimeout(r, 1500));
        try {
          const s = await getAnkiBuildIndexStatus();
          if (!s.running) break;
          if (s.total > 0) {
            setPipelineMsg(`Indexing… ${s.percent}% (${s.progress}/${s.total})`);
          }
        } catch {
          break;
        }
      }

      // Step 4: re-fetch suggestions so the panel reflects the new index.
      setPipelineMsg("Loading suggestions…");
      await loadSuggestions();
      setPipelineMsg("Refreshed.");
    } catch (e) {
      setPipelineMsg(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setPipelineRunning(false);
      if (pipelineMsgTimerRef.current !== null) clearTimeout(pipelineMsgTimerRef.current);
      pipelineMsgTimerRef.current = setTimeout(() => setPipelineMsg(null), 4000);
    }
  }, [pipelineRunning, loadSuggestions]);

  const handleUnsuspend = async () => {
    if (selected.size === 0) return;
    setSubmitting(true);
    try {
      const ids = Array.from(selected);
      const res = await unsuspendAnkiCards(ids);
      if (res.errors && res.errors.length > 0) {
        setToast(
          `Unsuspended ${res.unsuspended}. Errors: ${res.errors.join("; ")}`
        );
      } else {
        setToast(
          `Unsuspended ${res.unsuspended} card${res.unsuspended === 1 ? "" : "s"}`
        );
      }
      setSelected(new Set());
      await loadSuggestions();
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Unsuspend failed");
    } finally {
      setSubmitting(false);
      if (toastTimerRef.current !== null) clearTimeout(toastTimerRef.current);
      toastTimerRef.current = setTimeout(() => setToast(null), 4000);
    }
  };

  const due = stats?.due ?? 0;
  const reviewedToday = stats?.reviewedToday ?? 0;
  const streak = stats?.streak ?? 0;
  const newCards = stats?.newCards ?? 0;
  const retention = stats?.retention ?? 0;
  const learning = stats?.learning ?? 0;
  const suspended = stats?.suspended ?? 0;
  const availableTotal = stats?.available_total ?? 0;
  const suggestedCount = stats?.suggested_count ?? 0;

  // "All cards suspended" state: collection has cards but none are
  // unsuspended. Common for AnKing-style workflows where you only
  // unsuspend cards encountered in UWorld.
  const allSuspended =
    suspended > 0 && availableTotal === 0 && due === 0 && learning === 0;
  // First-ever-load auto-route hint. Was previously running on EVERY page
  // reload (autoRouteRef is per-mount), permanently burying the Stats view
  // for any user with no due cards. Now: persist a one-time flag in
  // localStorage so the auto-route fires at most once across all sessions.
  const autoRouteRef = useRef(false);
  useEffect(() => {
    if (autoRouteRef.current) return;
    if (liveStatus !== "live") return;
    let alreadyShown = false;
    try { alreadyShown = localStorage.getItem(AUTO_ROUTE_KEY) === "1"; } catch { /* ignore */ }
    if (alreadyShown) {
      autoRouteRef.current = true;
      return;
    }
    if (due === 0 && suggestedCount > 0) {
      autoRouteRef.current = true;
      try { localStorage.setItem(AUTO_ROUTE_KEY, "1"); } catch { /* ignore */ }
      setTab("suggested");
    } else if (due > 0) {
      autoRouteRef.current = true;
      try { localStorage.setItem(AUTO_ROUTE_KEY, "1"); } catch { /* ignore */ }
    }
  }, [liveStatus, due, suggestedCount]);
  // When due=0 and reviewedToday>0, the session is done → 100%.
  // When both are 0 (no activity), stay at 0%.
  const progressPct =
    due > 0
      ? Math.min(100, Math.round((reviewedToday / (due + reviewedToday)) * 100))
      : reviewedToday > 0
        ? 100
        : 0;

  const contentRef = useRef<HTMLDivElement>(null);
  const container = useContainerSize(contentRef);
  const isWide = container.width > 400;
  const isTall = container.height > 300;
  const isVeryLarge = container.width > 400 && container.height > 350;
  const dueSize = isTall ? "text-7xl" : "text-5xl";

  // Live indicator dot + label
  const LiveDot = () => {
    if (liveStatus === "loading") return <span className="sr-only">loading</span>;
    if (liveStatus === "live") {
      // Cards in the learning queue count as activity too — the user has
      // in-progress reviews. Without this, a user studying actively (21
      // cards in learning steps, due=0 because they're between intervals)
      // sees a misleading "no recent activity" indicator.
      const hasActivity = due > 0 || reviewedToday > 0 || learning > 0;
      if (hasActivity) {
        return (
          <>
            <span
              className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block"
              title="Live data"
            />
            <span className="sr-only">live</span>
          </>
        );
      }
      return (
        <>
          <span
            className="h-1.5 w-1.5 rounded-full bg-amber-400 inline-block"
            title="No recent activity"
          />
          <span className="text-[10px] normal-case font-normal text-muted-foreground/60">
            no recent activity
          </span>
          <span className="sr-only">loading</span>
        </>
      );
    }
    if (liveStatus === "closed") {
      return (
        <>
          <span
            className="h-1.5 w-1.5 rounded-full bg-amber-400 inline-block"
            title="Anki appears to be closed"
          />
          <span className="text-[10px] normal-case font-normal text-muted-foreground/60">
            closed
          </span>
          <span className="sr-only">loading</span>
        </>
      );
    }
    // error
    return (
      <>
        <span
          className="h-1.5 w-1.5 rounded-full bg-red-400 inline-block"
          title={fetchError ?? "Anki not reachable"}
        />
        <span className="text-[10px] normal-case font-normal text-muted-foreground/60">
          not reachable
        </span>
        <span className="sr-only">error</span>
      </>
    );
  };

  return (
    <Card className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card hover:border-foreground/15 transition-colors">
      <CardHeader className="p-5 pb-2">
        <CardTitle className="text-[13px] font-semibold tracking-[-0.02em] text-muted-foreground flex items-center gap-2">
          Anki
          <LiveDot />
        </CardTitle>
        <div className="mt-2 flex gap-1 text-xs">
          <button
            onClick={() => setTab("stats")}
            className={`px-2.5 py-1 rounded-md transition-colors ${
              tab === "stats"
                ? "bg-foreground/10 text-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-foreground/5"
            }`}
          >
            Stats
          </button>
          <button
            onClick={() => setTab("suggested")}
            className={`px-2.5 py-1 rounded-md transition-colors ${
              tab === "suggested"
                ? "bg-foreground/10 text-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-foreground/5"
            }`}
          >
            Suggested
          </button>
        </div>
      </CardHeader>

      <CardContent
        ref={contentRef}
        className="flex-1 min-h-0 p-5 pt-2 flex flex-col relative"
      >
        {tab === "stats" ? (
          <>
            {/* Loading skeleton */}
            {stats === null && (
              <div className="grid grid-cols-2 gap-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-16 animate-pulse rounded-md bg-muted/40"
                  />
                ))}
              </div>
            )}

            {/* Anki-closed overlay */}
            {liveStatus === "closed" && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-b-xl bg-card/90 backdrop-blur-sm text-center px-6 gap-2">
                <div className="text-sm font-medium text-foreground/80">
                  Anki is closed
                </div>
                <div className="text-xs text-muted-foreground">
                  Open Anki to see live stats
                </div>
              </div>
            )}

            <div className="flex-1 min-h-0 flex flex-col justify-between">
              <div className="text-center py-4">
                <div
                  className={`${dueSize} font-bold tabular-nums leading-none`}
                >
                  {due}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  cards due
                </div>
                <div className="mt-1.5 text-[11px] text-muted-foreground/70">
                  {reviewedToday} reviewed &middot; {learning} learning &middot; {newCards} new
                </div>
                {/* Real-state context: explain why due=0 when relevant. */}
                {allSuspended && (
                  <div className="mt-1.5 text-[10px] text-amber-300/80">
                    all {suspended.toLocaleString()} cards suspended
                  </div>
                )}
                {/* Suggested-cards CTA — prominent when due is empty. */}
                {suggestedCount > 0 && (
                  <button
                    type="button"
                    onClick={() => setTab("suggested")}
                    className={
                      "mt-2 inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-colors " +
                      (due === 0
                        ? "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 border border-emerald-500/30"
                        : "text-muted-foreground/70 hover:text-foreground hover:bg-foreground/5")
                    }
                    title="Open the Suggested tab to unsuspend UWorld-mapped cards"
                  >
                    {suggestedCount} suggested {suggestedCount === 1 ? "card" : "cards"} to unsuspend →
                  </button>
                )}
                {isVeryLarge && liveStatus === "live" && (
                  <div className="mt-1 text-[10px] text-muted-foreground/50">
                    live from AnkiConnect
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <div className="relative h-3 w-full overflow-hidden rounded-full bg-foreground/5">
                  <div
                    className={`h-full rounded-full bg-gradient-to-r ${progressGradient(progressPct)} transition-all duration-500`}
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{reviewedToday} reviewed</span>
                  <span>{progressPct}%</span>
                </div>
              </div>

              <div
                className={`${
                  isWide ? "flex justify-evenly" : "grid grid-cols-3 gap-4"
                } pt-4 border-t border-foreground/5 mt-4`}
              >
                <div className="text-center">
                  <div className="text-base font-semibold tabular-nums text-amber-400">
                    {streak}
                  </div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    streak
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-base font-semibold tabular-nums">
                    {newCards}
                  </div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    new
                  </div>
                </div>
                <div className="text-center">
                  <div
                    className={`text-base font-semibold tabular-nums ${retentionColor(retention)}`}
                  >
                    {retention}%
                  </div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    retention
                  </div>
                </div>
              </div>
            </div>
          </>
        ) : (
          <SuggestedPanel
            suggestions={suggestions}
            available={suggestionsAvailable}
            loading={suggestionsLoading}
            error={suggestionsError}
            selected={selected}
            onToggle={toggleSelected}
            onUnsuspend={handleUnsuspend}
            submitting={submitting}
            toast={toast}
            onRefresh={loadSuggestions}
            onRefreshPipeline={handleRefreshPipeline}
            pipelineRunning={pipelineRunning}
            pipelineMsg={pipelineMsg}
          />
        )}
      </CardContent>
    </Card>
  );
}

function SuggestedPanel(props: {
  suggestions: AnkiSuggestion[];
  available: boolean | null;
  loading: boolean;
  error: string | null;
  selected: Set<number>;
  onToggle: (id: number) => void;
  onUnsuspend: () => void;
  submitting: boolean;
  toast: string | null;
  onRefresh: () => void;
  onRefreshPipeline: () => void;
  pipelineRunning: boolean;
  pipelineMsg: string | null;
}) {
  const {
    suggestions,
    available,
    loading,
    error,
    selected,
    onToggle,
    onUnsuspend,
    submitting,
    toast,
    onRefresh,
    onRefreshPipeline,
    pipelineRunning,
    pipelineMsg,
  } = props;

  if (loading && suggestions.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground">
        Loading suggestions...
      </div>
    );
  }

  if (available === false) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-xs text-muted-foreground text-center gap-2 p-4">
        <div>AnkiConnect not reachable.</div>
        {error && (
          <div className="text-[10px] text-muted-foreground/60">{error}</div>
        )}
        <button
          onClick={onRefresh}
          className="mt-2 text-xs underline text-muted-foreground hover:text-foreground"
        >
          retry
        </button>
      </div>
    );
  }

  if (suggestions.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-xs text-muted-foreground text-center gap-2 p-4">
        <div className="text-sm text-foreground/80">
          No UWorld incorrect cards yet
        </div>
        <div className="text-[11px] text-muted-foreground/70">
          Connect the UWorld scraper (coming soon) to see suspended cards tied
          to questions you missed.
        </div>
        <button
          onClick={onRefresh}
          className="mt-2 text-xs underline text-muted-foreground hover:text-foreground"
        >
          refresh
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Refresh-pipeline header — re-run UWorld scrape + Anki index
          rebuild + suggestion fetch. Use after a new exam. */}
      <div className="mb-2 flex items-center justify-between gap-2 text-[11px]">
        <span className="text-muted-foreground/70">
          {suggestions.length} suggested
        </span>
        <div className="flex items-center gap-2">
          {pipelineMsg && (
            <span className="text-muted-foreground/70 truncate max-w-[180px]" title={pipelineMsg}>
              {pipelineMsg}
            </span>
          )}
          <button
            onClick={onRefreshPipeline}
            disabled={pipelineRunning}
            title="Rescrape UWorld + rebuild Anki index"
            className={`rounded-md px-2 py-1 text-[11px] transition-colors ${
              pipelineRunning
                ? "bg-foreground/5 text-muted-foreground cursor-wait"
                : "bg-foreground/5 hover:bg-foreground/10 text-foreground/80"
            }`}
          >
            {pipelineRunning ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto space-y-1 pr-1">
        {suggestions.map((s) => {
          const checked = selected.has(s.card_id);
          return (
            <label
              key={s.card_id}
              className={`flex items-start gap-2 px-2.5 py-2 rounded-md cursor-pointer border transition-colors ${
                checked
                  ? "bg-emerald-500/10 border-emerald-500/30"
                  : "bg-foreground/[0.02] border-foreground/5 hover:bg-foreground/[0.04]"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(s.card_id)}
                className="mt-0.5 accent-emerald-500 shrink-0"
              />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium truncate">
                  {s.front || (
                    <span className="text-muted-foreground italic">
                      (no preview)
                    </span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                  {s.tag && (
                    <span className="px-1.5 py-0.5 rounded bg-foreground/5 text-[10px]">
                      {s.tag}
                    </span>
                  )}
                  <span className="truncate">
                    UW {s.uworld_qid}: {s.uworld_topic}
                  </span>
                  {s.missed_at && (
                    <span className="text-muted-foreground/60">
                      &middot; missed {s.missed_at}
                    </span>
                  )}
                </div>
              </div>
            </label>
          );
        })}
      </div>

      {toast && (
        <div className="mt-2 text-xs text-emerald-400 text-center">{toast}</div>
      )}

      <div className="pt-3 mt-2 border-t border-foreground/5">
        <button
          onClick={onUnsuspend}
          disabled={selected.size === 0 || submitting}
          className={`w-full py-2 rounded-md text-xs font-medium transition-colors flex items-center justify-center gap-2 ${
            selected.size === 0 || submitting
              ? "bg-foreground/5 text-muted-foreground cursor-not-allowed"
              : "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30"
          }`}
        >
          {submitting ? (
            "Unsuspending..."
          ) : (
            <>
              Unsuspend
              {selected.size > 0 && (
                <span className="px-1.5 py-0.5 rounded-full bg-emerald-500/30 text-emerald-200 text-[10px] font-semibold leading-none">
                  {selected.size}
                </span>
              )}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
