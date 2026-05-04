/**
 * Skeleton shimmer component.
 *
 * Uses the `jv-skeleton` CSS class defined in globals.css which already
 * includes the `jv-skeleton-shimmer` keyframe animation shipped in Stream 5.
 * We wrap it here so widgets import a typed React component rather than
 * reaching directly into a CSS class name string.
 *
 * Usage:
 *   <Skeleton className="h-4 w-32" />
 *   <Skeleton className="h-16 w-full rounded-lg" />
 */

import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
}

export default function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn("jv-skeleton", className)}
      aria-hidden="true"
    />
  );
}
