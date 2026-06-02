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
  if (resp.status === 401) throw new Error("Unauthorized");
  if (!resp.ok) throw new Error(`Failed to load conversations: ${resp.status}`);
  return await resp.json();
}

export async function fetchMessages(
  token: string,
  conversationId: string
): Promise<MessageRow[]> {
  const resp = await fetch(
    `${API_BASE}/admin/conversations/${conversationId}/messages?limit=500`,
    { headers: authHeaders(token) }
  );
  if (resp.status === 401) throw new Error("Unauthorized");
  if (!resp.ok) throw new Error(`Failed to load messages: ${resp.status}`);
  return await resp.json();
}

