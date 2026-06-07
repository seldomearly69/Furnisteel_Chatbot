"""Deliver assistant replies to WhatsApp (text + images)."""

from __future__ import annotations

import logging

from pywa_async import types

from app.chat.reply_parser import AssistantReply

logger = logging.getLogger(__name__)


async def deliver_assistant_reply(
    message: types.Message, reply: AssistantReply
) -> None:
    text = reply.text.strip()
    if text:
        await message.reply_text(text)

    for index, url in enumerate(reply.image_urls):
        try:
            await message.reply_image(image=url)
            logger.info("WhatsApp image sent wa_id=%s url=%s", message.from_user.wa_id, url)
        except Exception:
            logger.exception(
                "Failed to send WhatsApp image wa_id=%s index=%d url=%s",
                message.from_user.wa_id,
                index,
                url,
            )
