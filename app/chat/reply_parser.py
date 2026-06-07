"""Parse structured image markers from assistant LLM replies."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

IMAGE_MARKER = re.compile(r"\[\[IMAGE:(https?://[^\]\s]+)\]\]", re.IGNORECASE)


@dataclass(frozen=True)
class AssistantReply:
    text: str
    image_urls: list[str] = field(default_factory=list)
    raw: str = ""


def parse_assistant_reply(raw: str, *, max_images: int = 3) -> AssistantReply:
    """Extract [[IMAGE:https://...]] markers and return clean customer-facing text."""
    content = raw or ""
    urls = IMAGE_MARKER.findall(content)
    if len(urls) > max_images:
        logger.warning(
            "Assistant reply had %d images; truncating to %d", len(urls), max_images
        )
        urls = urls[:max_images]

    text = IMAGE_MARKER.sub("", content)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return AssistantReply(text=text, image_urls=urls, raw=content)
