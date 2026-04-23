"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type TimerState = "idle" | "running" | "paused" | "break";

const DURATION_PRESETS = [15, 25, 45, 60] as const;
const DEFAULT_WORK_MINUTES = 25;

function breakMinutes(workMinutes: number): number {
  return Math.max(1, Math.round(workMinutes / 5));
}

function useContainerSize(ref: React.RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });

    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);

  return size;
}

export function PomodoroWidget() {
  const [state, setState] = useState<TimerState>("idle");
  const [workMinutes, setWorkMinutes] = useState(DEFAULT_WORK_MINUTES);
  const [customInput, setCustomInput] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(DEFAULT_WORK_MINUTES * 60);
  const [sessionsCompleted, setSessionsCompleted] = useState(0);

  const workSeconds = workMinutes * 60;
  const breakSeconds = breakMinutes(workMinutes) * 60;

  const contentRef = useRef<HTMLDivElement>(null);
  const container = useContainerSize(contentRef);

  const selectDuration = useCallback((mins: number) => {
    if (state !== "idle") return;
    const clamped = Math.max(1, Math.min(180, mins));
    setWorkMinutes(clamped);
    setSecondsLeft(clamped * 60);
    setCustomInput("");
  }, [state]);

  const reset = useCallback(() => {
    setState("idle");
    setSecondsLeft(workSeconds);
  }, [workSeconds]);

  // Get today's date in local timezone (YYYY-MM-DD format)
  const getTodayKey = () => {
    return new Date().toLocaleDateString("en-CA");
  };

  // On mount, rehydrate sessionsCompleted from localStorage
  useEffect(() => {
    const todayKey = `jarvis.pomodoro.${getTodayKey()}`;
    const stored = localStorage.getItem(todayKey);
    if (stored) {
      const parsed = parseInt(stored, 10);
      if (!isNaN(parsed)) {
        setSessionsCompleted(parsed);
      }
    }
  }, []);

  // Whenever sessionsCompleted changes, persist to localStorage
  useEffect(() => {
    const todayKey = `jarvis.pomodoro.${getTodayKey()}`;
    localStorage.setItem(todayKey, String(sessionsCompleted));
  }, [sessionsCompleted]);

  useEffect(() => {
    if (state !== "running" && state !== "break") return;

    const interval = setInterval(() => {
      setSecondsLeft((prev) => {
        if (prev <= 1) {
          if (state === "running") {
            setSessionsCompleted((c) => c + 1);
            setState("break");
            return breakSeconds;
          } else {
            setState("idle");
            return workSeconds;
          }
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [state, workSeconds, breakSeconds]);

  const minutes = Math.floor(secondsLeft / 60);
  const seconds = secondsLeft % 60;
  const totalSeconds = state === "break" ? breakSeconds : workSeconds;
  const progress = ((totalSeconds - secondsLeft) / totalSeconds) * 100;

  // Responsive sizing: ring scales to container, leave room for header/buttons/session text (~120px)
  const isCompact = container.height > 0 && container.height < 200;
  const ringDiameter = container.height > 0
    ? Math.max(60, Math.min(container.width - 40, container.height - 150))
    : 160;
  const strokeWidth = Math.max(4, ringDiameter * 0.04);
  const radius = (ringDiameter - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (progress / 100) * circumference;

  // Scale time text proportionally to ring size
  const timeFontSize = Math.max(16, ringDiameter * 0.2);

  const stateLabel =
    state === "break"
      ? "Break"
      : state === "idle"
        ? "Ready"
        : state === "paused"
          ? "Paused"
          : "Working";

  const timeDisplay = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;

  // Compact mode: just time + play button, no ring
  if (isCompact) {
    return (
      <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
        <CardContent className="flex-1 min-h-0 flex items-center justify-center gap-3 p-4">
          <span className="font-mono text-xl font-bold tabular-nums">
            {timeDisplay}
          </span>
          {state === "idle" && (
            <Button
              size="sm"
              onClick={() => setState("running")}
              className="bg-emerald-600 hover:bg-emerald-500 text-white border-0 h-7 w-7 p-0"
            >
              &#9654;
            </Button>
          )}
          {state === "running" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setState("paused")}
              className="border-white/10 hover:bg-white/5 h-7 w-7 p-0"
            >
              &#10074;&#10074;
            </Button>
          )}
          {state === "paused" && (
            <Button
              size="sm"
              onClick={() => setState("running")}
              className="bg-emerald-600 hover:bg-emerald-500 text-white border-0 h-7 w-7 p-0"
            >
              &#9654;
            </Button>
          )}
          {state === "break" && (
            <Button
              size="sm"
              variant="outline"
              onClick={reset}
              className="border-white/10 hover:bg-white/5 h-7 px-2"
            >
              Skip
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-5 pb-3">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Pomodoro
        </CardTitle>
      </CardHeader>
      <CardContent
        ref={contentRef}
        className="flex-1 min-h-0 flex flex-col items-center justify-center gap-5 p-5 pt-0"
      >
        {/* Circular timer — scales with container */}
        <div className="relative flex items-center justify-center">
          <svg width={ringDiameter} height={ringDiameter} className="-rotate-90">
            <defs>
              <linearGradient id="pomodoroGradient" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#10b981" />
                <stop offset="100%" stopColor="#34d399" />
              </linearGradient>
              <linearGradient id="breakGradient" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#3b82f6" />
                <stop offset="100%" stopColor="#60a5fa" />
              </linearGradient>
            </defs>
            {/* Background circle */}
            <circle
              cx={ringDiameter / 2}
              cy={ringDiameter / 2}
              r={radius}
              fill="none"
              stroke="currentColor"
              strokeWidth={strokeWidth}
              className="text-white/5"
            />
            {/* Progress circle */}
            <circle
              cx={ringDiameter / 2}
              cy={ringDiameter / 2}
              r={radius}
              fill="none"
              stroke={state === "break" ? "url(#breakGradient)" : "url(#pomodoroGradient)"}
              strokeWidth={strokeWidth}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              className="transition-all duration-1000"
            />
          </svg>
          <div className="absolute flex flex-col items-center">
            <span
              className="font-mono font-bold tabular-nums"
              style={{ fontSize: timeFontSize }}
            >
              {timeDisplay}
            </span>
            <span className="mt-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {stateLabel}
            </span>
          </div>
        </div>

        {/* Duration picker */}
        <div className={`flex items-center gap-1.5 flex-wrap justify-center ${state !== "idle" ? "opacity-40 pointer-events-none" : ""}`}>
          {DURATION_PRESETS.map((d) => (
            <button
              key={d}
              onClick={() => selectDuration(d)}
              className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors border ${
                workMinutes === d && !customInput
                  ? "border-emerald-500 bg-emerald-500/15 text-emerald-400"
                  : "border-white/10 text-muted-foreground hover:border-white/20 hover:text-foreground"
              }`}
            >
              {d}m
            </button>
          ))}
          <input
            type="number"
            min={1}
            max={180}
            placeholder="min"
            value={customInput}
            onChange={(e) => {
              const val = e.target.value;
              setCustomInput(val);
              const n = parseInt(val, 10);
              if (!isNaN(n) && n >= 1 && n <= 180) {
                setWorkMinutes(n);
                setSecondsLeft(n * 60);
              }
            }}
            className="w-12 px-1.5 py-0.5 rounded-full text-[11px] font-medium text-center border border-white/10 bg-transparent text-muted-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-emerald-500 focus:text-foreground [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
          />
        </div>

        {/* Controls */}
        <div className="flex gap-2">
          {state === "idle" && (
            <Button
              size="sm"
              onClick={() => setState("running")}
              className="bg-emerald-600 hover:bg-emerald-500 text-white border-0"
            >
              Start
            </Button>
          )}
          {state === "running" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setState("paused")}
              className="border-white/10 hover:bg-white/5"
            >
              Pause
            </Button>
          )}
          {state === "paused" && (
            <>
              <Button
                size="sm"
                onClick={() => setState("running")}
                className="bg-emerald-600 hover:bg-emerald-500 text-white border-0"
              >
                Resume
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={reset}
                className="border-white/10 hover:bg-white/5"
              >
                Reset
              </Button>
            </>
          )}
          {state === "break" && (
            <Button
              size="sm"
              variant="outline"
              onClick={reset}
              className="border-white/10 hover:bg-white/5"
            >
              Skip Break
            </Button>
          )}
        </div>

        {/* Sessions count */}
        <p className="text-xs text-muted-foreground">
          {sessionsCompleted} session{sessionsCompleted !== 1 ? "s" : ""}{" "}
          completed today
        </p>
      </CardContent>
    </Card>
  );
}
