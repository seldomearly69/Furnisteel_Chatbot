"""Extract image URLs and titles from gallery markdown chunks."""

from __future__ import annotations

import re

IMAGE_URL_RE = re.compile(r"\*\*Image URL:\*\*\s*(https?://\S+)", re.IGNORECASE)
SECTION_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def extract_image_url(text: str) -> str | None:
    match = IMAGE_URL_RE.search(text)
    if not match:
        return None
    return match.group(1).rstrip(")")


def extract_section_title(text: str) -> str | None:
    match = SECTION_HEADING_RE.search(text)
    if not match:
        return None
    return match.group(1).strip()


def section_has_image_url(section_body: str) -> bool:
    return "**Image URL:**" in section_body
