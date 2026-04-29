"use client";

import { useRef, useState, useEffect, useMemo } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { fetchIMessages } from "@/lib/api";
import { openInApp } from "@/lib/open-apps";
import {
  jarvisConfig,
  buildAllowlistSet,
  buildContactLookup,
  passesAllowlist,
  resolveDisplayName,
} from "@/lib/jarvis-config";

type ThreadMessage = {
  text: string;
  time: string;
  time_iso?: string | null;
  epoch_ms?: number | null;
  isFromMe: boolean;
  sender?: string | null;
};

type Conversation = {
  contact: string;
  handle: string;
  chat_id: number;
  is_group: boolean;
  unread_count: number;
  last_message: string;
  last_message_from_me: boolean;
  last_time: string;
  last_time_iso: string | null; // ISO timestamp for reliable sort; may be absent on old entries
  messages: ThreadMessage[];
};

type ApiResponse = {
  available: boolean;
  conversations?: Conversation[];
  total_unread?: number;
  count?: number;
  error?: string;
};

// Deterministic avatar tint per contact
const AVATAR_PALETTE = [
  "bg-blue-500/30 text-blue-100",
  "bg-emerald-500/30 text-emerald-100",
  "bg-purple-500/30 text-purple-100",
  "bg-pink-500/30 text-pink-100",
  "bg-amber-500/30 text-amber-100",
  "bg-indigo-500/30 text-indigo-100",
  "bg-rose-500/30 text-rose-100",
  "bg-teal-500/30 text-teal-100",
];

function avatarClass(name: string) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return AVATAR_PALETTE[Math.abs(h) % AVATAR_PALETTE.length];
}

function initial(name: string) {
  const trimmed = name.replace(/[^A-Za-z0-9]/g, "");
  return (trimmed[0] ?? name[0] ?? "?").toUpperCase();
}

