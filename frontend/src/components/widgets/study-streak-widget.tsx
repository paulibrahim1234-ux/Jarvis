"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";
import { fetchStudyStreak } from "@/lib/api";

/**
 * Study data sources (future backend integration):
 * - Anki review logs: time spent reviewing flashcards per day
 * - Pomodoro sessions: logged focus sessions (25-min blocks)
 * - UWorld / TrueLearn sessions: question-bank study time
 * - Manual entries: user-reported study time via this widget
 *
 * Interaction model (fast-edit UX):
 *  - Click a day               → cycle 60 → 90 → 120 → untouched (fast path)
 *  - Right-click a day         → mark explicit "no study" (0 min, distinct from untouched)
 *  - Shift+click or long-press → open detail popover for custom minutes
 *  - Reset icon in header      → wipe all study data (with confirm)
 *
 * Untouched vs no-study:
 *  - Untouched: minutes === null (cell rendered as blank/faint)
 *  - Explicit no-study: minutes === 0 (cell rendered as red-tinted)
 *  - Studied: minutes > 0 (colored by bucket)
 */

const STORAGE_KEY = "jarvis-study-streak-v1";
const LONG_PRESS_MS = 500;

type StudyMinutes = number | null;
interface DayRecord {
  date: string;
  minutes: StudyMinutes;
}

/**
 * 6-level color scale: null, 1-15, 16-30, 31-60, 61-120, 120+
 * Low-end: subtle outline ring so empty cells don't dominate visually.
 * High-end: vibrant green so good days really pop.
 */
function getColor(minutes: StudyMinutes): string {
  if (minutes === null) return "transparent"; // rendered with stroke only
  if (minutes === 0) return "rgba(239,68,68,0.25)"; // explicit no-study (red tint)
  if (minutes <= 15) return "#052e16";
  if (minutes <= 30) return "#14532d";
  if (minutes <= 60) return "#16a34a";
  if (minutes <= 120) return "#22c55e";
  return "#4ade80"; // >120 — vibrant pop
}

/** Returns true for null cells which get a faint ring instead of a fill */
function isUnset(minutes: StudyMinutes): boolean {
  return minutes === null;
}

const CELL = 12;
const GAP = 2;
const ROWS = 7;
const COLS = 52;

