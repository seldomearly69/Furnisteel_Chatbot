"""Text extraction helpers for OpenAI multimodal message payloads."""

from __future__ import annotations

from typing import Any


def content_as_text(content: str | list[dict[str, Any]] | Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return " ".join(parts)
    return str(content or "")
