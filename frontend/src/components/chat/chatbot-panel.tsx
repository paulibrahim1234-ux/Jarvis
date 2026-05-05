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
  fetchAnthropicStatus,
  BACKEND,
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
// Narrow = the side-by-side flex layout (sidebar + chat) doesn't fit. We
// drop from 300px to 220px because users often resize the chatbot widget
// down via the new RGL resize handle, and we want the side-by-side layout
// to stay viable for as long as possible. Below 220px we render the
// sidebar as an absolute overlay (see showSidebarAsOverlay below).
const NARROW_BREAKPOINT = 220;

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
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isNarrow, setIsNarrow] = useState(false);
  // Proactive credential health — checked on mount + every 2 min so the
  // user sees a banner BEFORE typing into a broken chat. Backend caches
  // the actual Anthropic probe for 5 min so this poll is cheap.
  const [credBanner, setCredBanner] = useState<{ ok: boolean; error: string | null } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const loadedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  // ── Responsive observer ──
  // We track `isNarrow` so we can switch the sidebar to absolute-overlay
  // mode when the panel is too cramped for a side-by-side layout. We
  // INTENTIONALLY do NOT auto-close the sidebar here — the user's explicit
  // toggle (Menu button) is the source of truth. Auto-closing would
  // override that intent when widgets get resized down.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      for (const e of entries) {
        const w = e.contentRect.width;
        setIsNarrow(w < NARROW_BREAKPOINT);
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
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isTyping]);

  // Probe Anthropic creds on mount + every 2 min. Surface a banner above
  // the chat input when invalid so the user knows BEFORE typing.
  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      try {
        const s = await fetchAnthropicStatus();
        if (!cancelled) setCredBanner({ ok: s.ok, error: s.error });
      } catch {
        /* ignore — chat will still render its existing 401 fallback */
      }
    };
    probe();
    const id = setInterval(probe, 120_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

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

  function handleStop() {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setIsTyping(false);
    setMessages((prev) => [...prev, { id: prev.length + 1, role: "jarvis", text: "(cancelled)" }]);
    setNextId((n) => n + 1);
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || isTyping) return;

    const userMsg: Message = { id: nextId, role: "user", text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setNextId((n) => n + 1);
    setIsTyping(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // Send just the new user turn; backend reads full history from DB.
      const { reply, conversation_id } = await postChat(
        [{ role: "user", content: text }],
        { conversation_id: activeId ?? undefined, signal: controller.signal }
      );
      abortRef.current = null;
      if (!activeId) setActiveId(conversation_id);
      setMessages((prev) => [
        ...prev,
        { id: prev.length + 1, role: "jarvis", text: reply },
      ]);
      refreshConversations();
    } catch (err: unknown) {
      abortRef.current = null;
      const isAbort = err instanceof Error && err.name === "AbortError";
      if (isAbort) return; // handleStop already appended the cancelled message
      const isOffline = err instanceof TypeError && err.message.includes("fetch");
      const rawMsg = err instanceof Error ? err.message : "Something went wrong.";
      // Detect Anthropic 401 specifically — token expired or wrong format.
      // Backend forwards the SDK message verbatim, so look for the markers.
      const isAuthError =
        /401|Invalid authentication|authentication_error/i.test(rawMsg);
      const errText = isOffline
        ? "⚠️ Can't reach the Jarvis backend."
        : isAuthError
        ? "⚠️ Claude credentials are invalid or expired.\n\nFix:\n• If you use the Claude Code subscription: refresh your token by running `claude` in a terminal, then restart the Jarvis backend.\n• If you use an API key: paste a valid `ANTHROPIC_API_KEY` into `backend/.env` and restart the backend (`launchctl kickstart -k gui/$UID/com.jarvis.backend`)."
        : `⚠️ ${rawMsg}`;
      setMessages((prev) => [...prev, { id: prev.length + 1, role: "jarvis", text: errText }]);
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

  // The user's explicit toggle drives visibility. When the panel is too
  // narrow for a side-by-side layout, the sidebar takes over via absolute
  // positioning (see overlay vs flow classes below) so the user's intent
  // is honored regardless of the resized widget width.
  const showSidebar = sidebarOpen;
  const showSidebarAsOverlay = sidebarOpen && isNarrow;

  return (
    <div
      ref={containerRef}
      className={`relative flex h-full ${embedded ? "rounded-xl border border-foreground/10 bg-card" : ""}`}
      style={!embedded ? { background: "var(--surface-0)" } : undefined}
    >
      {/* ── Sidebar ──
          When the panel is narrow, render the sidebar as an absolute overlay
          so it doesn't squeeze the chat area into uselessness. When wide,
          fall back to the flex side-by-side layout. */}
      {showSidebar && (
        <div
          className={
            showSidebarAsOverlay
              ? "absolute left-0 top-0 bottom-0 w-40 z-10 flex flex-col border-r shadow-lg bg-card"
              : "flex w-40 shrink-0 flex-col border-r"
          }
          style={{
            borderColor: "var(--border-subtle)",
            ...(showSidebarAsOverlay ? { background: "var(--card)" } : {}),
          }}
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
                      ? "bg-foreground/10 text-foreground"
                      : "text-muted-foreground/80 hover:bg-foreground/5"
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
        {/* Header — no longer the drag target. Drag is handled by the
            WidgetWrapper's centered grip pill at the top edge of the
            card. The previous design (whole header = drag target) made
            cursor 'move' on header buttons and caused accidental drags
            on click. */}
        <div className="relative flex h-10 items-center px-4">
          <div className="flex items-center gap-2">
            {/* Sidebar toggle — always visible (was previously hidden when
                sidebar was already open in normal-width layouts, leaving
                no way to collapse it). */}
            {!isNarrow && (
              <button
                onClick={() => setSidebarOpen((s) => !s)}
                title={sidebarOpen ? "Hide chat list" : "Show chat list"}
                aria-label={sidebarOpen ? "Hide chat list" : "Show chat list"}
                className="text-muted-foreground/60 hover:text-foreground transition-colors"
              >
                <Menu className="h-3.5 w-3.5" />
              </button>
            )}
            {isNarrow && !sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                title="Show chat list"
                aria-label="Show chat list"
                className="text-muted-foreground/60 hover:text-foreground transition-colors"
              >
                <Menu className="h-3.5 w-3.5" />
              </button>
            )}
            <div
              className="h-2 w-2 rounded-full pulse-live"
              style={{ backgroundColor: "var(--brand)" }}
            />
            <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              Jarvis
            </h2>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {/* Only show "New chat" in the main header when the sidebar is
                hidden — when sidebar is open it already has its own +
                button next to "Chats" heading. Avoids two identical
                affordances 200px apart. */}
            {(!showSidebar) && (
              <button
                onClick={handleNewChat}
                title="New chat"
                aria-label="New chat"
                className="text-muted-foreground/50 hover:text-muted-foreground transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            )}
            {messages.length > 1 && (
              <button
                onClick={clearCurrent}
                title="Clear current chat"
                aria-label="Clear current chat"
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
                "linear-gradient(90deg, transparent, var(--border-subtle) 50%, transparent)",
            }}
          />
        </div>

        {/* Credential health banner — proactive: shown BEFORE the user
            tries to chat against an expired token. Click → /setup form
            with a paste-new-token field that hot-reloads the in-process
            Anthropic client. */}
        {credBanner && credBanner.ok === false && (
          <div
            role="alert"
            className="mx-4 mt-2 mb-1 rounded-md border px-3 py-2 text-[12px] leading-snug"
            style={{
              borderColor: "rgba(245, 158, 11, 0.4)",
              backgroundColor: "rgba(245, 158, 11, 0.08)",
              color: "rgb(252, 211, 77)",
            }}
          >
            <div className="font-medium">
              {credBanner.error === "no_credential"
                ? "No Claude credential set"
                : credBanner.error === "invalid_credential"
                ? "Claude credential invalid or expired"
                : "Claude unreachable"}
            </div>
            <div className="mt-1 text-[11px] opacity-90">
              Update your token at{" "}
              <a
                href={`${BACKEND}/setup`}
                target="_blank"
                rel="noreferrer"
                className="underline hover:opacity-100"
              >
                /setup
              </a>
              {" "}— Jarvis hot-reloads the client, no restart needed.
            </div>
          </div>
        )}

        {/* Messages */}
        <ScrollArea className="flex-1 min-h-0">
          <div ref={scrollRef} className="flex flex-col gap-3 p-4">
            <div aria-live="polite" aria-atomic="false" className="contents">
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
                      background: "var(--surface-1)",
                      borderLeftColor: "var(--border-accent)",
                    }}
                  >
                    {msg.text}
                  </div>
                )}
              </div>
            ))}

            {isTyping && (
              <div className="flex justify-start items-center gap-2">
                <div
                  className="flex items-center gap-1 rounded-2xl rounded-bl-md border-l-2 px-4 py-3"
                  style={{
                    background: "var(--surface-1)",
                    borderLeftColor: "var(--border-accent)",
                  }}
                >
                  <span
                    className="typing-dot inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: "var(--ink-muted)" }}
                  />
                  <span
                    className="typing-dot inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: "var(--ink-muted)" }}
                  />
                  <span
                    className="typing-dot inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: "var(--ink-muted)" }}
                  />
                </div>
                <button
                  type="button"
                  onClick={handleStop}
                  className="text-[10px] text-muted-foreground/60 hover:text-muted-foreground border border-foreground/10 rounded px-1.5 py-0.5 transition-colors"
                  title="Stop generation"
                >
                  Stop
                </button>
              </div>
            )}
            </div>
            <div ref={bottomRef} aria-hidden="true" />
          </div>
        </ScrollArea>

        {/* Input */}
        <div className="p-3">
          <div
            className="chat-input-glow flex items-center gap-2 rounded-xl border px-3 py-1.5 transition-all"
            style={{
              borderColor: "var(--border-default)",
              background: "var(--surface-2)",
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
                  ? { backgroundColor: "var(--brand)", color: "white" }
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
