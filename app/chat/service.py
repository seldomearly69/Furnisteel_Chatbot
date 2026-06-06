"""RAG-backed conversational service for customer support."""

from __future__ import annotations

import logging
import uuid

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import MessageRole, MessageType
from app.db.repository import ChatRepository
from app.rag.chroma_store import ChromaKnowledgeStore
from app.rag.retrieval import KnowledgeRetriever

logger = logging.getLogger(__name__)

def _preview(text: str, limit: int = 240) -> str:
    text = (text or "").replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"

DEFAULT_SYSTEM_PROMPT = """You are the customer support assistant for {company_name}.

Use the provided knowledge base context to answer questions about products, services, policies, and general company information in first person.

Rules:
- Be professional, helpful, and concise.
- If the answer is not in the context, say you do not have that information and offer to connect the customer with a human representative.
- Do not invent specifications, prices, or policies.
- For urgent safety or warranty issues, recommend contacting the company directly.
- DO NOT respond to anything that is not related to the company or the products or services. In such cases, politely reaffirm your purpose as a customer support assistant.
- Answer in a format suitable for WhatsApp, with no markdown formatting.
- If a customer sends an image, acknowledge that it was received. You cannot see image contents unless they describe them in text.
"""

IMAGE_RECEIVED_REPLY = (
    "Thank you for sending the image. We have saved it and our team can review it. "
    "If you have a question about the image, please describe it in a text message as well."
)


class ChatService:
    def __init__(
        self,
        session: Session,
        store: ChromaKnowledgeStore | None = None,
    ):
        self._session = session
        self._repo = ChatRepository(session)
        self._settings = get_settings()
        self._client = (
            OpenAI(api_key=self._settings.openai_api_key)
            if self._settings.openai_api_key
            else None
        )
        self._retriever = (
            KnowledgeRetriever(self._client, store=store or ChromaKnowledgeStore())
            if self._client
            else None
        )

    def _system_prompt(self) -> str:
        return DEFAULT_SYSTEM_PROMPT.format(company_name=self._settings.company_name)

    def _history_content(self, message) -> str:
        if message.message_type == MessageType.IMAGE.value:
            caption = (message.content or "").strip()
            if caption and caption != "[Image]":
                return f"[Customer sent an image] {caption}"
            return "[Customer sent an image]"
        return message.content

    def _history_messages(self, conversation_id, limit: int) -> list[dict]:
        messages = self._repo.get_recent_messages(conversation_id, limit=limit)
        payload: list[dict] = []
        for message in messages:
            if message.role == MessageRole.USER:
                payload.append({"role": "user", "content": self._history_content(message)})
            elif message.role == MessageRole.ASSISTANT:
                payload.append({"role": "assistant", "content": message.content})
        return payload

    def _complete_conversation(self, conversation_id: uuid.UUID, user_message: str) -> str:
        if not self._client or not self._retriever:
            return (
                f"Thank you for contacting {self._settings.company_name}. "
                "Our assistant is being configured. Please try again shortly or "
                "contact our team directly."
            )

        history_for_retrieval = self._history_messages(
            conversation_id, limit=self._settings.retrieval_history_messages
        )
        logger.info(
            "RAG history for retrieval: %d messages", len(history_for_retrieval)
        )
        retrieval_query = self._retriever.generate_retrieval_query(
            history_for_retrieval
        )
        if not retrieval_query:
            retrieval_query = user_message

        hits = self._retriever.retrieve(retrieval_query)
        context = self._retriever.format_context(hits)
        logger.info(
            "RAG context ready hits=%d context_chars=%d",
            len(hits),
            len(context),
        )

        history_for_completion = self._history_messages(
            conversation_id, limit=self._settings.completion_history_messages
        )
        logger.info(
            "Chat completion history messages=%d", len(history_for_completion)
        )
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "system",
                "content": (
                    f"Knowledge base context (search query: {retrieval_query}):\n\n"
                    f"{context}"
                ),
            },
            *history_for_completion,
        ]

        try:
            logger.info(
                "OpenAI completion start model=%s",
                self._settings.openai_model,
            )
            response = self._client.chat.completions.create(
                model=self._settings.openai_model,
                messages=messages,
                temperature=0.3,
            )
            reply = response.choices[0].message.content or ""
            logger.info("OpenAI completion done reply_chars=%d", len(reply))
            return reply
        except Exception:
            logger.exception("OpenAI completion failed")
            return (
                "Sorry, I am having trouble responding right now. "
                "Please try again in a moment."
            )

    def generate_reply(
        self,
        whatsapp_user_id: str,
        user_message: str,
        *,
        display_name: str | None = None,
        whatsapp_message_id: str | None = None,
    ) -> str:
        conversation = self._repo.get_or_create_conversation(
            whatsapp_user_id, display_name=display_name
        )
        logger.info(
            "Chat start wa_id=%s conv_id=%s msg=%s",
            whatsapp_user_id,
            str(conversation.id),
            _preview(user_message, 180),
        )
        self._repo.add_message(
            conversation.id,
            MessageRole.USER,
            user_message,
            whatsapp_message_id=whatsapp_message_id,
            message_type=MessageType.TEXT,
        )

        reply = self._complete_conversation(conversation.id, user_message)
        self._repo.add_message(conversation.id, MessageRole.ASSISTANT, reply)
        self._session.commit()
        return reply

    def handle_image_message(
        self,
        whatsapp_user_id: str,
        *,
        display_name: str | None = None,
        whatsapp_message_id: str | None = None,
        media_url: str,
        media_key: str,
        media_mime_type: str,
        caption: str | None = None,
    ) -> str:
        conversation = self._repo.get_or_create_conversation(
            whatsapp_user_id, display_name=display_name
        )
        caption_text = (caption or "").strip()
        content = caption_text or "[Image]"
        logger.info(
            "Image received wa_id=%s conv_id=%s key=%s caption=%s",
            whatsapp_user_id,
            str(conversation.id),
            media_key,
            _preview(caption_text, 120),
        )
        self._repo.add_message(
            conversation.id,
            MessageRole.USER,
            content,
            whatsapp_message_id=whatsapp_message_id,
            message_type=MessageType.IMAGE,
            media_url=media_url,
            media_key=media_key,
            media_mime_type=media_mime_type,
        )

        if caption_text:
            reply = self._complete_conversation(conversation.id, caption_text)
        else:
            reply = IMAGE_RECEIVED_REPLY

        self._repo.add_message(conversation.id, MessageRole.ASSISTANT, reply)
        self._session.commit()
        return reply
