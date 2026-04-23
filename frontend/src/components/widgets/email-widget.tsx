"use client";

import { useMemo, useRef, useState, useEffect, useCallback } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  fetchEmails,
  fetchEmailFolders,
  type EmailFolder,
  type EmailAccountFolders,
  BACKEND,
} from "@/lib/api";
import type { Email } from "@/lib/types";
import { openInApp } from "@/lib/open-apps";

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
  const [containerWidth, setContainerWidth] = useState(0);
  const [emails, setEmails] = useState<Email[]>([]);
  const [live, setLive] = useState(false);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>(ALL_TAB);
  const [folderAccounts, setFolderAccounts] = useState<EmailAccountFolders[]>([]);
  const [search, setSearch] = useState("");

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

        if (data.auth_needed) {
          setEmails([]);
          setAuthUrl(data.auth_url ?? `${BACKEND}/auth/microsoft`);
          return;
        }
        if (data.needs_account || (!data.available && data.error)) {
          setEmails([]);
          setErrorMsg(data.error as string);
          return;
        }
        if (data.available && data.emails?.length) {
          setErrorMsg(null);
          const mapped: Email[] = data.emails.map((e: Record<string, unknown>, i: number) => ({
            id: (e.entry_id as string) || (e.id as string) || String(i),
            from: (e.from_name || e.from || e.from_email || "Unknown") as string,
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
        } else if (data.available && !data.emails?.length) {
          setEmails([]);
          setLive(true);
          setErrorMsg(null);
        }
      })
      .catch(() => {
        setEmails([]);
      });
  }, [activeFolder]);

  // Initial folder list fetch (once).
  useEffect(() => {
    fetchEmailFolders()
      .then((data) => {
        if (data.available) setFolderAccounts(data.accounts);
      })
      .catch(() => {
        /* swallow — folder bar just won't populate */
      });
  }, []);

  // Load emails on tab change and every 120s.
  useEffect(() => {
    loadEmails();
    const id = setInterval(loadEmails, 120_000);
    return () => clearInterval(id);
  }, [loadEmails]);

  // Build the tab strip: All + Unread + folders with unread > 0, deduped.
  const tabs = useMemo<{ key: TabKey; label: string; unread?: number }[]>(() => {
    const out: { key: TabKey; label: string; unread?: number }[] = [
      { key: ALL_TAB, label: "All" },
      { key: UNREAD_TAB, label: "Unread" },
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

  // Apply tab filter first, then search filter.
  const filtered = useMemo(() => {
    let base = tab === UNREAD_TAB ? emails.filter((e) => !e.read) : emails;
    const q = search.trim().toLowerCase();
    if (q) {
      base = base.filter(
        (e) =>
          e.from.toLowerCase().includes(q) ||
          e.subject.toLowerCase().includes(q)
      );
    }
    return base;
  }, [emails, tab, search]);

  const isWide = containerWidth > 500;

  return (
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          Inbox
          {live ? (
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block" title="Live from Outlook" />
          ) : errorMsg ? (
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 inline-block" title={errorMsg} />
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
                      ? "bg-white/10 text-white"
                      : "bg-white/[0.02] text-muted-foreground hover:bg-white/5 hover:text-white/80")
                  }
                >
                  {t.label}
                  {count > 0 && (
                    <span className={"ml-1.5 text-[10px] " + (active ? "text-white/60" : "text-muted-foreground/60")}>
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
              className="w-full rounded-md bg-white/[0.04] border border-white/[0.06] px-2.5 py-1 text-[11px] text-white/80 placeholder:text-muted-foreground/40 outline-none focus:border-white/15 focus:bg-white/[0.06] transition-colors"
            />
          </div>
        </>
      )}

      <CardContent ref={contentRef} className="flex-1 min-h-0 p-4 pt-0">
        {errorMsg ? (
          <div className="flex h-full flex-col items-start justify-center gap-2 px-2 text-xs text-muted-foreground">
            <div className="text-amber-400/90 text-sm font-medium">Outlook needs a quick fix</div>
            <p className="text-muted-foreground leading-relaxed">{errorMsg}</p>
            <button
              onClick={loadEmails}
              className="mt-1 rounded-md bg-white/5 hover:bg-white/10 px-3 py-1 text-[11px] text-white/90 transition-colors"
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
                  onClick={() =>
                    openInApp({
                      app: "outlook-email",
                      ref: email.id,
                      context: { subject: email.subject, from: email.from },
                    })
                  }
                  className={
                    isWide
                      ? "flex items-start gap-2.5 rounded-lg border border-white/5 bg-white/[0.02] p-2.5 transition-colors cursor-pointer hover:bg-white/10"
                      : "flex items-start gap-2.5 px-1 py-1.5 transition-colors cursor-pointer hover:bg-white/[0.08]"
                  }
                >
                  {/* Unread dot */}
                  <div className="mt-[5px] flex-shrink-0 w-2">
                    {!email.read ? (
                      <div className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    ) : (
                      <div className="h-1.5 w-1.5" />
                    )}
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
                          (!email.read ? "text-white/80" : "text-muted-foreground/60")
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
                        <span className="shrink-0 rounded px-1 py-px text-[9px] bg-white/[0.05] text-muted-foreground/50 leading-tight">
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
