import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { useEffect, useState } from "react";
import { fetchAnkiSuggestions } from "@/lib/api";
import { openInApp } from "@/lib/open-apps";

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

function SessionList({ sessions }: { sessions: any[] }) {
  return (
    <div className="space-y-1">
      {sessions.map((s) => (
        <div
          key={s.id}
          className="flex items-center justify-between rounded-lg px-3 py-2.5 hover:bg-white/5 transition-colors"
        >
          <div className="space-y-0.5">
            <div className="text-sm font-medium">{s.topics.join(", ")}</div>
            <div className="text-xs text-muted-foreground/60">{s.date}</div>
          </div>
          <div className="text-right">
            <div className="text-sm font-semibold tabular-nums">
              {s.score}%
            </div>
            <div className="text-xs text-muted-foreground/60">
              {s.correct}/{s.total}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function WeakTopicsSection({ topics }: { topics: any[] }) {
  if (topics.length === 0) return null;
  return (
    <div className="mt-4 space-y-3 border-t border-white/5 pt-4">
      <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
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

export function UWorldWidget() {
  const [qbankSessions, setQbankSessions] = useState<any[]>([]);
  const [weakTopics, setWeakTopics] = useState<any[]>([]);
  const [launching, setLaunching] = useState(false);

  const handleLaunchUWorld = async () => {
    setLaunching(true);
    try {
      await openInApp({ app: "uworld", ref: "" });
    } catch (error) {
      console.error("Failed to launch UWorld:", error);
    } finally {
      setLaunching(false);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchAnkiSuggestions();
        if (data.suggestions && Array.isArray(data.suggestions)) {
          // Count occurrences per topic/tag to calculate "percent wrong"
          const topicMap: { [key: string]: number } = {};
          for (const suggestion of data.suggestions) {
            const topic = suggestion.uworld_topic || suggestion.tag || "Unknown";
            topicMap[topic] = (topicMap[topic] || 0) + 1;
          }
          // Convert to array with scores (count as a proxy for error rate)
          const topicsArray = Object.entries(topicMap).map(([topic, count]) => ({
            topic,
            score: Math.min(100, count * 10), // Scale count to a percentage-like score
            trend: "declining" as const,
          }));
          setWeakTopics(topicsArray);
        }
        // qbankSessions remains empty since there's no UWorld session data yet
        setQbankSessions([]);
      } catch (e) {
        // On fetch failure, leave empty state as-is (correct behavior)
        console.error("Failed to fetch Anki suggestions:", e);
      }
    })();
  }, []);

  const hasData = qbankSessions.length > 0 || weakTopics.length > 0;

  return (
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-5 pb-3 flex flex-row items-center justify-between">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          QBank
        </CardTitle>
        <Button
          onClick={handleLaunchUWorld}
          disabled={launching}
          variant="ghost"
          size="xs"
          className="cursor-pointer"
        >
          {launching ? "Opening..." : "Launch UWorld"}
        </Button>
      </CardHeader>
      <CardContent className="flex-1 min-h-0 p-5 pt-0">
        {!hasData ? (
          <div className="flex flex-col items-center justify-center gap-4 py-8 text-center">
            <div>
              <p className="text-sm text-muted-foreground">No UWorld data yet</p>
              <p className="text-xs text-muted-foreground/70">Log incorrects from a UWorld block to get started</p>
            </div>
            <Button
              onClick={handleLaunchUWorld}
              disabled={launching}
              variant="default"
              size="sm"
              className="cursor-pointer"
            >
              {launching ? "Opening..." : "Open UWorld"}
            </Button>
          </div>
        ) : qbankSessions.length === 0 && weakTopics.length > 0 ? (
          <ScrollArea className="flex-1 min-h-0">
            <WeakTopicsSection topics={weakTopics} />
          </ScrollArea>
        ) : (
          <Tabs defaultValue="uworld">
            <TabsList className="mb-3 bg-white/5 border border-white/5">
              <TabsTrigger value="uworld" className="text-xs data-[state=active]:bg-white/10">
                UWorld
              </TabsTrigger>
              <TabsTrigger value="truelearn" className="text-xs data-[state=active]:bg-white/10">
                TrueLearn
              </TabsTrigger>
            </TabsList>
            <TabsContent value="uworld">
              <ScrollArea className="flex-1 min-h-0">
                <SessionList sessions={qbankSessions.filter((s) => s.platform === "uworld")} />
                <WeakTopicsSection topics={weakTopics} />
              </ScrollArea>
            </TabsContent>
            <TabsContent value="truelearn">
              <ScrollArea className="flex-1 min-h-0">
                <SessionList sessions={qbankSessions.filter((s) => s.platform === "truelearn")} />
                <WeakTopicsSection topics={weakTopics} />
              </ScrollArea>
            </TabsContent>
          </Tabs>
        )}
      </CardContent>
    </Card>
  );
}
