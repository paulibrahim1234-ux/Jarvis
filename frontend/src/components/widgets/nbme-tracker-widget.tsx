"use client";

import { useEffect, useState } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  LabelList,
} from "recharts";
import {
  fetchNBME,
  postNBMEScore,
  deleteNBMEScore,
  type NBMEScore,
} from "@/lib/api";

const EXAM_PRESETS = [
  "NBME 28",
  "NBME 29",
  "NBME 30",
  "NBME 31",
  "UWSA 1",
  "UWSA 2",
  "CMS Surgery",
  "CMS IM",
  "CMS Peds",
  "CMS OB",
  "CMS Psych",
  "Other...",
];

type DraftState = {
  exam_name: string;
  custom_exam_name: string;
  date_taken: string;
  raw_score: string;
  percentile: string;
  notes: string;
};

const EMPTY_DRAFT: DraftState = {
  exam_name: "NBME 28",
  custom_exam_name: "",
  date_taken: new Date().toISOString().slice(0, 10),
  raw_score: "",
  percentile: "",
  notes: "",
};

/** Format "2024-04-17" -> "Apr 17" */
function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

type ChartEntry = {
  label: string;
  score: number;
  percentile: number | null;
  date: string;
  exam: string;
};

type CustomTooltipProps = {
  active?: boolean;
  payload?: Array<{ payload: ChartEntry }>;
};

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div
      style={{
        backgroundColor: "hsl(var(--card))",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 12,
        boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
      }}
    >
      <div style={{ color: "hsl(var(--foreground))", fontWeight: 600 }}>{d.exam}</div>
      <div style={{ color: "#10b981", marginTop: 2 }}>
        Score: <strong>{d.score}</strong>
        {d.percentile != null && (
          <span style={{ color: "hsl(var(--muted-foreground))", marginLeft: 6 }}>
            ({d.percentile}th %ile)
          </span>
        )}
      </div>
      <div style={{ color: "hsl(var(--muted-foreground))", marginTop: 2 }}>{fmtDate(d.date)}</div>
    </div>
  );
}

