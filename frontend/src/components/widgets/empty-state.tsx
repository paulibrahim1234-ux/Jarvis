"use client";

import { type LucideIcon } from "lucide-react";
import { type ReactNode } from "react";

type Props = {
  icon: LucideIcon;
  title: string;
  hint?: ReactNode;
  className?: string;
};

export function EmptyState({ icon: Icon, title, hint, className = "" }: Props) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 py-8 px-4 text-center ${className}`}
    >
      <Icon className="h-8 w-8 text-muted-foreground/30" aria-hidden />
      <p className="text-sm text-muted-foreground">{title}</p>
      {hint && <p className="text-xs text-muted-foreground/70">{hint}</p>}
    </div>
  );
}
