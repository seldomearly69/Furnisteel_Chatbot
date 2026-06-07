"""Detect customer requests for project images / gallery content."""

from __future__ import annotations

_IMAGE_INTENT_KEYWORDS = (
    "image",
    "images",
    "photo",
    "photos",
    "picture",
    "pictures",
    "gallery",
    "portfolio",
    "past work",
    "past project",
    "project photo",
    "work photo",
    "examples",
    "show me",
    "see your",
    "visual",
    "looks like",
)


def is_image_intent(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in _IMAGE_INTENT_KEYWORDS)
