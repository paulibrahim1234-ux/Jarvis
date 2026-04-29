"use client";

import { useMemo, useRef, useState, useEffect, useCallback } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  fetchEmails,
  fetchEmailFolders,
  addEmailToCalendar,
  type EmailFolder,
  type EmailAccountFolders,
  BACKEND,
} from "@/lib/api";
import type { Email } from "@/lib/types";
import { openInApp } from "@/lib/open-apps";
import * as chrono from "chrono-node";
import { scoreEmail, isNewsletter } from "@/lib/inbox-rules";

/**
 * Inbox widget — Outlook desktop via AppleScript.
 *
 * Shows the user's ACTUAL Outlook folder structure (Rowan Class of 2027,
 * Financial Aid, Archive, etc.) as tabs, not hardcoded category filters.
 * Clicking a tab refetches the backend scoped to that folder.
 */

type TabKey = string; // "__all__" | "__unread__" | folder name

const ALL_TAB: TabKey = "__all__";
const UNREAD_TAB: TabKey = "__unread__";
const IMPORTANT_TAB: TabKey = "__important__";
const NEWSLETTERS_TAB: TabKey = "__newsletters__";

// Folders to hide from the tab strip by default (noise / infra).
const HIDDEN_FOLDERS = new Set([
  "Drafts",
  "Sent Items",
  "Deleted Items",
  "Junk Email",
  "Junk E-mail",
  "Clutter",
  "Conversation History",
  "RSS Feeds",
  "Sync Issues",
  "Outbox",
  "Subscribed Public Folders",
]);

/**
 * Parse Outlook's verbose timestamp ("Friday, April 17, 2026 at 11:41:02 AM")
 * into a compact human label matching the Messages widget pattern:
 *   - Today      → "8:12 AM"
 *   - Yesterday  → "Yesterday"
 *   - This week  → "Mon"
 *   - Same year  → "Apr 16"
 *   - Older      → "Apr 16, 2024"
 */
function formatEmailTime(raw: string): string {
  if (!raw) return "";

  // Try JS Date parse first (works on ISO strings).
  // For Outlook's "Friday, April 17, 2026 at 11:41:02 AM" strip the day-of-week
  // prefix and the "at" keyword so Date.parse handles it.
  const cleaned = raw
    .replace(/^[A-Za-z]+,\s*/, "") // strip "Friday, "
    .replace(/\s+at\s+/, " "); // strip "at"

  const d = new Date(cleaned);
  if (isNaN(d.getTime())) return raw; // fallback to original

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((today.getTime() - msgDay.getTime()) / 86_400_000);

  if (diffDays === 0) {
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  }
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) {
    return d.toLocaleDateString("en-US", { weekday: "short" });
  }
  if (d.getFullYear() === now.getFullYear()) {
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/**
 * Shorten a folder name to a readable chip label (max ~8 chars).
 * e.g. "Rowan Class of 2027" -> "Rowan"
 *      "Financial Aid"       -> "Fin Aid"
 *      "Automail"            -> "Automail"
 */
function folderChip(name: string): string {
  if (name.length <= 10) return name;
  // Take first two meaningful words, each capped at 4 chars.
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length === 1) return words[0].slice(0, 8);
  return words
    .slice(0, 2)
    .map((w) => (w.length > 4 ? w.slice(0, 4) : w))
    .join(" ");
}

