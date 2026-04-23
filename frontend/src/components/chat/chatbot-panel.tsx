"use client";

import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Send, Trash2, Plus, Menu, MessageSquare } from "lucide-react";
import {
  postChat,
  listConversations,
  createConversation,
  getConversation,
  deleteConversation,
  type ConversationMeta,
} from "@/lib/api";

interface Message {
  id: number;
  role: "user" | "jarvis";
  text: string;
}

const WELCOME_MESSAGE: Message = {
  id: 0,
  role: "jarvis",
  text: "Hey! I'm Jarvis, your med school copilot. Ask me about your schedule, study stats, or anything else.",
};

const ACTIVE_CONV_KEY = "jarvis-active-conversation-v2";
const NARROW_BREAKPOINT = 300;

interface ChatbotPanelProps {
  embedded?: boolean;
}

export function ChatbotPanel({ embedded = false }: ChatbotPanelProps) {
  const [conversations, setConversations] = useState<ConversationMeta[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [nextId, setNextId] = useState(1);
  const [isTyping, setIsTyping] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isNarrow, setIsNarrow] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const loadedRef = useRef(false);

  // ── Responsive: hide sidebar when narrow ──
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      for (const e of entries) {
        const w = e.contentRect.width;
        const narrow = w < NARROW_BREAKPOINT;
        setIsNarrow(narrow);
        if (narrow) setSidebarOpen(false);
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // ── Load conversation list + resume active thread on mount ──
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    (async () => {
      try {
        const list = await listConversations();
        setConversations(list);
        const saved = localStorage.getItem(ACTIVE_CONV_KEY);
        if (saved && list.some((c) => c.id === saved)) {
          await loadConversation(saved);
        } else if (list.length > 0) {
          await loadConversation(list[0].id);
        }
      } catch {
        /* backend may be down — user can still chat, new thread will be created on first send */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Persist active id ──
  useEffect(() => {
    if (!activeId) return;
    try {
      localStorage.setItem(ACTIVE_CONV_KEY, activeId);
    } catch {
      /* ignore */
    }
  }, [activeId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, isTyping]);

  const refreshConversations = useCallback(async () => {
    try {
      const list = await listConversations();
      setConversations(list);
    } catch {
      /* ignore */
    }
  }, []);

  const loadConversation = useCallback(async (id: string) => {
    try {
      const conv = await getConversation(id);
      const msgs: Message[] = [WELCOME_MESSAGE];
      conv.messages.forEach((m, i) => {
        msgs.push({
          id: i + 1,
          role: m.role === "user" ? "user" : "jarvis",
          text: m.content,
        });
      });
      setMessages(msgs);
      setActiveId(id);
      setNextId(conv.messages.length + 2);
    } catch {
      /* ignore */
    }
  }, []);

  const handleNewChat = useCallback(async () => {
    try {
      const conv = await createConversation();
      setActiveId(conv.id);
      setMessages([WELCOME_MESSAGE]);
      setNextId(1);
      await refreshConversations();
    } catch {
      // fallback: clear local state; backend will create one on first send
      setActiveId(null);
      setMessages([WELCOME_MESSAGE]);
      setNextId(1);
    }
  }, [refreshConversations]);

  const handleDeleteConversation = useCallback(
    async (id: string, e?: React.MouseEvent) => {
      e?.stopPropagation();
      try {
        await deleteConversation(id);
        if (activeId === id) {
          setActiveId(null);
          setMessages([WELCOME_MESSAGE]);
          setNextId(1);
        }
        await refreshConversations();
      } catch {
        /* ignore */
      }
    },
    [activeId, refreshConversations]
  );

  const clearCurrent = useCallback(async () => {
    if (activeId) {
      await handleDeleteConversation(activeId);
    } else {
      setMessages([WELCOME_MESSAGE]);
      setNextId(1);
    }
  }, [activeId, handleDeleteConversation]);

  async function handleSend() {
    const text = input.trim();
    if (!text || isTyping) return;

    const userMsg: Message = { id: nextId, role: "user", text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setNextId((n) => n + 1);
    setIsTyping(true);

    try {
      // Send just the new user turn; backend reads full history from DB.
      const { reply, conversation_id } = await postChat(
        [{ role: "user", content: text }],
        { conversation_id: activeId ?? undefined }
      );
      if (!activeId) setActiveId(conversation_id);
      setMessages((prev) => [
        ...prev,
        { id: nextId + 1, role: "jarvis", text: reply },
      ]);
      refreshConversations();
    } catch (err: unknown) {
      const isOffline = err instanceof TypeError && err.message.includes("fetch");
      const errText = isOffline
        ? "⚠️ Can't reach the Jarvis backend."
        : `⚠️ ${err instanceof Error ? err.message : "Something went wrong."}`;
      setMessages((prev) => [...prev, { id: nextId + 1, role: "jarvis", text: errText }]);
    } finally {
      setIsTyping(false);
      setNextId((n) => n + 2);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const showSidebar = sidebarOpen && !isNarrow;

  return (
    <div
      ref={containerRef}
      className={`flex h-full ${embedded ? "rounded-xl border border-white/10 bg-card" : ""}`}
      style={!embedded ? { background: "oklch(0.13 0.005 260)" } : undefined}
    >
      {/* ── Sidebar ── */}
      {showSidebar && (
        <div
          className="flex w-40 shrink-0 flex-col border-r"
          style={{ borderColor: "oklch(1 0 0 / 6%)" }}
        >
          <div className="flex h-10 items-center justify-between px-3">
            <span className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground/70">
              Chats
            </span>
            <button
              onClick={handleNewChat}
              title="New chat"
              className="rounded p-0.5 text-muted-foreground/70 hover:text-foreground transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <ScrollArea className="flex-1 min-h-0">
            <div className="flex flex-col gap-0.5 p-1.5">
              {conversations.length === 0 && (
                <div className="px-2 py-3 text-[11px] text-muted-foreground/50">
                  No chats yet. Send a message to start.
                </div>
              )}
              {conversations.map((c) => (
                <div
                  key={c.id}
                  onClick={() => loadConversation(c.id)}
                  className={`group flex cursor-pointer items-center gap-1.5 rounded px-2 py-1.5 text-xs transition-colors ${
                    activeId === c.id
                      ? "bg-white/10 text-foreground"
                      : "text-muted-foreground/80 hover:bg-white/5"
                  }`}
                >
                  <MessageSquare className="h-3 w-3 shrink-0 opacity-50" />
                  <span className="flex-1 truncate">{c.title || "New chat"}</span>
                  <button
                    onClick={(e) => handleDeleteConversation(c.id, e)}
                    title="Delete chat"
                    className="opacity-0 group-hover:opacity-60 hover:opacity-100 transition-opacity"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* ── Main panel ── */}
      <div className="flex flex-1 min-w-0 flex-col">
        {/* Header */}
        <div
          className={`relative flex h-10 items-center ${
            embedded ? "widget-drag-handle cursor-move px-4" : "px-4"
          }`}
        >
          <div className="flex items-center gap-2">
            {(isNarrow || !sidebarOpen) && (
              <button
                onClick={() => setSidebarOpen((s) => !s)}
                title="Toggle chat list"
                className="text-muted-foreground/60 hover:text-foreground transition-colors"
              >
                <Menu className="h-3.5 w-3.5" />
              </button>
            )}
            <div
              className="h-2 w-2 rounded-full pulse-live"
              style={{ backgroundColor: "oklch(0.65 0.18 250)" }}
            />
            <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              Jarvis
            </h2>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={handleNewChat}
              title="New chat"
              className="text-muted-foreground/50 hover:text-muted-foreground transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
            {messages.length > 1 && (
              <button
                onClick={clearCurrent}
                title="Clear current chat"
                className="text-muted-foreground/50 hover:text-muted-foreground transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-px"
            style={{
              background:
                "linear-gradient(90deg, transparent, oklch(1 0 0 / 6%) 50%, transparent)",
            }}
          />
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 min-h-0">
          <div ref={scrollRef} className="flex flex-col gap-3 p-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {msg.role === "user" ? (
                  <div
                    className="max-w-[85%] rounded-2xl rounded-br-md px-3.5 py-2.5 text-sm leading-relaxed text-white"
                    style={{
                      background:
                        "linear-gradient(135deg, oklch(0.6 0.18 250), oklch(0.55 0.2 260))",
                    }}
                  >
                    {msg.text}
                  </div>
                ) : (
                  <div
                    className="max-w-[85%] rounded-2xl rounded-bl-md border-l-2 px-3.5 py-2.5 text-sm leading-relaxed text-foreground whitespace-pre-wrap"
                    style={{
                      background: "oklch(0.18 0.008 260)",
                      borderLeftColor: "oklch(0.65 0.18 250 / 40%)",
                    }}
                  >
                    {msg.text}
                  </div>
                )}
              </div>
            ))}

            {isTyping && (
              <div className="flex justify-start">
                <div
                  className="flex items-center gap-1 rounded-2xl rounded-bl-md border-l-2 px-4 py-3"
                  style={{
                    background: "oklch(0.18 0.008 260)",
                    borderLeftColor: "oklch(0.65 0.18 250 / 40%)",
                  }}
                >
                  <span
                    className="typing-dot inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: "oklch(0.6 0 0)" }}
                  />
                  <span
                    className="typing-dot inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: "oklch(0.6 0 0)" }}
                  />
                  <span
                    className="typing-dot inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: "oklch(0.6 0 0)" }}
                  />
                </div>
              </div>
            )}
          </div>
        </ScrollArea>

        {/* Input */}
        <div className="p-3">
          <div
            className="chat-input-glow flex items-center gap-2 rounded-xl border px-3 py-1.5 transition-all"
            style={{
              borderColor: "oklch(1 0 0 / 8%)",
              background: "oklch(0.16 0.005 260)",
            }}
          >
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask Jarvis anything..."
              className="flex-1 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
              disabled={isTyping}
            />
            <Button
              size="icon"
              variant="ghost"
              onClick={handleSend}
              disabled={!input.trim() || isTyping}
              className="h-8 w-8 shrink-0 rounded-lg transition-colors"
              style={
                input.trim() && !isTyping
                  ? { backgroundColor: "oklch(0.65 0.18 250)", color: "white" }
                  : {}
              }
            >
              <Send className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