export function IMessageWidget() {
  const contentRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [totalUnread, setTotalUnread] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [live, setLive] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) setContainerWidth(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Memoize once per mount — config is compiled in.
  const allowlist = useMemo(
    () => buildAllowlistSet(jarvisConfig.messagesContactsAllowlist),
    [],
  );
  const nameLookup = useMemo(
    () => buildContactLookup(jarvisConfig.contacts),
    [],
  );

  useEffect(() => {
    let alive = true;
    const load = () => {
      fetchIMessages()
        .then((data: ApiResponse) => {
          if (!alive) return;
          if (!data.available) {
            setStatusMsg(data.error ?? "iMessage not connected");
            setLoading(false);
            return;
          }
          let incoming = data.conversations ?? [];
          // Apply allowlist filter on the `handle` field (more stable than `contact`).
          if (allowlist.size > 0) {
            incoming = incoming.filter((c) =>
              passesAllowlist(c.handle || c.contact, allowlist),
            );
          }
          // Optional client-side override: if user added contacts to
          // jarvis-config.ts, those win over the server-resolved name.
          if (nameLookup.size > 0) {
            incoming = incoming.map((c) => {
              const override = resolveDisplayName(c.handle || c.contact, nameLookup);
              // Only override if we actually found a match (resolver returns the
              // raw handle when unknown — don't let that stomp the server name).
              const wasResolved =
                override !== (c.handle || c.contact) && override !== "";
              return wasResolved ? { ...c, contact: override } : c;
            });
          }
          setConvos(incoming);
          setLoading(false);
          setTotalUnread(
            allowlist.size > 0
              ? incoming.reduce((s, c) => s + c.unread_count, 0)
              : data.total_unread ?? 0,
          );
          setLive(true);
          setStatusMsg(
            allowlist.size > 0 && incoming.length === 0
              ? "No messages from allowlisted contacts"
              : null,
          );
        })
        .catch(() => {
          if (alive) {
            setStatusMsg("Backend offline");
            setLoading(false);
          }
        });
    };
    load();
    const t = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      load();
    }, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [allowlist, nameLookup]);

  const isWide = containerWidth > 400;

  const { unread, read } = useMemo(() => {
    const u: Conversation[] = [];
    const r: Conversation[] = [];
    for (const c of convos) (c.unread_count > 0 ? u : r).push(c);
    // Sort each bucket newest-first using the ISO timestamp when available.
    // The backend returns conversations sorted by last_date DESC already, but
    // the unread/read split can reorder them — re-sort to preserve recency.
    const byTime = (a: Conversation, b: Conversation) => {
      const ta = a.last_time_iso ?? "";
      const tb = b.last_time_iso ?? "";
      if (ta && tb) return tb.localeCompare(ta); // ISO strings compare correctly
      return 0; // preserve backend order when ISO is absent
    };
    u.sort(byTime);
    r.sort(byTime);
    return { unread: u, read: r };
  }, [convos]);

  const expandedConvo = expanded != null
    ? convos.find((c) => c.chat_id === expanded) ?? null
    : null;

  return (
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-5 pb-3 flex-row items-center justify-between space-y-0">
        <CardTitle className="text-[13px] font-semibold tracking-[-0.02em] text-muted-foreground flex items-center gap-2">
          Messages
          {live ? (
            <>
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block" title="Live data" />
              <span className="sr-only">live</span>
            </>
          ) : statusMsg ? (
            <>
              <span className="text-[10px] normal-case font-normal text-muted-foreground/50" title={statusMsg}>
                {statusMsg.includes("Full Disk") ? "no FDA" : "offline"}
              </span>
              <span className="sr-only">error</span>
            </>
          ) : (
            <span className="sr-only">loading</span>
          )}
        </CardTitle>
        {totalUnread > 0 && !expandedConvo && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-200">
            {totalUnread} unread
          </span>
        )}
        {expandedConvo && (
          <button
            onClick={() => setExpanded(null)}
            className="text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
          >
            Back
          </button>
        )}
      </CardHeader>

      <CardContent ref={contentRef} className="flex-1 min-h-0 p-0">
        <ScrollArea className="h-full px-5 pb-5">
          {expandedConvo ? (
            <ThreadView convo={expandedConvo} isWide={isWide} />
          ) : (
            <ConversationList
              unread={unread}
              read={read}
              onOpen={(id) => setExpanded(id)}
              isWide={isWide}
              statusMsg={statusMsg}
              hasAny={convos.length > 0}
              loading={loading}
            />
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

function ConversationList({
  unread,
  read,
  onOpen,
  isWide,
  statusMsg,
  hasAny,
  loading,
}: {
  unread: Conversation[];
  read: Conversation[];
  onOpen: (chatId: number) => void;
  isWide: boolean;
  statusMsg: string | null;
  hasAny: boolean;
  loading: boolean;
}) {
  if (loading && !hasAny) {
    return (
      <div className="space-y-2 pt-2 animate-pulse">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 py-2 px-2">
            <div className={`rounded-full bg-white/[0.07] flex-shrink-0 ${isWide ? "h-10 w-10" : "h-8 w-8"}`} />
            <div className="flex-1 space-y-1.5">
              <div className="h-2.5 w-1/2 rounded bg-white/[0.06]" />
              <div className="h-2 w-3/4 rounded bg-white/[0.04]" />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (!hasAny) {
    return (
      <div className="py-8 text-center text-xs text-muted-foreground">
        {statusMsg ?? "No recent messages"}
      </div>
    );
  }
  return (
    <div className="space-y-1">
      {unread.map((c) => (
        <ConversationRow key={c.chat_id} convo={c} onOpen={onOpen} isWide={isWide} />
      ))}
      {unread.length > 0 && read.length > 0 && (
        <div className="my-2 border-t border-white/5" />
      )}
      {read.map((c) => (
        <ConversationRow key={c.chat_id} convo={c} onOpen={onOpen} isWide={isWide} />
      ))}
    </div>
  );
}

function ConversationRow({
  convo,
  onOpen,
  isWide,
}: {
  convo: Conversation;
  onOpen: (chatId: number) => void;
  isWide: boolean;
}) {
  const preview = convo.last_message_from_me
    ? `You: ${convo.last_message}`
    : convo.last_message;

  const handleOpenInMessages = async (e: React.MouseEvent) => {
    e.preventDefault();
    // For 1:1 chats, use phone as ref; for group chats, use chat_id
    const ref = convo.is_group ? String(convo.chat_id) : (convo.handle || convo.contact);
    // For group chats, don't include phone in context so Case 2 (chat_id path) is reached
    const context = convo.is_group
      ? {
          is_group: true,
          chat_id: convo.chat_id,
          display_name: convo.contact,
        }
      : {
          is_group: false,
          phone: convo.handle,
          chat_id: convo.chat_id,
          display_name: convo.contact,
        };
    await openInApp({
      app: "messages",
      ref,
      context,
    });
  };

  const handleExpandInline = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onOpen(convo.chat_id);
  };

  return (
    // Use a <div role="button"> as the outer container to avoid nesting
    // <button> inside <button> (invalid HTML — browsers auto-close the
    // outer tag which breaks click routing and caused openInApp to fire
    // on unintended clicks).
    <div
      role="button"
      tabIndex={0}
      onClick={handleOpenInMessages}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") handleOpenInMessages(e as unknown as React.MouseEvent);
      }}
      className="w-full flex items-center gap-3 py-2.5 px-2 rounded-lg text-left hover:bg-white/5 transition-colors cursor-pointer border-b border-white/[0.04] last:border-0"
    >
      <Avatar className={isWide ? "h-10 w-10 flex-shrink-0" : "h-8 w-8 flex-shrink-0"}>
        <AvatarFallback className={`${avatarClass(convo.contact)} text-sm font-semibold`}>
          {initial(convo.contact)}
        </AvatarFallback>
      </Avatar>

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span
            className={`truncate ${isWide ? "text-sm" : "text-xs"} ${
              convo.unread_count > 0 ? "font-semibold text-foreground" : "font-medium text-foreground/90"
            }`}
          >
            {convo.contact}
          </span>
          <span
            className={`flex-shrink-0 ${
              convo.unread_count > 0 ? "text-blue-300" : "text-muted-foreground/60"
            } ${isWide ? "text-xs" : "text-[10px]"}`}
          >
            {convo.last_time}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2 mt-0.5">
          <span
            className={`truncate ${isWide ? "text-xs" : "text-[11px]"} ${
              convo.unread_count > 0 ? "text-foreground/80" : "text-muted-foreground/70"
            }`}
          >
            {preview || (convo.last_message_from_me ? "You sent a message" : "No text")}
          </span>
          <div className="flex items-center gap-2 flex-shrink-0">
            {convo.unread_count > 0 && (
              <span className="h-2 w-2 rounded-full bg-blue-400" />
            )}
            <button
              type="button"
              onClick={handleExpandInline}
              className="text-muted-foreground/40 hover:text-muted-foreground/80 transition-colors text-[10px] px-1.5 py-0.5 rounded hover:bg-white/5"
              title="Expand in widget"
            >
              ▾
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Format a day label for a thread divider pill. */
function dayLabel(epochMs: number): string {
  const d = new Date(epochMs);
  const today = new Date();
  const todayStr = today.toDateString();
  const dStr = d.toDateString();
  if (dStr === todayStr) return "Today";
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (dStr === yesterday.toDateString()) return "Yesterday";
  const diffDays = Math.round((today.getTime() - d.getTime()) / 86_400_000);
  if (diffDays < 7) return d.toLocaleDateString("en-US", { weekday: "long" });
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function ThreadView({ convo, isWide }: { convo: Conversation; isWide: boolean }) {
  // Build groups with real epoch-based 60s window grouping.
  const { groups, dayDividers } = useMemo(() => {
    type Group = {
      isFromMe: boolean;
      messages: ThreadMessage[];
      firstSender: string | null;
    };
    const result: Group[] = [];
    // Map from group index → day-label to show BEFORE that group
    const dividerBefore: Map<number, string> = new Map();

    convo.messages.forEach((m, idx) => {
      const prevMsg = idx > 0 ? convo.messages[idx - 1] : null;

      // Day divider: check if this message crossed midnight from the previous one
      if (prevMsg && m.epoch_ms && prevMsg.epoch_ms) {
        const prevDate = new Date(prevMsg.epoch_ms).toDateString();
        const currDate = new Date(m.epoch_ms).toDateString();
        if (prevDate !== currDate) {
          // Insert divider before the new group we're about to create
          dividerBefore.set(result.length, dayLabel(m.epoch_ms));
        }
      }

      // Group condition: same sender AND within 60s of previous message in group
      const last = result[result.length - 1];
      const lastMsg = last?.messages[last.messages.length - 1];
      const sameDir = last && last.isFromMe === m.isFromMe;
      const withinWindow =
        sameDir &&
        m.epoch_ms != null &&
        lastMsg?.epoch_ms != null &&
        Math.abs(m.epoch_ms - lastMsg.epoch_ms) < 60_000;

      if (withinWindow) {
        last.messages.push(m);
      } else {
        result.push({
          isFromMe: m.isFromMe,
          messages: [m],
          firstSender: m.sender ?? null,
        });
      }
    });

    return { groups: result, dayDividers: dividerBefore };
  }, [convo.messages]);

  return (
    <div className="pt-2 space-y-3">
      <div className="flex items-center gap-3 pb-3 border-b border-white/5">
        <Avatar className={isWide ? "h-10 w-10" : "h-8 w-8"}>
          <AvatarFallback className={`${avatarClass(convo.contact)} text-sm font-semibold`}>
            {initial(convo.contact)}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className={`truncate font-semibold ${isWide ? "text-sm" : "text-xs"} text-foreground`}>
            {convo.contact}
          </div>
          <div className={`truncate text-muted-foreground/60 ${isWide ? "text-[11px]" : "text-[10px]"}`}>
            {convo.handle}
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {groups.map((group, gi) => {
          const dividerLabel = dayDividers.get(gi);
          return (
            <div key={`group-${gi}`}>
              {dividerLabel && (
                <div className="text-[10px] text-muted-foreground/50 text-center py-1.5 flex items-center gap-2">
                  <span className="flex-1 border-t border-white/5" />
                  <span className="px-2 py-0.5 rounded-full bg-white/[0.04] border border-white/[0.06]">
                    {dividerLabel}
                  </span>
                  <span className="flex-1 border-t border-white/5" />
                </div>
              )}

              {/* Sender label for group chats — only first bubble in each group */}
              {convo.is_group && !group.isFromMe && group.firstSender && (
                <div className={`text-[10px] text-muted-foreground/50 mb-0.5 ${isWide ? "ml-1" : "ml-0.5"}`}>
                  {group.firstSender}
                </div>
              )}

              <div className={`flex flex-col ${group.isFromMe ? "items-end" : "items-start"} gap-0.5`}>
                {group.messages.map((m, mi) => {
                  const isLast = mi === group.messages.length - 1;
                  const bubbleCls = group.isFromMe
                    ? isLast
                      ? "rounded-[18px] rounded-br-[4px] bg-gradient-to-b from-[#0b93f6] to-[#0a7ce0] text-white"
                      : "rounded-[18px] bg-gradient-to-b from-[#0b93f6] to-[#0a7ce0] text-white"
                    : isLast
                      ? "rounded-[18px] rounded-bl-[4px] bg-white/5 text-foreground"
                      : "rounded-[18px] bg-white/5 text-foreground";
                  return (
                    <div
                      key={`${m.epoch_ms ?? m.time}-${mi}`}
                      className={`group/bubble ${isWide ? "max-w-[75%]" : "max-w-[80%]"}`}
                    >
                      <div className={`${bubbleCls} ${isWide ? "px-3.5 py-2 text-sm" : "px-3 py-1.5 text-xs"}`}>
                        {m.text}
                      </div>
                      {isLast && (
                        <div
                          className={`opacity-0 group-hover/bubble:opacity-100 transition-opacity text-muted-foreground/40 ${group.isFromMe ? "text-right" : ""} ${
                            isWide ? "text-[10px]" : "text-[9px]"
                          } mt-0.5`}
                        >
                          {m.time}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
