import React, { useEffect, useMemo, useState } from "react";
import {
  ConversationRow,
  MessageRow,
  exchangeApiKeyForToken,
  fetchConversations,
  fetchMessages
} from "./api";

const TOKEN_KEY = "furnisteel_admin_token";

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function bubbleClass(role: MessageRow["role"]) {
  if (role === "assistant") return "bg-wa-bubbleMe text-wa-text ml-auto";
  return "bg-wa-bubbleThem text-wa-text mr-auto";
}

export function App() {
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem(TOKEN_KEY) || null
  );
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const [conversations, setConversations] = useState<ConversationRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageRow[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadingConvs, setLoadingConvs] = useState(false);
  const [loadingMsgs, setLoadingMsgs] = useState(false);

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

  async function loginWithApiKey() {
    setAuthLoading(true);
    setError(null);
    try {
      const res = await exchangeApiKeyForToken(apiKeyInput.trim());
      localStorage.setItem(TOKEN_KEY, res.access_token);
      setToken(res.access_token);
      setApiKeyInput("");
    } catch (e: any) {
      setError(e?.message || "Login failed");
    } finally {
      setAuthLoading(false);
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setConversations([]);
    setMessages([]);
    setSelectedId(null);
  }

  async function loadConversations() {
    if (!token) return;
    setLoadingConvs(true);
    setError(null);
    try {
      const data = await fetchConversations(token);
      setConversations(data);
      if (!selectedId && data.length) setSelectedId(data[0].id);
    } catch (e: any) {
      if ((e?.message || "").includes("Unauthorized")) {
        logout();
        setError("Session expired. Please sign in again.");
        return;
      }
      setError(e?.message || "Failed to load conversations");
    } finally {
      setLoadingConvs(false);
    }
  }

  async function loadMessages(conversationId: string) {
    if (!token) return;
    setLoadingMsgs(true);
    setError(null);
    try {
      const data = await fetchMessages(token, conversationId);
      setMessages(data);
    } catch (e: any) {
      if ((e?.message || "").includes("Unauthorized")) {
        logout();
        setError("Session expired. Please sign in again.");
        return;
      }
      setError(e?.message || "Failed to load messages");
    } finally {
      setLoadingMsgs(false);
    }
  }

  useEffect(() => {
    if (!token) return;
    loadConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!token) return;
    if (selectedId) loadMessages(selectedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, token]);

  if (!token) {
    return (
      <div className="h-full bg-wa-bg text-wa-text flex items-center justify-center p-6">
        <div className="w-full max-w-md bg-wa-panel border border-white/10 rounded-xl p-6">
          <div className="text-xl font-semibold mb-2">Admin Access</div>
          <div className="text-sm text-wa-muted mb-4">
            Enter your admin API key to view customer chats.
          </div>
          <input
            type="password"
            value={apiKeyInput}
            onChange={(e) => setApiKeyInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !authLoading) {
                void loginWithApiKey();
              }
            }}
            placeholder="Admin API key"
            className="w-full rounded bg-wa-panel2 px-3 py-2 outline-none border border-white/10 focus:border-wa-green/40"
          />
          <button
            onClick={loginWithApiKey}
            disabled={!apiKeyInput.trim() || authLoading}
            className="mt-3 w-full text-sm px-3 py-2 rounded bg-wa-green/20 hover:bg-wa-green/30 border border-wa-green/30 disabled:opacity-50"
          >
            {authLoading ? "Signing in..." : "Sign in"}
          </button>
          {error ? <div className="mt-3 text-sm text-red-300">{error}</div> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-hidden text-wa-text">
      <div className="h-full min-h-0 grid grid-cols-[360px_1fr]">
        <aside className="h-full min-h-0 bg-wa-panel border-r border-black/30 flex flex-col overflow-hidden">
          <div className="shrink-0 px-4 py-3 bg-wa-panel2 flex items-center justify-between">
            <div className="font-semibold">Furnisteel Chats</div>
            <button
              onClick={loadConversations}
              className="text-sm px-3 py-1 rounded bg-wa-green/20 hover:bg-wa-green/30 border border-wa-green/30"
            >
              Refresh
            </button>
            <button
              onClick={logout}
              className="text-sm px-3 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10"
            >
              Logout
            </button>
          </div>

          <div className="shrink-0 p-3">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search chats"
              className="w-full rounded bg-wa-panel2 px-3 py-2 outline-none border border-white/5 focus:border-wa-green/40"
            />
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
            {loadingConvs ? (
              <div className="p-4 text-wa-muted">Loading conversations…</div>
            ) : filtered.length === 0 ? (
              <div className="p-4 text-wa-muted">No conversations found.</div>
            ) : (
              filtered.map((c) => {
                const active = c.id === selectedId;
                return (
                  <button
                    key={c.id}
                    onClick={() => setSelectedId(c.id)}
                    className={[
                      "w-full text-left px-4 py-3 border-b border-white/5 hover:bg-white/5",
                      active ? "bg-white/10" : ""
                    ].join(" ")}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="font-medium truncate">
                          {c.display_name || c.whatsapp_user_id}
                        </div>
                        <div className="text-sm text-wa-muted truncate">
                          {c.last_message_preview || "—"}
                        </div>
                      </div>
                      <div className="text-xs text-wa-muted shrink-0 text-right">
                        <div>{formatTime(c.updated_at)}</div>
                        <div className="mt-1 inline-flex items-center justify-center min-w-6 h-5 px-2 rounded-full bg-wa-green/30 border border-wa-green/30">
                          {c.message_count}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        <main className="h-full min-h-0 bg-wa-bg flex flex-col overflow-hidden">
          <div className="shrink-0 px-4 py-3 bg-wa-panel2 border-b border-black/30 flex items-center justify-between">
            <div className="min-w-0">
              <div className="font-semibold truncate">
                {selectedConversation?.display_name ||
                  selectedConversation?.whatsapp_user_id ||
                  "Select a chat"}
              </div>
              {selectedConversation?.display_name ? (
                <div className="text-xs text-wa-muted truncate">
                  {selectedConversation.whatsapp_user_id}
                </div>
              ) : null}
            </div>
            <button
              disabled={!selectedId}
              onClick={() => selectedId && loadMessages(selectedId)}
              className="text-sm px-3 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 disabled:opacity-50"
            >
              Reload
            </button>
          </div>

          {error ? (
            <div className="shrink-0 px-4 py-2 text-red-300 bg-red-950/30 border-b border-red-900/30">
              {error}
            </div>
          ) : null}

          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-4 space-y-2">
            {loadingMsgs ? (
              <div className="text-wa-muted">Loading messages…</div>
            ) : !selectedId ? (
              <div className="text-wa-muted">Pick a conversation on the left.</div>
            ) : messages.length === 0 ? (
              <div className="text-wa-muted">No messages yet.</div>
            ) : (
              messages.map((m) => (
                <div key={m.id} className="flex">
                  <div
                    className={[
                      "max-w-[72%] rounded-lg px-3 py-2 text-sm shadow-sm",
                      bubbleClass(m.role)
                    ].join(" ")}
                  >
                    <div className="whitespace-pre-wrap leading-relaxed">
                      {m.content}
                    </div>
                    <div className="mt-1 text-[11px] text-wa-muted text-right">
                      {formatTime(m.created_at)}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </main>
      </div>
    </div>
  );
}