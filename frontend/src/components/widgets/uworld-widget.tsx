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
import {
  fetchUWorldData,
  refreshUWorld,
  fetchAnkiSuggestions,
  type UWorldSession,
  type UWorldWeakTopic,
  type UWorldIncorrect,
} from "@/lib/api";
import { openInApp } from "@/lib/open-apps";

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
  const [ankiLoading, setAnkiLoading] = useState(false);
  const [ankiMsg, setAnkiMsg] = useState<string | null>(null);

  // Filter wrong questions to this session by test_id
  const sessionWrong = session.test_id
    ? incorrects.filter((q) => q.test_id === session.test_id)
    : [];

  const groups = groupBySystem(sessionWrong);
  const hasData = session.test_id && sessionWrong.length > 0;

  // UWorld deep-link: use test results overview (no seq segment).
  // The /seq form (e.g. /results/{course}/{test_id}/0) only shows the
  // loading spinner because seq=0 doesn't resolve to a real question.
  // Dropping the segment lands on the test overview page correctly.
  const testResultsUrl = session.test_id
    ? `https://apps.uworld.com/courseapp/usmle/v50/en-US/performance/test/results/${COURSE_ID}/${session.test_id}`
    : null;

  const handleAnkiSuggest = async () => {
    setAnkiLoading(true);
    setAnkiMsg(null);
    try {
      // The /widgets/anki/suggestions endpoint pulls ALL incorrect QIDs —
      // there's no per-QID filter param yet. We call it and let the user
      // know how many total suggestions exist.
      // GAP: endpoint does not accept a qid_filter param; would need backend
      // change to filter to only this session's QIDs.
      const result = await fetchAnkiSuggestions();
      if (!result.available) {
        setAnkiMsg("Anki not reachable — is AnkiConnect running?");
      } else {
        const qids = sessionWrong.map((q) => q.uworld_qid);
        const sessionSuggestions = result.suggestions.filter((s) =>
          qids.includes(s.uworld_qid)
        );
        setAnkiMsg(
          sessionSuggestions.length > 0
            ? `${sessionSuggestions.length} suspended card${sessionSuggestions.length === 1 ? "" : "s"} found for this session`
            : "No suspended Anki cards matched for this session"
        );
      }
    } catch {
      setAnkiMsg("Error reaching Anki suggestions");
    } finally {
      setAnkiLoading(false);
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
    <div className="mt-1 mb-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-3 text-xs">
      {/* Header row */}
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
        <button
          onClick={onClose}
          className="text-muted-foreground/50 hover:text-muted-foreground transition-colors shrink-0 text-sm leading-none"
          aria-label="Collapse"
        >
          ×
        </button>
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
                  {testResultsUrl && (
                    <a
                      href={testResultsUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[10px] text-blue-400/80 hover:text-blue-400 transition-colors"
                      title="Opens test results overview — navigate to individual questions there"
                    >
                      Open in UWorld ↗
                    </a>
                  )}
                </div>
                <div className="space-y-0.5 pl-1">
                  {g.questions.map((q) => (
                    <div
                      key={q.uworld_qid}
                      className="flex items-center gap-2"
                    >
                      <span className="text-foreground/80">{q.uworld_topic_name || q.uworld_topic}</span>
                      <span className="text-muted-foreground/40 font-mono text-[10px] shrink-0">
                        #{q.uworld_qid}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Anki suggestions button */}
          <div className="mt-3 flex items-center gap-2">
            <Button
              variant="ghost"
              size="xs"
              className="text-xs h-6 px-2 text-amber-300/80 hover:text-amber-300"
              onClick={handleAnkiSuggest}
              disabled={ankiLoading}
            >
              {ankiLoading ? "Checking Anki..." : "Suggest Anki cards"}
            </Button>
            {ankiMsg && (
              <span className="text-[10px] text-muted-foreground/60">{ankiMsg}</span>
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
        className={`flex items-center justify-between rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
          isExpanded ? "bg-white/8 hover:bg-white/10" : "hover:bg-white/5"
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

  if (sessions.length === 0) {
    return (
      <p className="px-3 py-4 text-xs text-muted-foreground/60 text-center">
        No sessions logged yet
      </p>
    );
  }

  const toggle = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  return (
    <div className="space-y-1">
      {sessions.map((s) => (
        <SessionRow
          key={s.id}
          session={s}
          incorrects={incorrects}
          isExpanded={expandedId === s.id}
          onToggle={() => toggle(s.id)}
        />
      ))}
    </div>
  );
}

// ── Weak topics ───────────────────────────────────────────────────────────────

function WeakTopicsSection({ topics }: { topics: UWorldWeakTopic[] }) {
  if (topics.length === 0) return null;
  return (
    <div className="mt-4 space-y-3 border-t border-white/5 pt-4">
      <h4 className="text-[13px] font-semibold tracking-[-0.02em] text-muted-foreground">
        Weak Topics
      </h4>
      {topics.map((t) => (
        <div key={t.topic} className="space-y-1.5 rounded-lg px-3 py-2 hover:bg-white/5 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-sm">{t.topic}</span>
            <div className="flex items-center gap-1.5">
              <span className="text-sm tabular-nums font-medium">{t.score}%</span>
              <TrendIcon trend={t.trend} />
            </div>
          </div>
          <div className={`relative h-1.5 w-full overflow-hidden rounded-full ${scoreTrackColor(t.score)}`}>
            <div
              className={`h-full rounded-full ${scoreColor(t.score)} transition-all duration-500`}
              style={{ width: `${t.score}%` }}
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
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
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
        <div className={`mx-5 mb-2 rounded-md px-3 py-2 text-xs ${loggedOut ? "bg-amber-500/10 text-amber-300" : "bg-white/5 text-muted-foreground"}`}>
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
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground/60">
            Loading...
          </div>
        ) : !hasData ? (
          <div className="flex flex-col items-center justify-center gap-4 py-8 text-center">
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
          <Tabs defaultValue="uworld" className="flex-1 min-h-0 flex flex-col">
            <TabsList className="mb-3 bg-white/5 border border-white/5 shrink-0">
              <TabsTrigger value="uworld" className="text-xs data-[state=active]:bg-white/10">
                UWorld {uworldSessions.length > 0 && <span className="ml-1 text-muted-foreground/50">({uworldSessions.length})</span>}
              </TabsTrigger>
              <TabsTrigger value="truelearn" className="text-xs data-[state=active]:bg-white/10">
                TrueLearn
              </TabsTrigger>
            </TabsList>
            <TabsContent value="uworld" className="flex-1 min-h-0 mt-0">
              <ScrollArea className="h-full">
                <SessionList sessions={uworldSessions} incorrects={incorrects} />
                <WeakTopicsSection topics={weakTopics} />
              </ScrollArea>
            </TabsContent>
            <TabsContent value="truelearn" className="flex-1 min-h-0 mt-0">
              <ScrollArea className="h-full">
                <SessionList sessions={trueLearnSessions} incorrects={incorrects} />
              </ScrollArea>
            </TabsContent>
          </Tabs>
        )}
      </CardContent>
    </Card>
  );
}
