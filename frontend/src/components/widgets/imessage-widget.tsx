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
  isFromMe: boolean;
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
        .catch(() => alive && setStatusMsg("Backend offline"));
    };
    load();
    const t = setInterval(load, 60_000);
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
    return { unread: u, read: r };
  }, [convos]);

  const expandedConvo = expanded != null
    ? convos.find((c) => c.chat_id === expanded) ?? null
    : null;

  return (
    <Card className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors">
      <CardHeader className="p-5 pb-3 flex-row items-center justify-between space-y-0">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          Messages
          {live ? (
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block" title="Live data" />
          ) : statusMsg ? (
            <span className="text-[10px] normal-case font-normal text-muted-foreground/50" title={statusMsg}>
              {statusMsg.includes("Full Disk") ? "no FDA" : "offline"}
            </span>
          ) : null}
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
}: {
  unread: Conversation[];
  read: Conversation[];
  onOpen: (chatId: number) => void;
  isWide: boolean;
  statusMsg: string | null;
  hasAny: boolean;
}) {
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
          chat_id: convo.chat_id,
          display_name: convo.contact,
        }
      : {
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
      className="w-full flex items-center gap-3 py-2 px-2 rounded-lg text-left hover:bg-white/5 transition-colors cursor-pointer"
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

function ThreadView({ convo, isWide }: { convo: Conversation; isWide: boolean }) {
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

      <div className={isWide ? "space-y-3" : "space-y-2"}>
        {convo.messages.map((m, idx) => (
          <div
            key={idx}
            className={`flex ${m.isFromMe ? "justify-end" : "justify-start"}`}
          >
            <div className={`${isWide ? "max-w-[75%]" : "max-w-[80%]"} space-y-1`}>
              <div
                className={`rounded-2xl ${isWide ? "px-3.5 py-2 text-sm" : "px-3 py-1.5 text-xs"} ${
                  m.isFromMe
                    ? "rounded-br-md bg-blue-600 text-white"
                    : "rounded-bl-md bg-white/5 text-foreground"
                }`}
              >
                {m.text}
              </div>
              <div
                className={`text-muted-foreground/40 ${m.isFromMe ? "text-right" : ""} ${
                  isWide ? "text-[10px]" : "text-[9px]"
                }`}
              >
                {m.time}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
