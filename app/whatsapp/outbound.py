"""Deliver assistant replies to WhatsApp (text + images)."""

from __future__ import annotations

import logging

from pywa_async import types

from app.chat.reply_parser import AssistantReply

logger = logging.getLogger(__name__)

WHATSAPP_TEXT_LIMIT = 4096

def _split_text_for_whatsapp(text: str, limit: int = WHATSAPP_TEXT_LIMIT) -> list[str]:
    """Split text into WhatsApp-safe chunks, breaking on paragraph/line
    boundaries where possible so items don't get cut mid-sentence."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while len(remaining) > limit:
        # try to break at the last newline before the limit
        split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit * 0.5:
            # no good newline break found, fall back to a hard split
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)

    return chunks

async def deliver_assistant_reply(
    message: types.Message, reply: AssistantReply
) -> None:
    if reply.text:
        for chunk in _split_text_for_whatsapp(reply.text):
            await message.reply_text(chunk)

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
