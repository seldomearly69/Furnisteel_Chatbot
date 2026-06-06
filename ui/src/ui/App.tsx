import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ConversationRow,
  MessageRow,
  exchangeApiKeyForToken,
  fetchConversations,
  fetchMessages
} from "./api";
import {
  clearToken,
  isTokenExpired,
  loadStoredToken,
  msUntilExpiry,
  saveToken
} from "./auth";

const READ_COUNTS_KEY = "furnisteel_read_counts";
const POLL_INTERVAL_MS = 10_000;
const SESSION_CHECK_MS = 15_000;

function loadReadCounts(): Record<string, number> {
  try {
    const raw = localStorage.getItem(READ_COUNTS_KEY);
    return raw ? (JSON.parse(raw) as Record<string, number>) : {};
  } catch {
    return {};
  }
}

function unreadCount(conv: ConversationRow, readCounts: Record<string, number>) {
  const lastRead = readCounts[conv.id] ?? 0;
  return Math.max(0, conv.message_count - lastRead);
}

function formatTime(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function initials(label: string) {
  const parts = label.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  const s = parts[0] || label;
  return s.slice(0, 2).toUpperCase();
}

function MessageBody({ message }: { message: MessageRow }) {
  const isImage = message.message_type === "image";
  const caption =
    message.content && message.content !== "[Image]" ? message.content : null;

  if (isImage && message.media_url) {
    return (
      <div className="space-y-2">
        <a href={message.media_url} target="_blank" rel="noopener noreferrer">
          <img
            src={message.media_url}
            alt={caption || "Customer image"}
            className="max-w-full rounded-md border border-black/20"
            loading="lazy"
          />
        </a>
        {caption ? (
          <div className="whitespace-pre-wrap leading-relaxed">{caption}</div>
        ) : null}
      </div>
    );
  }

  return <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>;
}

function Avatar({ label, size = "md" }: { label: string; size?: "sm" | "md" }) {
  const dim = size === "sm" ? "h-9 w-9 text-xs" : "h-11 w-11 text-sm";
  return (
    <div
      className={[
        "shrink-0 rounded-full bg-wa-green/20 text-wa-green font-semibold flex items-center justify-center ring-1 ring-wa-green/30",
        dim
      ].join(" ")}
      aria-hidden
    >
      {initials(label)}
    </div>
  );
}

function LoginScreen({
  apiKeyInput,
  setApiKeyInput,
  authLoading,
  error,
  onLogin
}: {
  apiKeyInput: string;
  setApiKeyInput: (v: string) => void;
  authLoading: boolean;
  error: string | null;
  onLogin: () => void;
}) {
  return (
    <div className="h-full flex items-center justify-center p-6 bg-wa-bg">
      <div className="w-full max-w-md bg-wa-panel rounded-xl border border-white/10 p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="h-12 w-12 rounded-xl bg-wa-green/20 text-wa-green font-bold text-lg flex items-center justify-center">
            FS
          </div>
          <div>
            <h1 className="text-xl font-semibold text-wa-text tracking-tight">
              Furnisteel Admin
            </h1>
            <p className="text-sm text-wa-muted">Customer chat dashboard</p>
          </div>
        </div>
        <p className="text-sm text-wa-muted mb-4 leading-relaxed">
          Sign in with your admin API key. Sessions expire automatically per server
          policy.
        </p>
        <label className="block text-sm font-medium text-wa-text mb-1.5" htmlFor="api-key">
          API key
        </label>
        <input
          id="api-key"
          type="password"
          value={apiKeyInput}
          onChange={(e) => setApiKeyInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !authLoading) onLogin();
          }}
          placeholder="Enter admin API key"
          autoComplete="current-password"
          className="w-full rounded-lg bg-wa-panel2 px-3.5 py-2.5 outline-none border border-white/5 focus:border-wa-green/40 transition-colors"
        />
        <button
          type="button"
          onClick={onLogin}
          disabled={!apiKeyInput.trim() || authLoading}
          className="mt-4 w-full text-sm font-medium px-4 py-2.5 rounded-lg bg-wa-green/20 hover:bg-wa-green/30 border border-wa-green/30 text-wa-text disabled:opacity-50 disabled:pointer-events-none transition-colors"
        >
          {authLoading ? "Signing in…" : "Sign in"}
        </button>
        {error ? (
          <div
            role="alert"
            className="mt-4 text-sm text-red-300 bg-red-950/30 border border-red-900/30 rounded-lg px-3 py-2"
          >
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function App() {
  const [token, setToken] = useState<string | null>(() => loadStoredToken());
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const [conversations, setConversations] = useState<ConversationRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageRow[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadingConvs, setLoadingConvs] = useState(false);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [readCounts, setReadCounts] = useState<Record<string, number>>(loadReadCounts);
  const selectedIdRef = useRef<string | null>(selectedId);
  selectedIdRef.current = selectedId;

  const selectedConversation = useMemo(
    () => conversations.find((c) => c.id === selectedId) || null,
    [conversations, selectedId]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) => {
      const name = (c.display_name || "").toLowerCase();
      const wa = (c.whatsapp_user_id || "").toLowerCase();
      const prev = (c.last_message_preview || "").toLowerCase();
      return name.includes(q) || wa.includes(q) || prev.includes(q);
    });
  }, [conversations, search]);

  const logout = useCallback((message?: string) => {
    clearToken();
    setToken(null);
    setConversations([]);
    setMessages([]);
    setSelectedId(null);
    if (message) setError(message);
  }, []);

  const ensureValidToken = useCallback((): string | null => {
    if (!token) return null;
    if (isTokenExpired(token)) {
      logout("Session expired. Please sign in again.");
      return null;
    }
    return token;
  }, [token, logout]);

  async function loginWithApiKey() {
    setAuthLoading(true);
    setError(null);
    try {
      const res = await exchangeApiKeyForToken(apiKeyInput.trim());
      saveToken(res.access_token);
      setToken(res.access_token);
      setApiKeyInput("");
    } catch (e: any) {
      setError(e?.message || "Login failed");
    } finally {
      setAuthLoading(false);
    }
  }

  function markConversationRead(conversationId: string, messageCount: number) {
    setReadCounts((prev) => {
      const next = { ...prev, [conversationId]: messageCount };
      localStorage.setItem(READ_COUNTS_KEY, JSON.stringify(next));
      return next;
    });
  }

  const refreshAll = useCallback(
    async (silent = false, activeConversationId?: string | null) => {
      const activeToken = ensureValidToken();
      if (!activeToken) return;

      const activeId =
        activeConversationId !== undefined
          ? activeConversationId
          : selectedIdRef.current;

      if (!silent) {
        setLoadingConvs(true);
        if (activeId) setLoadingMsgs(true);
      }
      setError(null);

      try {
        const data = await fetchConversations(activeToken);
        setConversations(data);

        let conversationId = activeId;
        if (!conversationId && data.length) {
          conversationId = data[0].id;
          setSelectedId(data[0].id);
          markConversationRead(data[0].id, data[0].message_count);
        }

        if (conversationId) {
          const open = data.find((c) => c.id === conversationId);
          const msgs = await fetchMessages(activeToken, conversationId);
          setMessages(msgs);
          const count = Math.max(open?.message_count ?? 0, msgs.length);
          markConversationRead(conversationId, count);
        } else {
          setMessages([]);
        }
      } catch (e: any) {
        const msg = e?.message || "";
        if (msg.includes("Unauthorized") || msg.includes("expired")) {
          logout("Session expired. Please sign in again.");
          return;
        }
        if (!silent) {
          setError(msg || "Failed to refresh chats");
        }
      } finally {
        if (!silent) {
          setLoadingConvs(false);
          setLoadingMsgs(false);
        }
      }
    },
    [ensureValidToken, logout]
  );

  function openConversation(conv: ConversationRow) {
    setSelectedId(conv.id);
    markConversationRead(conv.id, conv.message_count);
    void refreshAll(false, conv.id);
  }

  useEffect(() => {
    if (!token) return;
    void refreshAll(false);
  }, [token, refreshAll]);

  useEffect(() => {
    if (!token) return;
    const intervalId = window.setInterval(() => {
      void refreshAll(true);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, [token, refreshAll]);

  useEffect(() => {
    if (!token) return;

    const checkExpiry = () => {
      if (isTokenExpired(token)) {
        logout("Session expired. Please sign in again.");
        return;
      }
      const remaining = msUntilExpiry(token);
      if (remaining !== null && remaining <= 0) {
        logout("Session expired. Please sign in again.");
      }
    };

    checkExpiry();
    const intervalId = window.setInterval(checkExpiry, SESSION_CHECK_MS);
    const remaining = msUntilExpiry(token);
    let timeoutId: number | undefined;
    if (remaining !== null && remaining > 0) {
      timeoutId = window.setTimeout(checkExpiry, remaining + 50);
    }

    return () => {
      window.clearInterval(intervalId);
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [token, logout]);

  if (!token) {
    return (
      <LoginScreen
        apiKeyInput={apiKeyInput}
        setApiKeyInput={setApiKeyInput}
        authLoading={authLoading}
        error={error}
        onLogin={() => void loginWithApiKey()}
      />
    );
  }

  const headerLabel =
    selectedConversation?.display_name ||
    selectedConversation?.whatsapp_user_id ||
    "Select a conversation";

  return (
    <div className="h-full overflow-hidden bg-wa-bg">
      <div className="h-full min-h-0 grid grid-cols-[minmax(300px,360px)_1fr]">
        <aside className="h-full min-h-0 bg-wa-panel border-r border-black/30 flex flex-col overflow-hidden">
          <header className="shrink-0 px-4 py-4 bg-wa-panel2 border-b border-black/30 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-semibold text-wa-text tracking-tight truncate">
                Conversations
              </div>
              <div className="text-xs text-wa-muted truncate">Furnisteel WhatsApp</div>
            </div>
            <button
              type="button"
              onClick={() => logout()}
              className="shrink-0 text-sm px-3 py-1.5 rounded-lg text-wa-muted hover:text-wa-text bg-white/5 hover:bg-white/10 border border-white/10 transition-colors"
            >
              Sign out
            </button>
          </header>

          <div className="shrink-0 p-3 bg-wa-panel">
            <div className="relative">
              <svg
                className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-wa-muted pointer-events-none"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M21 21l-4.35-4.35M11 18a7 7 0 100-14 7 7 0 000 14z"
                />
              </svg>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name or number"
                className="w-full rounded-lg bg-wa-panel2 pl-9 pr-3 py-2 text-sm outline-none border border-white/5 focus:border-wa-green/40 transition-colors"
              />
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-2 pb-2">
            {loadingConvs && conversations.length === 0 ? (
              <div className="p-6 text-center text-sm text-wa-muted">Loading…</div>
            ) : filtered.length === 0 ? (
              <div className="p-6 text-center text-sm text-wa-muted">
                {search.trim() ? "No matches for your search." : "No conversations yet."}
              </div>
            ) : (
              filtered.map((c) => {
                const active = c.id === selectedId;
                const unread = unreadCount(c, readCounts);
                const title = c.display_name || c.whatsapp_user_id;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => openConversation(c)}
                    className={[
                      "w-full text-left rounded-xl px-3 py-3 mb-1 flex gap-3 items-start transition-colors",
                      active
                        ? "bg-white/10"
                        : "hover:bg-white/5 border border-transparent"
                    ].join(" ")}
                  >
                    <Avatar label={title} size="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <div className="font-medium text-sm text-wa-text truncate">
                          {title}
                        </div>
                        <div className="text-[11px] text-wa-muted shrink-0">
                          {formatTime(c.updated_at)}
                        </div>
                      </div>
                      <div className="text-sm text-wa-muted truncate mt-0.5">
                        {c.last_message_preview || "No messages yet"}
                      </div>
                    </div>
                    {unread > 0 ? (
                      <span className="shrink-0 mt-1 inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-wa-green text-wa-bg text-xs font-semibold">
                        {unread > 99 ? "99+" : unread}
                      </span>
                    ) : null}
                  </button>
                );
              })
            )}
          </div>
        </aside>

        <main className="h-full min-h-0 flex flex-col overflow-hidden bg-wa-bg">
          <header className="shrink-0 px-5 py-4 bg-wa-panel2 border-b border-black/30 flex items-center gap-3">
            <Avatar label={headerLabel} />
            <div className="min-w-0 flex-1">
              <div className="font-semibold text-wa-text truncate">{headerLabel}</div>
              {selectedConversation?.display_name ? (
                <div className="text-xs text-wa-muted font-mono truncate">
                  {selectedConversation.whatsapp_user_id}
                </div>
              ) : selectedConversation ? (
                <div className="text-xs text-wa-muted">WhatsApp customer</div>
              ) : (
                <div className="text-xs text-wa-muted">Choose a thread from the list</div>
              )}
            </div>
            {selectedConversation ? (
              <div className="text-xs text-wa-muted shrink-0 hidden sm:block">
                {selectedConversation.message_count} message
                {selectedConversation.message_count === 1 ? "" : "s"}
              </div>
            ) : null}
          </header>

          {error ? (
            <div
              role="alert"
              className="shrink-0 px-5 py-2.5 text-sm text-red-300 bg-red-950/30 border-b border-red-900/30"
            >
              {error}
            </div>
          ) : null}

          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-5 py-6">
            {loadingMsgs && messages.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-wa-muted">
                Loading messages…
              </div>
            ) : !selectedId ? (
              <div className="flex h-full flex-col items-center justify-center text-center px-6">
                <div className="h-16 w-16 rounded-2xl bg-wa-green/20 text-wa-green flex items-center justify-center text-2xl font-semibold mb-4">
                  FS
                </div>
                <p className="text-wa-text font-medium">Select a conversation</p>
                <p className="text-sm text-wa-muted mt-1 max-w-sm">
                  Pick a customer on the left to view their WhatsApp history with the
                  assistant.
                </p>
              </div>
            ) : messages.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-wa-muted">
                No messages in this conversation yet.
              </div>
            ) : (
              <div className="space-y-4 max-w-3xl mx-auto w-full">
                {messages.map((m) => {
                  const isAssistant = m.role === "assistant";
                  return (
                    <div
                      key={m.id}
                      className={["flex", isAssistant ? "justify-end" : "justify-start"].join(
                        " "
                      )}
                    >
                      <div
                        className={[
                          "max-w-[min(85%,28rem)] rounded-lg px-3 py-2 text-sm shadow-sm",
                          isAssistant
                            ? "bg-wa-bubbleMe text-wa-text rounded-tr-sm"
                            : "bg-wa-bubbleThem text-wa-text rounded-tl-sm"
                        ].join(" ")}
                      >
                        <MessageBody message={m} />
                        <div className="mt-1 text-[11px] text-wa-muted text-right">
                          {formatTime(m.created_at)}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
