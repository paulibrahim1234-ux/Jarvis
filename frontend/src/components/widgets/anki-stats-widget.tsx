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

          // Backend bug: returns available:true with all zeros when Anki is closed
          const ankiClosed =
            data.available === true &&
            due === 0 &&
            reviewedToday === 0 &&
            streak === 0 &&
            retention === 0;

          if (ankiClosed) {
            setLiveStatus("closed");
            // still update stats to zeros so the display is consistent
            setStats({
              due: 0,
              reviewedToday: 0,
              newCards: data.newCards ?? 0,
              streak: 0,
              retention: 0,
            });
            return;
          }

          setStats({
            due,
            reviewedToday,
            newCards: data.newCards ?? 0,
            streak,
            retention,
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
      setTimeout(() => setToast(null), 4000);
    }
  };

  const due = stats?.due ?? 0;
  const reviewedToday = stats?.reviewedToday ?? 0;
  const streak = stats?.streak ?? 0;
  const newCards = stats?.newCards ?? 0;
  const retention = stats?.retention ?? 0;
  const progressPct =
    due > 0 ? Math.min(100, Math.round((reviewedToday / due) * 100)) : 0;

  const contentRef = useRef<HTMLDivElement>(null);
  const container = useContainerSize(contentRef);
  const isWide = container.width > 400;
  const isTall = container.height > 300;
  const isVeryLarge = container.width > 400 && container.height > 350;
  const dueSize = isTall ? "text-7xl" : "text-5xl";

  // Live indicator dot + label
  const LiveDot = () => {
    if (liveStatus === "loading") return null;
    if (liveStatus === "live") {
      const hasActivity = due > 0 || reviewedToday > 0;
      if (hasActivity) {
        return (
          <span
            className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block"
            title="Live data"
          />
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
      </>
    );
  };

  return (
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-5 pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          Anki
          <LiveDot />
        </CardTitle>
        <div className="mt-2 flex gap-1 text-xs">
          <button
            onClick={() => setTab("stats")}
            className={`px-2.5 py-1 rounded-md transition-colors ${
              tab === "stats"
                ? "bg-white/10 text-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-white/5"
            }`}
          >
            Stats
          </button>
          <button
            onClick={() => setTab("suggested")}
            className={`px-2.5 py-1 rounded-md transition-colors ${
              tab === "suggested"
                ? "bg-white/10 text-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-white/5"
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
                  {due} due now &middot; {newCards} new today
                </div>
                {isVeryLarge && liveStatus === "live" && (
                  <div className="mt-1 text-[10px] text-muted-foreground/50">
                    live from AnkiConnect
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <div className="relative h-3 w-full overflow-hidden rounded-full bg-white/5">
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
                } pt-4 border-t border-white/5 mt-4`}
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
      <div className="flex-1 min-h-0 overflow-y-auto space-y-1 pr-1">
        {suggestions.map((s) => {
          const checked = selected.has(s.card_id);
          return (
            <label
              key={s.card_id}
              className={`flex items-start gap-2 px-2.5 py-2 rounded-md cursor-pointer border transition-colors ${
                checked
                  ? "bg-emerald-500/10 border-emerald-500/30"
                  : "bg-white/[0.02] border-white/5 hover:bg-white/[0.04]"
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
                    <span className="px-1.5 py-0.5 rounded bg-white/5 text-[10px]">
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

      <div className="pt-3 mt-2 border-t border-white/5">
        <button
          onClick={onUnsuspend}
          disabled={selected.size === 0 || submitting}
          className={`w-full py-2 rounded-md text-xs font-medium transition-colors flex items-center justify-center gap-2 ${
            selected.size === 0 || submitting
              ? "bg-white/5 text-muted-foreground cursor-not-allowed"
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
