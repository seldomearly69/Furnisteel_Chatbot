export type ConversationRow = {
  id: string;
  whatsapp_user_id: string;
  display_name: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview: string | null;
};

export type MessageRow = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  message_type: "text" | "image";
  media_url: string | null;
  media_mime_type: string | null;
};

export type MessagesPage = {
  messages: MessageRow[];
  has_more: boolean;
};

export type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
};

const API_BASE =
  (import.meta as any).env?.VITE_API_BASE?.toString() || "http://localhost:8080";

function authHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`
  };
}

export async function exchangeApiKeyForToken(apiKey: string): Promise<TokenResponse> {
  const resp = await fetch(`${API_BASE}/admin/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey })
  });
  if (!resp.ok) throw new Error("Invalid API key");
  return await resp.json();
}

export async function fetchConversations(token: string): Promise<ConversationRow[]> {
  const resp = await fetch(`${API_BASE}/admin/conversations`, {
    headers: authHeaders(token)
  });
  if (resp.status === 401) throw new Error("Unauthorized: session expired");
  if (!resp.ok) throw new Error(`Failed to load conversations: ${resp.status}`);
  return await resp.json();
}

export type FetchMessagesOptions = {
  limit?: number;
  before?: string;
  after?: string;
};

export async function fetchMessagesPage(
  token: string,
  conversationId: string,
  options: FetchMessagesOptions = {}
): Promise<MessagesPage> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.before) params.set("before", options.before);
  if (options.after) params.set("after", options.after);

  const query = params.toString();
  const resp = await fetch(
    `${API_BASE}/admin/conversations/${conversationId}/messages${query ? `?${query}` : ""}`,
    { headers: authHeaders(token) }
  );
  if (resp.status === 401) throw new Error("Unauthorized: session expired");
  if (!resp.ok) throw new Error(`Failed to load messages: ${resp.status}`);
  return await resp.json();
}
