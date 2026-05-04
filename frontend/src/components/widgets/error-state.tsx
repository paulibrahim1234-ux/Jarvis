"use client";

import { AlertCircle, RotateCw } from "lucide-react";

type Props = {
  message?: string;
  onRetry?: () => void;
  className?: string;
};

export function ErrorState({
  message = "Couldn't load data",
  onRetry,
  className = "",
}: Props) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-3 py-8 px-4 text-center ${className}`}
    >
      <AlertCircle
        className="h-7 w-7"
        style={{ color: "var(--status-error)" }}
        aria-hidden
      />
      <p className="text-sm text-muted-foreground">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs text-foreground border border-border hover:bg-[var(--surface-raised)] transition-colors"
        >
          <RotateCw className="h-3 w-3" aria-hidden />
          Retry
        </button>
      )}
    </div>
  );
}
