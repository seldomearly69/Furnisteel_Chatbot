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

const API_BASE =
  (import.meta as any).env?.VITE_API_BASE?.toString() || "http://localhost:8080";

export async function fetchConversations(): Promise<ConversationRow[]> {
  const resp = await fetch(`${API_BASE}/admin/conversations`);
  if (!resp.ok) throw new Error(`Failed to load conversations: ${resp.status}`);
  return await resp.json();
}

export async function fetchMessages(conversationId: string): Promise<MessageRow[]> {
  const resp = await fetch(
    `${API_BASE}/admin/conversations/${conversationId}/messages?limit=500`
  );
  if (!resp.ok) throw new Error(`Failed to load messages: ${resp.status}`);
  return await resp.json();
}

