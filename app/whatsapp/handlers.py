"""WhatsApp Cloud API webhook handlers via pywa."""

from __future__ import annotations

import logging

from pywa_async import WhatsApp, filters, types

from app.chat.service import ChatService
from app.config import get_settings
from app.db.session import get_session_factory
from app.storage.r2 import get_r2_storage

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


async def _download_image_bytes(message: types.Message) -> tuple[bytes, str]:
    image = message.image
    if image is None:
        raise ValueError("WhatsApp message does not include image metadata")

    mime_type = getattr(image, "mime_type", None) or "image/jpeg"
    if hasattr(image, "get_bytes"):
        data = await image.get_bytes()
        return data, mime_type

    if hasattr(message, "get_media_bytes"):
        data = await message.get_media_bytes()
        return data, mime_type

    raise RuntimeError("Unable to download image bytes from WhatsApp message")


def register_whatsapp_handlers(wa: WhatsApp) -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    r2 = get_r2_storage()

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

    @wa.on_message(filters.image)
    async def on_image(_wa: WhatsApp, message: types.Message):
        user_id = message.from_user.wa_id
        display_name = message.from_user.name
        caption = (message.caption or "").strip() or None

        if not r2.is_configured():
            logger.error("Image received but R2 storage is not configured")
            await message.reply_text(
                f"Thanks for reaching out to {settings.company_name}. "
                "We are unable to receive images right now. Please send your question as text."
            )
            return

        try:
            image_bytes, mime_type = await _download_image_bytes(message)
        except Exception:
            logger.exception("Failed to download WhatsApp image wa_id=%s", user_id)
            await message.reply_text(
                "Sorry, we could not download your image. Please try sending it again."
            )
            return

        try:
            media_key, media_url = r2.upload_image(
                whatsapp_user_id=user_id,
                whatsapp_message_id=message.id,
                data=image_bytes,
                mime_type=mime_type,
            )
        except Exception:
            logger.exception("Failed to upload image to R2 wa_id=%s", user_id)
            await message.reply_text(
                "Sorry, we could not save your image. Please try again in a moment."
            )
            return

        with session_factory() as session:
            service = ChatService(session)
            reply = service.handle_image_message(
                whatsapp_user_id=user_id,
                display_name=display_name,
                whatsapp_message_id=message.id,
                media_url=media_url,
                media_key=media_key,
                media_mime_type=mime_type,
                caption=caption,
            )

        await message.reply_text(reply)

    @wa.on_message(~filters.text & ~filters.image)
    async def on_unsupported(_wa: WhatsApp, message: types.Message):
        await message.reply_text(
            f"Thanks for reaching out to {settings.company_name}. "
            "Please send your question as a text message or an image so I can assist you."
        )

    logger.info("WhatsApp handlers registered")
