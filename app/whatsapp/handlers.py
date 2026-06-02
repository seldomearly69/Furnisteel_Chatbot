"""WhatsApp Cloud API webhook handlers via pywa."""

from __future__ import annotations

import logging

from pywa_async import WhatsApp, filters, types

from app.chat.service import ChatService
from app.config import get_settings
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)


def _extract_text(message: types.Message) -> str | None:
    if message.type == types.MessageType.TEXT and message.text:
        return message.text.strip()
    if message.type == types.MessageType.BUTTON and message.button:
        return message.button.text.strip()
    if message.type == types.MessageType.INTERACTIVE and message.interactive:
        if message.interactive.button_reply:
            return message.interactive.button_reply.title.strip()
        if message.interactive.list_reply:
            return message.interactive.list_reply.title.strip()
    return None


def register_whatsapp_handlers(wa: WhatsApp) -> None:
    settings = get_settings()
    session_factory = get_session_factory()

    @wa.on_message(filters.text)
    async def on_text(_wa: WhatsApp, message: types.Message):
        user_text = _extract_text(message)
        if not user_text:
            await message.reply_text(
                "I can help with text messages about Furnisteel products and services. "
                "Please send your question as text."
            )
            return

        user_id = message.from_user.wa_id
        display_name = message.from_user.name

        with session_factory() as session:
            service = ChatService(session)
            reply = service.generate_reply(
                whatsapp_user_id=user_id,
                user_message=user_text,
                display_name=display_name,
                whatsapp_message_id=message.id,
            )

        await message.reply_text(reply)

    @wa.on_message(~filters.text)
    async def on_unsupported(_wa: WhatsApp, message: types.Message):
        await message.reply_text(
            f"Thanks for reaching out to {settings.company_name}. "
            "Please send your question as a text message so I can assist you."
        )

    logger.info("WhatsApp handlers registered")
