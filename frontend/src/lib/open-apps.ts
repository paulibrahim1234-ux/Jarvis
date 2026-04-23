export type AppTarget =
  | "outlook-email"
  | "messages"
  | "outlook-calendar"
  | "uworld"
  | "anki";

export interface OpenInAppOptions {
  app: AppTarget;
  ref: string;               // item id, phone number, event id, etc.
  context?: Record<string, unknown>;
}

/**
 * Opens an item in a native macOS app by POSTing to the backend.
 * Resolves whether backend succeeds or fails (widgets fire-and-forget).
 * Only throws on network failure.
 *
 * @param opts - Options including app target, ref, and optional context
 * @throws on network failure only
 */
export async function openInApp(opts: OpenInAppOptions): Promise<void> {
  try {
    const r = await fetch("/api/apps/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        app: opts.app,
        ref: opts.ref,
        context: opts.context,
      }),
      signal: AbortSignal.timeout(10000),
    });

    // On error, log but resolve (fire-and-forget)
    if (!r.ok) {
      console.error(
        `Failed to open app "${opts.app}" with ref "${opts.ref}": HTTP ${r.status}`
      );
    }
  } catch (error) {
    // Network failure - log and throw
    const errorMsg =
      error instanceof Error ? error.message : String(error);
    console.error(
      `Network error opening app "${opts.app}" with ref "${opts.ref}": ${errorMsg}`
    );
    throw error;
  }
}