/** Popover for editing a single day's study minutes (shift+click / long-press path) */
function DayEditPopover({
  date,
  minutes,
  position,
  onChangeMinutes,
  onClose,
}: {
  date: string;
  minutes: StudyMinutes;
  position: { x: number; y: number };
  onChangeMinutes: (mins: StudyMinutes) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const displayMinutes = minutes ?? 0;

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  const adjust = (delta: number) => {
    onChangeMinutes(Math.max(0, Math.min(300, displayMinutes + delta)));
  };

  const formatted = new Date(date + "T00:00:00").toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  return (
    <div
      ref={ref}
      className="absolute z-50 rounded-lg border border-white/10 bg-zinc-900 p-3 shadow-xl"
      style={{
        left: position.x,
        top: position.y,
        transform: "translate(-50%, -100%) translateY(-8px)",
        minWidth: 180,
      }}
    >
      <div className="absolute left-1/2 -bottom-1.5 h-3 w-3 -translate-x-1/2 rotate-45 border-b border-r border-white/10 bg-zinc-900" />

      <div className="text-xs font-medium text-muted-foreground mb-2">
        {formatted}
      </div>

      <div className="flex items-center gap-2 mb-2">
        <button
          onClick={() => adjust(-15)}
          className="flex h-6 w-6 items-center justify-center rounded bg-white/5 text-xs font-bold text-muted-foreground hover:bg-white/10 transition-colors"
        >
          -
        </button>
        <div className="flex-1 text-center">
          <span className="text-sm font-bold tabular-nums">{displayMinutes}</span>
          <span className="text-xs text-muted-foreground ml-1">min</span>
        </div>
        <button
          onClick={() => adjust(15)}
          className="flex h-6 w-6 items-center justify-center rounded bg-white/5 text-xs font-bold text-muted-foreground hover:bg-white/10 transition-colors"
        >
          +
        </button>
      </div>

      <input
        type="range"
        min={0}
        max={300}
        step={5}
        value={displayMinutes}
        onChange={(e) => onChangeMinutes(Number(e.target.value))}
        className="w-full h-1 appearance-none rounded bg-white/10 accent-emerald-500 cursor-pointer mb-2
          [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-500"
      />

      <div className="flex gap-1.5">
        <button
          onClick={() => onChangeMinutes(null)}
          className={`flex-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
            minutes === null
              ? "bg-white/15 text-foreground"
              : "bg-white/5 text-muted-foreground hover:bg-white/10"
          }`}
        >
          Clear
        </button>
        <button
          onClick={() => onChangeMinutes(0)}
          className={`flex-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
            minutes === 0
              ? "bg-red-500/20 text-red-400"
              : "bg-white/5 text-muted-foreground hover:bg-white/10"
          }`}
        >
          No study
        </button>
        <button
          onClick={() => onChangeMinutes(60)}
          className={`flex-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
            (minutes ?? 0) > 0
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-white/5 text-muted-foreground hover:bg-white/10"
          }`}
        >
          Studied
        </button>
      </div>
    </div>
  );
}

/**
 * Cycle for single-click fast path.
 *
 *   null (untouched) -> 60 -> 90 -> 120 -> null
 *   0 (explicit no-study) -> null  (click ONCE undoes the no-study mark)
 */
function cycleMinutes(current: StudyMinutes): StudyMinutes {
  if (current === null) return 60;
  if (current === 0) return null; // undo no-study
  if (current < 90) return 90;
  if (current < 120) return 120;
  return null;
}

/** Format date as "Apr 17, 2026" */
function formatDate(dateStr: string): string {
  return new Date(dateStr + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Help icon that shows a popover on hover */
function HelpPopover() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        aria-label="Show interaction hints"
        className="flex h-5 w-5 items-center justify-center rounded-full border border-white/15 bg-white/5 text-[10px] text-muted-foreground hover:border-white/25 hover:text-foreground transition-colors"
      >
        ?
      </button>
      {open && (
        <div
          className="absolute right-0 top-6 z-50 rounded-lg border border-white/10 bg-zinc-900 p-2.5 shadow-xl text-[10px] text-muted-foreground leading-relaxed whitespace-nowrap"
          style={{ minWidth: 260 }}
        >
          <div>Click: cycle 60→90→120m (or clear if already no-study)</div>
          <div>Right-click: mark no study</div>
          <div>Shift-click: enter custom minutes</div>
          <div>Long-press (touch): enter custom minutes</div>
        </div>
      )}
    </div>
  );
}

export function StudyStreakWidget() {
  const [studyData, setStudyData] = useState<DayRecord[]>(() => {
    // Generate empty 364-day array for the past year (null = no data)
    const days: DayRecord[] = [];
    const today = new Date();
    for (let i = 363; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      const dateStr = d.toISOString().split("T")[0];
      days.push({ date: dateStr, minutes: null });
    }
    return days;
  });
  const [hydrated, setHydrated] = useState(false);
  const [dataSource, setDataSource] = useState<"mock" | "anki" | "manual">("mock");

  const [editingDay, setEditingDay] = useState<{
    index: number;
    position: { x: number; y: number };
  } | null>(null);

  const [confirmingReset, setConfirmingReset] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressFired = useRef(false);

  // On mount: (1) fetch Anki-derived baseline from backend, (2) layer
  // localStorage user overrides on top. localStorage wins per-day so manual
  // edits aren't clobbered by the next refresh.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let overrides: Record<string, StudyMinutes> = {};
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) overrides = JSON.parse(raw) as Record<string, StudyMinutes>;
      } catch {
        /* ignore malformed storage */
      }

      let nextSource: "mock" | "anki" | "manual" = "mock";
      let baseline: DayRecord[] | null = null;
      try {
        const resp = await fetchStudyStreak();
        if (
          !cancelled &&
          resp.available &&
          Array.isArray(resp.days) &&
          resp.days.length > 0
        ) {
          baseline = resp.days.map((d) => ({
            date: d.date,
            minutes: (d.minutes && d.minutes > 0 ? d.minutes : null) as StudyMinutes,
          }));
          nextSource = "anki";
        }
      } catch {
        /* fall through to mock baseline */
      }

      if (cancelled) return;
      const hasOverrides = Object.keys(overrides).length > 0;
      setStudyData((prev) => {
        const base = baseline ?? prev;
        return base.map((d) =>
          d.date in overrides ? { ...d, minutes: overrides[d.date] } : d
        );
      });
      if (nextSource === "anki") {
        setDataSource("anki");
      } else if (hasOverrides) {
        setDataSource("manual");
      } else {
        setDataSource("mock");
      }
      setHydrated(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Persist whenever studyData changes (post-hydration only)
  useEffect(() => {
    if (!hydrated) return;
    try {
      const payload: Record<string, StudyMinutes> = {};
      for (const d of studyData) {
        if (d.minutes !== null) payload[d.date] = d.minutes;
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch {
      /* ignore quota errors */
    }
  }, [studyData, hydrated]);

  // ---------- stats ----------
  const stats = useMemo(() => {
    const studiedDays = studyData.filter((d) => (d.minutes ?? 0) > 0);
    const daysStudied = studiedDays.length;
    const totalMin = studiedDays.reduce((s, d) => s + (d.minutes ?? 0), 0);
    const avgMin = daysStudied > 0 ? Math.round(totalMin / daysStudied) : 0;

    // Current streak: count backwards from today (last element)
    let currentStreak = 0;
    for (let i = studyData.length - 1; i >= 0; i--) {
      if ((studyData[i].minutes ?? 0) > 0) currentStreak++;
      else break;
    }

    // Best streak
    let bestStreak = 0;
    let run = 0;
    for (const d of studyData) {
      if ((d.minutes ?? 0) > 0) {
        run++;
        if (run > bestStreak) bestStreak = run;
      } else {
        run = 0;
      }
    }

    return { daysStudied, avgMin, currentStreak, bestStreak };
  }, [studyData]);

  // ---------- month labels aligned to first Monday of each month ----------
  const monthLabels = useMemo(() => {
    const labels: { label: string; col: number }[] = [];
    let lastMonth = -1;
    for (let col = 0; col < COLS; col++) {
      const idx = col * 7;
      if (idx < studyData.length) {
        const d = new Date(studyData[idx].date);
        const month = d.getMonth();
        if (month !== lastMonth) {
          labels.push({
            label: d.toLocaleString("default", { month: "short" }),
            col,
          });
          lastMonth = month;
        }
      }
    }
    return labels;
  }, [studyData]);

  const updateDay = useCallback((index: number, mins: StudyMinutes) => {
    setStudyData((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], minutes: mins };
      return next;
    });
  }, []);

  const openPopover = useCallback(
    (index: number, rect: DOMRect) => {
      if (!containerRef.current) return;
      const containerRect = containerRef.current.getBoundingClientRect();
      const x = rect.left + rect.width / 2 - containerRect.left;
      const y = rect.top - containerRect.top;
      setEditingDay({ index, position: { x, y } });
    },
    []
  );

  const handleCellPointerDown = useCallback(
    (index: number, e: React.PointerEvent<SVGRectElement>) => {
      if (e.pointerType !== "touch") return;
      if (e.shiftKey) return;
      longPressFired.current = false;
      const rect = e.currentTarget.getBoundingClientRect();
      if (longPressTimer.current) clearTimeout(longPressTimer.current);
      longPressTimer.current = setTimeout(() => {
        longPressFired.current = true;
        openPopover(index, rect);
      }, LONG_PRESS_MS);
    },
    [openPopover]
  );

  const handleCellPointerUpOrLeave = useCallback(() => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
  }, []);

  const handleCellClick = useCallback(
    (index: number, e: React.MouseEvent<SVGRectElement>) => {
      if (longPressFired.current) {
        longPressFired.current = false;
        return;
      }
      if (e.shiftKey) {
        const rect = e.currentTarget.getBoundingClientRect();
        openPopover(index, rect);
        return;
      }
      setStudyData((prev) => {
        const next = [...prev];
        next[index] = {
          ...next[index],
          minutes: cycleMinutes(next[index].minutes),
        };
        return next;
      });
    },
    [openPopover]
  );

  const handleCellContextMenu = useCallback(
    (index: number, e: React.MouseEvent<SVGRectElement>) => {
      e.preventDefault();
      updateDay(index, 0);
    },
    [updateDay]
  );

  const handleChangeMinutes = useCallback(
    (mins: StudyMinutes) => {
      if (editingDay === null) return;
      updateDay(editingDay.index, mins);
    },
    [editingDay, updateDay]
  );

  const handleClosePopover = useCallback(() => {
    setEditingDay(null);
  }, []);

  const handleResetConfirmed = useCallback(() => {
    setStudyData((prev) => prev.map((d) => ({ ...d, minutes: null })));
    setConfirmingReset(false);
  }, []);

  const svgWidth = COLS * (CELL + GAP);
  const svgHeight = ROWS * (CELL + GAP) + 14;

  return (
    <Card className="col-span-full rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-5 pb-2">
        <div className="flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Study Streak
            </CardTitle>
            {dataSource === "mock" && (
              <span className="text-[10px] text-muted-foreground/60">Connect Anki for streak</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {dataSource === "anki" && (
              <span className="text-[10px] text-emerald-400/70">Anki</span>
            )}
            {dataSource === "manual" && (
              <span className="text-[10px] text-amber-400/70">Manual</span>
            )}
            <button
              onClick={() => setConfirmingReset(true)}
              title="Reset study data"
              aria-label="Reset study data"
              className="rounded border border-white/10 bg-transparent px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:border-white/20 transition-colors"
            >
              Reset
            </button>
            <HelpPopover />
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-5 pt-0">
        {/* Stats row */}
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <span>
            <span className="font-semibold tabular-nums text-foreground">{stats.daysStudied}</span>
            {" days studied this year"}
          </span>
          <span>
            <span className="font-semibold tabular-nums text-foreground">{stats.avgMin}</span>
            {" avg min/day"}
          </span>
          <span>
            <span className="font-semibold tabular-nums text-foreground">{stats.currentStreak}</span>
            {" day streak"}
          </span>
          <span>
            {"Best: "}
            <span className="font-semibold tabular-nums text-foreground">{stats.bestStreak}</span>
            {" days"}
          </span>
        </div>

        <TooltipProvider>
          <div ref={containerRef} className="relative overflow-x-auto">
            <svg width={svgWidth} height={svgHeight} className="block">
              {/* Month axis labels */}
              {monthLabels.map(({ label, col }) => (
                <text
                  key={`month-${col}`}
                  x={col * (CELL + GAP)}
                  y={10}
                  fontSize={9}
                  className="fill-muted-foreground/50"
                >
                  {label}
                </text>
              ))}

              {studyData.map((day, i) => {
                const col = Math.floor(i / 7);
                const row = i % 7;
                const unset = isUnset(day.minutes);
                const fill = unset ? "transparent" : getColor(day.minutes);
                const opacity = unset ? 0.3 : 1;

                // Tooltip text: "Apr 17, 2026 — 42 min" / "— no study" / "— no data"
                let tipSuffix: string;
                if (day.minutes === null) tipSuffix = "no data";
                else if (day.minutes === 0) tipSuffix = "no study";
                else tipSuffix = `${day.minutes} min`;
                const tipLabel = `${formatDate(day.date)} — ${tipSuffix}`;

                return (
                  <Tooltip key={day.date}>
                    <TooltipTrigger
                      render={
                        <rect
                          x={col * (CELL + GAP)}
                          y={14 + row * (CELL + GAP)}
                          width={CELL}
                          height={CELL}
                          rx={2}
                          ry={2}
                          fill={fill}
                          stroke={unset ? "rgba(255,255,255,0.08)" : "none"}
                          strokeWidth={unset ? 1 : 0}
                          opacity={opacity}
                          className="cursor-pointer transition-[fill,opacity] hover:opacity-80"
                          onClick={(e) => handleCellClick(i, e)}
                          onContextMenu={(e) => handleCellContextMenu(i, e)}
                          onPointerDown={(e) => handleCellPointerDown(i, e)}
                          onPointerUp={handleCellPointerUpOrLeave}
                          onPointerLeave={handleCellPointerUpOrLeave}
                          onPointerCancel={handleCellPointerUpOrLeave}
                        />
                      }
                    />
                    <TooltipContent>{tipLabel}</TooltipContent>
                  </Tooltip>
                );
              })}
            </svg>

            {editingDay !== null && (
              <DayEditPopover
                date={studyData[editingDay.index].date}
                minutes={studyData[editingDay.index].minutes}
                position={editingDay.position}
                onChangeMinutes={handleChangeMinutes}
                onClose={handleClosePopover}
              />
            )}
          </div>
        </TooltipProvider>

        {/* Legend only (hint moved to ? popover) */}
        <div className="mt-2 flex items-center justify-end gap-1 text-[10px] text-muted-foreground/60">
          <span>Less</span>
          {[null, 10, 25, 45, 90, 150].map((m, idx) => (
            <div
              key={idx}
              className="h-3 w-3 rounded-sm"
              style={{
                backgroundColor: m === null ? "transparent" : getColor(m),
                border: m === null ? "1px solid rgba(255,255,255,0.08)" : "none",
              }}
            />
          ))}
          <span>More</span>
        </div>
      </CardContent>

      {confirmingReset && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setConfirmingReset(false)}
        >
          <div
            className="rounded-xl border border-white/10 bg-zinc-900 p-5 shadow-2xl max-w-sm"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold mb-2">Reset study data?</h3>
            <p className="text-xs text-muted-foreground mb-4">
              All logged study minutes for the past year will be cleared. The heatmap
              layout is not affected. This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmingReset(false)}
                className="rounded-md border border-white/10 bg-transparent px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleResetConfirmed}
                className="rounded-md border border-red-500/30 bg-red-500/20 px-3 py-1.5 text-xs text-red-300 hover:bg-red-500/30 transition-colors"
              >
                Reset
              </button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