export function NBMETrackerWidget() {
  const [scores, setScores] = useState<NBMEScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const [draft, setDraft] = useState<DraftState>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const loadScores = async () => {
    try {
      const data = await fetchNBME();
      setScores(data.scores ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadScores();
  }, []);

  const sortedAsc = [...scores].sort((a, b) => a.date_taken.localeCompare(b.date_taken));
  const chartData: ChartEntry[] = sortedAsc.map((s) => ({
    label: fmtDate(s.date_taken),
    score: s.raw_score,
    percentile: s.percentile,
    date: s.date_taken,
    exam: s.exam_name,
  }));

  const latest = chartData.length > 0 ? chartData[chartData.length - 1] : null;
  const sortedDesc = [...scores].sort((a, b) => b.date_taken.localeCompare(a.date_taken));
  const recentList = showAll ? sortedDesc : sortedDesc.slice(0, 5);

  const resetForm = () => {
    setDraft(EMPTY_DRAFT);
    setIsAdding(false);
  };

  const handleSave = async () => {
    const exam_name =
      draft.exam_name === "Other..." ? draft.custom_exam_name.trim() : draft.exam_name;
    if (!exam_name) {
      setError("Exam name is required");
      return;
    }
    const raw = parseFloat(draft.raw_score);
    if (Number.isNaN(raw)) {
      setError("Score must be a number");
      return;
    }
    const pct = draft.percentile.trim() === "" ? null : parseFloat(draft.percentile);
    if (pct !== null && Number.isNaN(pct)) {
      setError("Percentile must be a number");
      return;
    }
    setSaving(true);
    try {
      const created = await postNBMEScore({
        exam_name,
        date_taken: draft.date_taken,
        raw_score: raw,
        percentile: pct,
        notes: draft.notes.trim() === "" ? null : draft.notes.trim(),
      });
      setScores((prev) => [...prev, created]);
      resetForm();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (pendingDelete !== id) {
      setPendingDelete(id);
      return;
    }
    try {
      await deleteNBMEScore(id);
      setScores((prev) => prev.filter((s) => s.id !== id));
      setPendingDelete(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  // y-domain: 200-300 default NBME range, auto-expand if data is outside
  let yDomain: [number, number] = [200, 300];
  if (chartData.length > 0) {
    const vals = chartData.map((d) => d.score);
    const lo = Math.min(200, Math.min(...vals) - 10);
    const hi = Math.max(300, Math.max(...vals) + 10);
    yDomain = [lo, hi];
  }

  return (
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-5 pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            NBME Progress
          </CardTitle>
          <div className="flex items-center gap-3">
            {latest && (
              <div className="flex items-baseline gap-1.5">
                <span className="text-3xl font-bold tabular-nums text-emerald-400">
                  {latest.score}
                </span>
                {latest.percentile != null && (
                  <span className="text-xs text-muted-foreground">
                    {latest.percentile}th %ile
                  </span>
                )}
              </div>
            )}
            <button
              onClick={() => setIsAdding((v) => !v)}
              className="text-xs px-2 py-1 rounded-md border border-white/10 hover:border-white/30 hover:bg-white/5 text-muted-foreground transition-colors"
            >
              {isAdding ? "Cancel" : "+ Add"}
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex-1 min-h-0 p-5 pt-0 space-y-3 overflow-y-auto">
        {isAdding && (
          <div className="rounded-lg border border-white/10 bg-black/20 p-3 space-y-2 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-muted-foreground">Exam</span>
                <select
                  value={draft.exam_name}
                  onChange={(e) =>
                    setDraft({ ...draft, exam_name: e.target.value })
                  }
                  className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs"
                >
                  {EXAM_PRESETS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                {draft.exam_name === "Other..." && (
                  <input
                    type="text"
                    placeholder="Custom exam name"
                    value={draft.custom_exam_name}
                    onChange={(e) =>
                      setDraft({ ...draft, custom_exam_name: e.target.value })
                    }
                    className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs mt-1"
                  />
                )}
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-muted-foreground">Date</span>
                <input
                  type="date"
                  value={draft.date_taken}
                  onChange={(e) =>
                    setDraft({ ...draft, date_taken: e.target.value })
                  }
                  className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-muted-foreground">Score</span>
                <input
                  type="number"
                  min={0}
                  max={800}
                  value={draft.raw_score}
                  onChange={(e) =>
                    setDraft({ ...draft, raw_score: e.target.value })
                  }
                  className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-muted-foreground">Percentile (opt)</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={draft.percentile}
                  onChange={(e) =>
                    setDraft({ ...draft, percentile: e.target.value })
                  }
                  className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs"
                />
              </label>
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-muted-foreground">Notes (opt)</span>
              <textarea
                rows={2}
                value={draft.notes}
                onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
                className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs resize-none"
              />
            </label>
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={resetForm}
                className="px-3 py-1 rounded-md border border-white/10 hover:border-white/30 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1 rounded-md bg-emerald-600/80 hover:bg-emerald-500 text-white text-xs disabled:opacity-50"
              >
                {saving ? "Saving..." : "Add score"}
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="text-xs text-red-400 border border-red-500/30 rounded px-2 py-1">
            {error}
          </div>
        )}

        <div className="w-full" style={{ height: 140 }}>
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
              Loading...
            </div>
          ) : chartData.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center gap-4 border border-dashed border-white/10 rounded-lg px-4 text-center">
              <div className="text-sm text-muted-foreground leading-snug">
                Track your shelf scores here. Add your first NBME or UWSA score to start.
              </div>
              <button
                onClick={() => setIsAdding(true)}
                className="px-5 py-2.5 rounded-md bg-emerald-600/80 hover:bg-emerald-500 text-white text-sm font-medium transition-colors"
              >
                + Add score
              </button>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={140}>
              <AreaChart
                data={chartData}
                margin={{ top: 18, right: 12, left: -8, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="nbmeGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="rgba(255,255,255,0.05)"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  domain={yDomain}
                  tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                />
                <RechartsTooltip content={<CustomTooltip />} />
                <ReferenceLine
                  y={220}
                  stroke="#f59e0b"
                  strokeDasharray="6 4"
                  strokeWidth={1.5}
                  opacity={0.6}
                  label={{
                    value: "Passing",
                    position: "right",
                    fill: "#f59e0b",
                    fontSize: 11,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="score"
                  stroke="#10b981"
                  strokeWidth={2.5}
                  fill="url(#nbmeGradient)"
                  dot={{
                    r: 4,
                    fill: "#10b981",
                    stroke: "hsl(var(--card))",
                    strokeWidth: 2,
                  }}
                  activeDot={{
                    r: 6,
                    stroke: "#10b981",
                    strokeWidth: 2,
                    fill: "hsl(var(--card))",
                  }}
                >
                  <LabelList
                    dataKey="score"
                    position="top"
                    style={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
                  />
                </Area>
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {sortedDesc.length > 0 && (
          <div className="space-y-0.5">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
              Recent
            </div>
            {recentList.map((s) => (
              <div
                key={s.id}
                className="flex items-center gap-2 text-xs py-1 px-2 rounded hover:bg-white/5 group"
              >
                <span className="font-medium truncate min-w-0 flex-shrink">{s.exam_name}</span>
                <span className="text-muted-foreground shrink-0">&middot;</span>
                <span className="text-muted-foreground shrink-0 tabular-nums">{fmtDate(s.date_taken)}</span>
                <span className="text-muted-foreground shrink-0">&middot;</span>
                <span className="tabular-nums font-medium text-emerald-400 shrink-0">
                  {s.raw_score}
                  {s.percentile != null && (
                    <span className="text-muted-foreground font-normal">
                      {" "}({s.percentile}%ile)
                    </span>
                  )}
                </span>
                <div className="flex-1" />
                <button
                  onClick={() => handleDelete(s.id)}
                  onBlur={() => setPendingDelete(null)}
                  className={`text-xs px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity shrink-0 ${
                    pendingDelete === s.id
                      ? "bg-red-600/80 text-white opacity-100"
                      : "text-muted-foreground hover:text-red-400"
                  }`}
                  title={pendingDelete === s.id ? "Click again to confirm" : "Delete"}
                >
                  {pendingDelete === s.id ? "Confirm?" : "x"}
                </button>
              </div>
            ))}
            {sortedDesc.length > 5 && (
              <button
                onClick={() => setShowAll((v) => !v)}
                className="text-[10px] text-muted-foreground hover:text-foreground px-2 py-1 transition-colors"
              >
                {showAll ? "Show less" : `Show all (${sortedDesc.length})`}
              </button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
