"use client";

import { forwardRef } from "react";

export const ResizeHandle = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function ResizeHandle(props, ref) {
    const { ...restProps } = props;
    return (
      <div
        ref={ref}
        {...restProps}
        className="absolute bottom-0 right-0 w-5 h-5 z-[100] cursor-se-resize group/resize"
      >
        <svg
          className="absolute bottom-1 right-1 w-3 h-3 text-muted-foreground/0 group-hover/resize:text-muted-foreground/70 transition-colors"
          viewBox="0 0 12 12"
          fill="none"
        >
          <path d="M11 1L1 11M11 5L5 11M11 9L9 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>
    );
  }
);
