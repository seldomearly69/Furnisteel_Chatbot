"""RAG-backed conversational service for customer support."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from app.chat.reply_parser import AssistantReply, parse_assistant_reply
from app.config import get_settings
from app.db.models import ChatMessage, MessageRole, MessageType
from app.db.repository import ChatRepository
from app.rag.chroma_store import ChromaKnowledgeStore
from app.rag.retrieval import KnowledgeRetriever

logger = logging.getLogger(__name__)

IMAGE_ONLY_USER_TEXT = "The customer sent this image."

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
- When the customer sends an image, look at it carefully and relate your answer to what you see, using the knowledge base where relevant.
- To send an image, add its own line: [[IMAGE:https://public-url]] (public https URL only, from knowledge base). Up to {max_outbound_images} per reply. These lines are not shown as text — WhatsApp delivers them as images. Write your visible reply as normal text; do not describe the marker syntax to the customer.
- When the customer asks to see project photos or examples, pick several relevant URLs from the "Available images in retrieved context" list and send up to {max_outbound_images} [[IMAGE:url]] markers. Do not claim you only have one image if multiple are listed in context.
"""
QUERY_SPLIT_SYSTEM = """You prepare search queries for a company knowledge base, given a customer support conversation.

Step 1 — Resolve intent: Look at the full conversation and determine what the customer currently wants answered. Resolve pronouns and references using context (e.g. "it", "that one", "the first option" → the actual product/policy being discussed). If earlier questions in the conversation were already answered, focus only on what is being asked now — do not re-retrieve for resolved topics.

Step 2 — Decompose into atomic sub-queries: Break the current request into the smallest set of independent search queries needed to fully cover it. Each sub-query should target exactly ONE discrete fact, entity, attribute, or comparison point — not a compound question.

Rules for decomposition:
- If the customer asks about a single attribute of a single entity ("what's the warranty on your steel doors"), output ONE query. Do not invent extra splits.
- If the customer asks about multiple attributes of the same entity ("warranty AND installation coverage for steel doors"), output ONE query per attribute: "steel door warranty", "steel door installation coverage".
- If the customer asks about multiple entities (even without "and" — e.g. "difference between steel and aluminum doors"), output ONE query per entity: "steel door specifications", "aluminum door specifications".
- If the customer message is vague or a follow-up with no new distinct facts needed ("ok what about pricing"), resolve it against context into ONE concrete query, e.g. "steel door pricing".
- Never split a single atomic fact into multiple redundant phrasings of the same thing.

Output ONLY the search queries, one per line, in plain text. No numbering, no labels, no explanation.
"""

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
        return DEFAULT_SYSTEM_PROMPT.format(
            company_name=self._settings.company_name,
            max_outbound_images=self._settings.max_outbound_images,
        )

    def _history_text_content(self, message: ChatMessage) -> str:
        if message.message_type == MessageType.IMAGE.value:
            caption = (message.content or "").strip()
            if message.role == MessageRole.ASSISTANT:
                return "[Assistant sent an image]"
            if caption and caption != "[Image]":
                return f"[Customer sent an image] {caption}"
            return "[Customer sent an image]"
        return message.content

    def _parse_and_log_reply(self, raw: str) -> AssistantReply:
        reply = parse_assistant_reply(
            raw, max_images=self._settings.max_outbound_images
        )
        if reply.image_urls:
            logger.info(
                "Assistant reply images=%d text_chars=%d",
                len(reply.image_urls),
                len(reply.text),
            )
        return reply

    def _save_assistant_reply(
        self, conversation_id: uuid.UUID, reply: AssistantReply
    ) -> None:
        if reply.text:
            self._repo.add_message(
                conversation_id,
                MessageRole.ASSISTANT,
                reply.text,
                message_type=MessageType.TEXT,
            )
        for url in reply.image_urls:
            self._repo.add_message(
                conversation_id,
                MessageRole.ASSISTANT,
                "[Image]",
                message_type=MessageType.IMAGE,
                media_url=url,
                media_mime_type="image/jpeg",
            )

    def _is_first_customer_message(self, conversation_id: uuid.UUID) -> bool:
        return self._repo.count_messages(conversation_id) == 0

    def _maybe_first_message_greeting(
        self,
        conversation_id: uuid.UUID,
        whatsapp_user_id: str,
        *,
        is_first_message: bool,
    ) -> AssistantReply | None:
        if not is_first_message or not self._settings.first_message_greeting_enabled:
            return None

        greeting = self._settings.resolved_first_message_greeting()
        logger.info(
            "First message greeting wa_id=%s conv_id=%s chars=%d",
            whatsapp_user_id,
            str(conversation_id),
            len(greeting),
        )
        return AssistantReply(text=greeting, image_urls=[], raw=greeting)

    def _history_text_messages(self, conversation_id, limit: int) -> list[dict]:
        messages = self._repo.get_recent_messages(conversation_id, limit=limit)
        payload: list[dict] = []
        for message in messages:
            if message.role == MessageRole.USER:
                payload.append(
                    {"role": "user", "content": self._history_text_content(message)}
                )
            elif message.role == MessageRole.ASSISTANT:
                payload.append(
                    {"role": "assistant", "content": self._history_text_content(message)}
                )
        return payload

    def _image_user_text(self, message: ChatMessage) -> str:
        caption = (message.content or "").strip()
        if caption and caption != "[Image]":
            return caption
        return IMAGE_ONLY_USER_TEXT

    def _openai_user_message(self, message: ChatMessage) -> dict[str, Any]:
        if (
            message.message_type == MessageType.IMAGE.value
            and message.media_url
        ):
            parts: list[dict[str, Any]] = [
                {"type": "text", "text": self._image_user_text(message)},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": message.media_url,
                        "detail": self._settings.openai_vision_detail,
                    },
                },
            ]
            return {"role": "user", "content": parts}

        return {"role": "user", "content": message.content}

    def _history_openai_messages(self, conversation_id, limit: int) -> list[dict]:
        messages = self._repo.get_recent_messages(conversation_id, limit=limit)
        payload: list[dict] = []
        image_count = 0
        for message in messages:
            if message.role == MessageRole.USER:
                payload.append(self._openai_user_message(message))
                if (
                    message.message_type == MessageType.IMAGE.value
                    and message.media_url
                ):
                    image_count += 1
            elif message.role == MessageRole.ASSISTANT:
                payload.append(
                    {"role": "assistant", "content": self._history_text_content(message)}
                )
        if image_count:
            logger.info(
                "Vision completion history images=%d messages=%d",
                image_count,
                len(payload),
            )
        return payload

    def _split_compound_query(self, history: list[dict], user_message: str) -> list[str]:
        """Resolve conversation context and decompose the current request into
        atomic sub-queries for maximum retrieval coverage. Replaces the old
        generate_retrieval_query + split two-step with a single context-aware pass."""
        messages = list(history) if history else []
        if not messages or messages[-1].get("content") != user_message:
            messages = messages + [{"role": "user", "content": user_message}]

        try:
            response = self._client.chat.completions.create(
                model=self._settings.openai_retrieval_query_model,
                messages=[
                    {"role": "system", "content": QUERY_SPLIT_SYSTEM},
                    *messages,
                ],
                temperature=0.0,
            )
            lines = [
                l.strip()
                for l in (response.choices[0].message.content or "").split("\n")
                if l.strip()
            ]
            result = lines[:4] or [user_message]
            logger.info(
                "RAG query decomposition: %d sub-queries from %d history messages: %s",
                len(result), len(messages), result,
            )
            return result
        except Exception:
            logger.exception("RAG query decomposition failed, falling back to single query")
            return [user_message]

    def _retrieve_with_confidence_loop(self, query: str, user_message: str) -> tuple[list[dict], float, str]:
        """Confidence-gated retrieval for ONE query. Returns (hits, top_score, final_query_used)."""
        hits: list[dict] = []
        top_score = 0.0
        query_used = query

        for round_num in range(1, self._settings.rag_max_retrieval_rounds + 1):
            round_hits = self._retriever.retrieve(query_used, user_message=user_message)
            round_score = max((h.get("rerank_score") or 0.0) for h in round_hits) if round_hits else 0.0

            logger.info(
                "RAG retrieval round=%d query=%s score=%.3f",
                round_num, _preview(query_used, 120), round_score,
            )

            if round_score > top_score:
                hits, top_score, query = round_hits, round_score, query_used

            if top_score >= self._settings.rag_confidence_threshold:
                break

            if round_num < self._settings.rag_max_retrieval_rounds:
                weak_context = self._retriever.format_context(round_hits)
                query_used = self._refine_retrieval_query(query_used, user_message, weak_context)

        return hits, top_score, query
    
    def _complete_conversation(
        self, conversation_id: uuid.UUID, user_message: str
    ) -> str:
        if not self._client or not self._retriever:
            return (
                f"Thank you for contacting {self._settings.company_name}. "
                "Our assistant is being configured. Please try again shortly or "
                "contact our team directly."
            )

        history_for_retrieval = self._history_text_messages(
            conversation_id, limit=self._settings.retrieval_history_messages
        )
        logger.info(
            "RAG history for retrieval: %d messages", len(history_for_retrieval)
        )

        # --- coverage: resolve intent + decompose into atomic sub-queries in one pass ---
        sub_queries = self._split_compound_query(history_for_retrieval, user_message)

        # --- confidence: gate each sub-query's retrieval independently ---
        all_hits: list[dict] = []
        seen_texts: set[str] = set()
        query_labels: list[str] = []

        for sub_query in sub_queries:
            sub_hits, sub_score, final_query = self._retrieve_with_confidence_loop(
                sub_query, user_message
            )
            query_labels.append(f"{final_query} (score={sub_score:.2f})")
            for hit in sub_hits:
                text = hit.get("text", "")
                if text not in seen_texts:
                    seen_texts.add(text)
                    all_hits.append(hit)

        context = self._retriever.format_context(all_hits)
        image_count = len(KnowledgeRetriever.collect_image_entries(all_hits))
        logger.info(
            "RAG context ready hits=%d images=%d context_chars=%d",
            len(all_hits),
            image_count,
            len(context),
        )

        history_for_completion = self._history_openai_messages(
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
                    f"Knowledge base context (search queries: {'; '.join(query_labels)}):\n\n"
                    f"{context}"
                ),
            },
            *history_for_completion,
        ]

        try:
            logger.info(
                "OpenAI completion start model=%s vision=%s",
                self._settings.openai_model,
                any(
                    isinstance(m.get("content"), list)
                    for m in history_for_completion
                    if m.get("role") == "user"
                ),
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
    ) -> AssistantReply:
        conversation = self._repo.get_or_create_conversation(
            whatsapp_user_id, display_name=display_name
        )
        is_first_message = self._is_first_customer_message(conversation.id)
        logger.info(
            "Chat start wa_id=%s conv_id=%s first=%s msg=%s",
            whatsapp_user_id,
            str(conversation.id),
            is_first_message,
            _preview(user_message, 180),
        )
        self._repo.add_message(
            conversation.id,
            MessageRole.USER,
            user_message,
            whatsapp_message_id=whatsapp_message_id,
            message_type=MessageType.TEXT,
        )

        greeting = self._maybe_first_message_greeting(
            conversation.id, whatsapp_user_id, is_first_message=is_first_message
        )
        if greeting:
            self._save_assistant_reply(conversation.id, greeting)
            self._session.commit()
            return greeting

        raw = self._complete_conversation(conversation.id, user_message)
        reply = self._parse_and_log_reply(raw)
        self._save_assistant_reply(conversation.id, reply)
        self._session.commit()
        return reply
    def _refine_retrieval_query(
        self, original_query: str, user_message: str, weak_context: str
    ) -> str:
        """Ask the model for a better search query when the first retrieval was weak."""
        prompt = (
            "The following search query returned weak/low-relevance results from a "
            "knowledge base. Suggest ONE alternative search query that might retrieve "
            "better matches. Consider synonyms, more specific terms, or a different "
            "angle on the same question. Output ONLY the new query text.\n\n"
            f"Original query: {original_query}\n"
            f"Customer's actual message: {user_message}\n"
            f"Weak results preview: {weak_context[:400]}"
        )
        try:
            response = self._client.chat.completions.create(
                model=self._settings.openai_retrieval_query_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            refined = (response.choices[0].message.content or "").strip()
            logger.info("RAG refinement query=%s", _preview(refined, 160))
            return refined or original_query
        except Exception:
            logger.exception("RAG query refinement failed")
            return original_query
        
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
    ) -> AssistantReply:
        conversation = self._repo.get_or_create_conversation(
            whatsapp_user_id, display_name=display_name
        )
        is_first_message = self._is_first_customer_message(conversation.id)
        caption_text = (caption or "").strip()
        content = caption_text or "[Image]"
        logger.info(
            "Image received wa_id=%s conv_id=%s first=%s key=%s url=%s caption=%s",
            whatsapp_user_id,
            str(conversation.id),
            is_first_message,
            media_key,
            media_url,
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

        greeting = self._maybe_first_message_greeting(
            conversation.id, whatsapp_user_id, is_first_message=is_first_message
        )
        if greeting:
            self._save_assistant_reply(conversation.id, greeting)
            self._session.commit()
            return greeting

        query_hint = caption_text or "[Customer sent an image]"
        raw = self._complete_conversation(conversation.id, query_hint)
        reply = self._parse_and_log_reply(raw)
        self._save_assistant_reply(conversation.id, reply)
        self._session.commit()
        return reply
