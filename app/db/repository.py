import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ChatMessage, Conversation, MessageRole


class ChatRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_or_create_conversation(
        self, whatsapp_user_id: str, display_name: str | None = None
    ) -> Conversation:
        stmt = select(Conversation).where(
            Conversation.whatsapp_user_id == whatsapp_user_id
        )
        conversation = self._session.scalar(stmt)
        if conversation:
            if display_name and conversation.display_name != display_name:
                conversation.display_name = display_name
            return conversation

        conversation = Conversation(
            whatsapp_user_id=whatsapp_user_id,
            display_name=display_name,
        )
        self._session.add(conversation)
        self._session.flush()
        return conversation

    def add_message(
        self,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        whatsapp_message_id: str | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            whatsapp_message_id=whatsapp_message_id,
        )
        self._session.add(message)
        self._session.flush()
        return message

    def get_recent_messages(
        self, conversation_id: uuid.UUID, limit: int = 20
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = list(self._session.scalars(stmt))
        messages.reverse()
        return messages

    def list_conversations(
        self, *, limit: int = 200, offset: int = 0
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(stmt))

    def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return self._session.get(Conversation, conversation_id)

    def get_messages(
        self, conversation_id: uuid.UUID, *, limit: int = 200, offset: int = 0
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(stmt))

    def get_message_counts(self, conversation_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not conversation_ids:
            return {}
        stmt = (
            select(ChatMessage.conversation_id, func.count(ChatMessage.id))
            .where(ChatMessage.conversation_id.in_(conversation_ids))
            .group_by(ChatMessage.conversation_id)
        )
        return {cid: int(count) for cid, count in self._session.execute(stmt).all()}