export function EmailWidget() {
  const contentRef = useRef<HTMLDivElement>(null);
  const lastFolderFetchRef = useRef<number>(0);
  const [containerWidth, setContainerWidth] = useState(0);
  const [emails, setEmails] = useState<Email[]>([]);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>(ALL_TAB);
  const [folderAccounts, setFolderAccounts] = useState<EmailAccountFolders[]>([]);
  const [search, setSearch] = useState("");
  const [previewEmail, setPreviewEmail] = useState<Email | null>(null);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) setContainerWidth(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Resolve the current tab to a folder name (or "" for Inbox/All/Unread).
  const activeFolder = useMemo(() => {
    if (tab === ALL_TAB || tab === UNREAD_TAB) return "";
    return tab;
  }, [tab]);

  // Show folder-origin chips only in All/Unread views.
  const showFolderChips = tab === ALL_TAB || tab === UNREAD_TAB;

  // Generation counter — prevents stale tab responses from overwriting newer results.
  const folderGen = useRef<string>("");

  const loadEmails = useCallback(() => {
    const opts = activeFolder ? { folder: activeFolder } : undefined;
    const launchedFor = activeFolder;
    folderGen.current = launchedFor;
    fetchEmails(opts)
      .then((data) => {
        if (folderGen.current !== launchedFor) return;

        // auth_needed: backend explicitly says OAuth token required.
        // needs_account: Outlook desktop app isn't open / signed in — also
        //   treat as "needs connection" so the Connect CTA shows instead of
        //   a generic error message that gives the user nothing to click.
        if (data.auth_needed || data.needs_account) {
          setEmails([]);
          setErrorMsg(null);
          setAuthUrl(data.auth_url ?? `${BACKEND}/auth/microsoft`);
          setLoading(false);
          return;
        }
        if (!data.available && data.error) {
          setEmails([]);
          setErrorMsg(data.error as string);
          setLoading(false);
          return;
        }
        if (data.available && data.emails?.length) {
          setErrorMsg(null);
          const mapped: Email[] = data.emails.map((e: Record<string, unknown>, i: number) => ({
            id: (e.entry_id as string) || (e.id as string) || String(i),
            from: String(e.from_name ?? e.from ?? e.from_email ?? "Unknown"),
            from_email: String(e.from_email ?? e.from ?? ""),
            subject: (e.subject as string) || "(no subject)",
            preview: (e.preview as string) || "",
            time: (e.received || e.time || "") as string,
            read: !!(e.read as boolean),
            source: (e.source as Email["source"]) ?? "other",
            account: (e.account as string) || undefined,
            folder: (e.folder as string) || undefined,
          }));
          setEmails(mapped);
          setLive(true);
          setLoading(false);
        } else if (data.available && !data.emails?.length) {
          setEmails([]);
          setLive(true);
          setLoading(false);
          setErrorMsg(null);
        }
      })
      .catch(() => {
        setEmails([]);
        setErrorMsg("Backend unreachable — retry…");
        setLoading(false);
      });
  }, [activeFolder]);

  // Initial folder list fetch (once).
  useEffect(() => {
    fetchEmailFolders()
      .then((data) => {
        if (data.available) {
          setFolderAccounts(data.accounts);
          lastFolderFetchRef.current = Date.now();
        }
      })
      .catch(() => {
        /* swallow — folder bar just won't populate */
      });
  }, []);

  // Re-fetch folders when the tab becomes visible (after ≥30s away).
  useEffect(() => {
    const handleVisibility = () => {
      if (
        document.visibilityState === "visible" &&
        Date.now() - lastFolderFetchRef.current > 30_000
      ) {
        fetchEmailFolders()
          .then((data) => {
            if (data.available) {
              setFolderAccounts(data.accounts);
              lastFolderFetchRef.current = Date.now();
            }
          })
          .catch(() => {/* swallow */});
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  // Load emails on tab change and every 120s.
  useEffect(() => {
    loadEmails();
    const id = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      loadEmails();
    }, 120_000);
    return () => clearInterval(id);
  }, [loadEmails]);

  // Build the tab strip: All + Unread + Important + Newsletters + folders with unread > 0, deduped.
  const tabs = useMemo<{ key: TabKey; label: string; unread?: number }[]>(() => {
    const out: { key: TabKey; label: string; unread?: number }[] = [
      { key: ALL_TAB, label: "All" },
      { key: UNREAD_TAB, label: "Unread" },
      { key: IMPORTANT_TAB, label: "Important" },
      { key: NEWSLETTERS_TAB, label: "Newsletters" },
    ];
    const seen = new Set<string>(["Inbox"]);
    const candidates: EmailFolder[] = [];
    for (const a of folderAccounts) {
      for (const f of a.folders) {
        if (HIDDEN_FOLDERS.has(f.name)) continue;
        if (seen.has(f.name)) continue;
        if (f.unread > 0) candidates.push(f);
      }
    }
    candidates.sort((a, b) => (b.unread - a.unread) || a.name.localeCompare(b.name));
    for (const f of candidates) {
      seen.add(f.name);
      out.push({ key: f.name, label: f.name, unread: f.unread });
    }
    return out;
  }, [folderAccounts]);

  const allUnreadCount = useMemo(() => emails.filter((e) => !e.read).length, [emails]);

  const importantEmails = useMemo(() => emails.filter((e) => scoreEmail(e) >= 40), [emails]);
  const newsletterEmails = useMemo(() => emails.filter((e) => isNewsletter(e)), [emails]);

  // Apply tab filter first, then search filter.
  const filtered = useMemo(() => {
    let base: Email[];
    if (tab === UNREAD_TAB) base = emails.filter((e) => !e.read);
    else if (tab === IMPORTANT_TAB) base = importantEmails;
    else if (tab === NEWSLETTERS_TAB) base = newsletterEmails;
    else base = emails;
    const q = search.trim().toLowerCase();
    if (q) {
      base = base.filter(
        (e) =>
          e.from.toLowerCase().includes(q) ||
          e.subject.toLowerCase().includes(q)
      );
    }
    return base;
  }, [emails, tab, search, importantEmails, newsletterEmails]);

  const isWide = containerWidth > 500;

  return (
    <Card className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card hover:border-foreground/15 transition-colors">
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-[13px] font-semibold tracking-[-0.02em] text-muted-foreground flex items-center gap-2">
          Inbox
          {live ? (
            <>
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block" title="Live from Outlook" />
              <span className="sr-only">live</span>
            </>
          ) : errorMsg ? (
            <>
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 inline-block" title={errorMsg} />
              <span className="sr-only">error</span>
            </>
          ) : authUrl ? (
            <a
              href={authUrl}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] normal-case font-normal text-blue-400/70 hover:text-blue-400 underline"
            >
              connect Outlook
            </a>
          ) : null}
        </CardTitle>
      </CardHeader>

      {!errorMsg && (
        <>
          {/* Tab strip */}
          <div className="px-4 pb-1.5 flex gap-1 flex-wrap">
            {tabs.map((t) => {
              const active = tab === t.key;
              const count =
                t.key === ALL_TAB
                  ? emails.length
                  : t.key === UNREAD_TAB
                  ? allUnreadCount
                  : t.unread ?? 0;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  title={t.label}
                  className={
                    "rounded-full px-2.5 py-0.5 text-[11px] transition-colors max-w-[180px] truncate " +
                    (active
                      ? "bg-foreground/10 text-foreground"
                      : "bg-foreground/[0.02] text-muted-foreground hover:bg-foreground/5 hover:text-foreground/80")
                  }
                >
                  {t.label}
                  {count > 0 && (
                    <span className={"ml-1.5 text-[10px] " + (active ? "text-foreground/60" : "text-muted-foreground/60")}>
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Search box */}
          <div className="px-4 pb-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search sender or subject..."
              className="w-full rounded-md bg-foreground/[0.04] border border-foreground/[0.06] px-2.5 py-1 text-[11px] text-foreground/80 placeholder:text-muted-foreground/40 outline-none focus:border-foreground/15 focus:bg-foreground/[0.06] transition-colors"
            />
          </div>
        </>
      )}

      {/* Inline email preview modal */}
      {previewEmail && (
        <EmailPreviewModal
          email={previewEmail}
          onClose={() => setPreviewEmail(null)}
          onOpenOutlook={() => {
            setPreviewEmail(null);
            openInApp({
              app: "outlook-email",
              ref: previewEmail.id,
              context: { subject: previewEmail.subject, from: previewEmail.from },
            });
          }}
        />
      )}

      <CardContent ref={contentRef} className="flex-1 min-h-0 p-4 pt-0">
        {loading && emails.length === 0 ? (
          <div className="space-y-2 pt-1">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex items-start gap-2.5 px-1 py-1.5 animate-pulse">
                <div className="mt-[3px] h-5 w-5 rounded-full bg-foreground/[0.07] flex-shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-2.5 w-2/3 rounded bg-foreground/[0.06]" />
                  <div className="h-2 w-4/5 rounded bg-foreground/[0.04]" />
                </div>
              </div>
            ))}
          </div>
        ) : errorMsg ? (
          <div className="flex h-full flex-col items-start justify-center gap-2 px-2 text-xs text-muted-foreground">
            <div className="text-amber-400/90 text-sm font-medium">Outlook needs a quick fix</div>
            <p className="text-muted-foreground leading-relaxed">{errorMsg}</p>
            <button
              onClick={loadEmails}
              className="mt-1 rounded-md bg-foreground/5 hover:bg-foreground/10 px-3 py-1 text-[11px] text-foreground/90 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : emails.length === 0 && authUrl ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <p className="text-sm text-muted-foreground">Outlook not connected</p>
            <a
              href={authUrl}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-primary underline hover:text-primary/80 transition-colors"
            >
              Connect
            </a>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground/60">
            {search
              ? "No results."
              : `No ${tab === ALL_TAB ? "emails" : tab === UNREAD_TAB ? "unread emails" : `emails in ${tab}`} yet.`}
          </div>
        ) : (
          <ScrollArea className="h-full">
            <div className={isWide ? "grid grid-cols-2 gap-1.5" : "divide-y divide-white/[0.04]"}>
              {filtered.map((email) => (
                <div
                  key={email.id}
                  role="button"
                  tabIndex={0}
                  onClick={(ev) => {
                    // Cmd-click or shift-click → open in Outlook directly
                    if (ev.metaKey || ev.shiftKey) {
                      openInApp({
                        app: "outlook-email",
                        ref: email.id,
                        context: { subject: email.subject, from: email.from },
                      });
                    } else {
                      setPreviewEmail(email);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setPreviewEmail(email);
                    }
                  }}
                  className={
                    isWide
                      ? "flex items-start gap-2.5 rounded-lg border border-foreground/5 bg-foreground/[0.02] p-2.5 transition-colors cursor-pointer hover:bg-foreground/10"
                      : "flex items-start gap-2.5 px-1 py-1.5 transition-colors cursor-pointer hover:bg-foreground/[0.08]"
                  }
                >
                  {/* Unread + priority dots */}
                  <div className="mt-[5px] flex-shrink-0 flex flex-col gap-0.5 w-2">
                    {!email.read ? (
                      <div className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    ) : (
                      <div className="h-1.5 w-1.5" />
                    )}
                    {(() => {
                      const score = scoreEmail(email);
                      if (score >= 70) return <div className="h-1.5 w-1.5 rounded-full bg-red-400" />;
                      if (score >= 40) return <div className="h-1.5 w-1.5 rounded-full bg-amber-400" />;
                      return null;
                    })()}
                  </div>

                  <div className="min-w-0 flex-1">
                    {/* Row 1: sender + time */}
                    <div className="flex items-baseline gap-2">
                      <span
                        className={
                          "truncate text-[12px] leading-tight flex-1 " +
                          (!email.read
                            ? "font-semibold text-foreground"
                            : "font-normal text-muted-foreground/80")
                        }
                      >
                        {email.from}
                      </span>
                      <span className="flex-shrink-0 text-[10px] text-muted-foreground/50 tabular-nums">
                        {formatEmailTime(email.time)}
                      </span>
                    </div>

                    {/* Row 2: subject + source badges + folder chip */}
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <p
                        className={
                          "truncate text-[11px] leading-tight flex-1 " +
                          (!email.read ? "text-foreground/80" : "text-muted-foreground/60")
                        }
                      >
                        {email.subject}
                      </p>
                      {email.source === "canvas" && (
                        <Badge className="shrink-0 border-none bg-orange-500/10 text-[9px] px-1 py-0 text-orange-400/80">Canvas</Badge>
                      )}
                      {email.source === "one45" && (
                        <Badge className="shrink-0 border-none bg-cyan-500/10 text-[9px] px-1 py-0 text-cyan-400/80">One45</Badge>
                      )}
                      {email.source === "school" && (
                        <Badge className="shrink-0 border-none bg-violet-500/10 text-[9px] px-1 py-0 text-violet-400/80">School</Badge>
                      )}
                      {/* Folder origin chip — only in All / Unread views */}
                      {showFolderChips && email.folder && (
                        <span className="shrink-0 rounded px-1 py-px text-[9px] bg-foreground/[0.05] text-muted-foreground/50 leading-tight">
                          {folderChip(email.folder)}
                        </span>
                      )}
                    </div>

                    {/* Row 3: preview (much muted, small) */}
                    {email.preview && (
                      <p className="mt-0.5 truncate text-[10px] text-muted-foreground/40 leading-tight">
                        {email.preview}
                      </p>
                    )}

                    {/* Row 4: calendar pill — only when chrono finds a future date */}
                    {(() => {
                      const parsed = chrono.parse(
                        (email.subject ?? "") + " " + (email.preview ?? "")
                      );
                      if (!parsed.length) return null;
                      const d = parsed[0].start.date();
                      if (d <= new Date()) return null;
                      const label = d.toLocaleDateString("en-US", {
                        weekday: "short",
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      });
                      return (
                        <button
                          className="mt-1 text-[10px] px-2 py-0.5 rounded-full border border-foreground/10 text-muted-foreground hover:text-foreground transition-colors"
                          onClick={(ev) => {
                            ev.stopPropagation();
                            addEmailToCalendar({
                              title: email.subject,
                              start_iso: d.toISOString(),
                            }).catch(() => {/* fire-and-forget */});
                          }}
                        >
                          + Add to Calendar — {label}
                        </button>
                      );
                    })()}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

// ── Email Preview Modal ───────────────────────────────────────────────────────

function EmailPreviewModal({
  email,
  onClose,
  onOpenOutlook,
}: {
  email: Email;
  onClose: () => void;
  onOpenOutlook: () => void;
}) {
  // Close on ESC
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const score = scoreEmail(email);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-foreground/10 bg-card shadow-2xl flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 pb-3 border-b border-foreground/[0.06] shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-foreground leading-tight truncate">
                {email.subject}
              </p>
              <p className="text-[11px] text-muted-foreground/80 mt-0.5 truncate">
                {email.from}
                {email.from_email && email.from_email !== email.from && (
                  <span className="text-muted-foreground/50 ml-1">&lt;{email.from_email}&gt;</span>
                )}
              </p>
            </div>
            <button
              onClick={onClose}
              className="text-muted-foreground/50 hover:text-muted-foreground transition-colors text-lg leading-none shrink-0 mt-0.5"
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <span className="text-[10px] text-muted-foreground/50">
              {formatEmailTime(email.time)}
            </span>
            {email.source === "canvas" && (
              <Badge className="border-none bg-orange-500/10 text-[9px] px-1 py-0 text-orange-400/80">Canvas</Badge>
            )}
            {email.source === "one45" && (
              <Badge className="border-none bg-cyan-500/10 text-[9px] px-1 py-0 text-cyan-400/80">One45</Badge>
            )}
            {email.source === "school" && (
              <Badge className="border-none bg-violet-500/10 text-[9px] px-1 py-0 text-violet-400/80">School</Badge>
            )}
            {email.folder && (
              <span className="rounded px-1.5 py-px text-[9px] bg-foreground/[0.05] text-muted-foreground/50 border border-foreground/[0.06]">
                {email.folder}
              </span>
            )}
            {!email.read && (
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shrink-0" title="Unread" />
            )}
            {score >= 70 && (
              <span className="text-[9px] px-1.5 py-px rounded bg-red-500/10 text-red-400 border border-red-500/20">High priority</span>
            )}
            {score >= 40 && score < 70 && (
              <span className="text-[9px] px-1.5 py-px rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">Important</span>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto p-4 text-sm text-foreground/80 leading-relaxed whitespace-pre-wrap">
          {email.preview || <span className="text-muted-foreground/50 italic">No preview available</span>}
        </div>

        {/* Footer */}
        <div className="p-3 pt-2 border-t border-foreground/[0.06] shrink-0 flex justify-between items-center">
          <p className="text-[10px] text-muted-foreground/40">
            Cmd+click any email row to open directly in Outlook
          </p>
          <button
            onClick={onOpenOutlook}
            className="rounded-md bg-foreground/[0.06] hover:bg-foreground/[0.10] border border-foreground/[0.08] px-3 py-1.5 text-[11px] text-foreground/80 transition-colors"
          >
            Open in Outlook
          </button>
        </div>
      </div>
    </div>
  );
}
