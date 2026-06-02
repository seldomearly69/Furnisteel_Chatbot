"""Section-aware markdown chunking with complete section boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import get_settings

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class MarkdownSection:
    heading_line: str | None
    level: int
    body: str
    breadcrumb: list[str] = field(default_factory=list)

    def render(self) -> str:
        if self.heading_line:
            body = self.body.strip()
            return f"{self.heading_line}\n\n{body}" if body else self.heading_line
        return self.body.strip()


@lru_cache
def _get_tokenizer():
    settings = get_settings()
    import tiktoken

    try:
        return tiktoken.encoding_for_model(settings.chunk_tokenizer_model)
    except KeyError:
        # Safe default for most OpenAI models
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text.strip():
        return 0
    return len(_get_tokenizer().encode(text))


def parse_markdown_sections(content: str) -> list[MarkdownSection]:
    """Split markdown into sections at ATX heading boundaries (# .. ######)."""
    sections: list[MarkdownSection] = []
    heading_stack: list[tuple[int, str, str]] = []

    current_heading_line: str | None = None
    current_level = 0
    current_body: list[str] = []

    def breadcrumb() -> list[str]:
        return [title for _, title, _ in heading_stack]

    def flush() -> None:
        nonlocal current_heading_line, current_level, current_body
        body = "\n".join(current_body).strip()
        if current_heading_line is None and not body:
            current_body = []
            return

        sections.append(
            MarkdownSection(
                heading_line=current_heading_line,
                level=current_level,
                body=body,
                breadcrumb=breadcrumb(),
            )
        )
        current_heading_line = None
        current_level = 0
        current_body = []

    for line in content.splitlines():
        match = HEADING_PATTERN.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack[:] = [entry for entry in heading_stack if entry[0] < level]
            heading_stack.append((level, title, line))
            current_heading_line = line
            current_level = level
        else:
            current_body.append(line)

    flush()

    if not sections and content.strip():
        sections.append(
            MarkdownSection(
                heading_line=None,
                level=0,
                body=content.strip(),
                breadcrumb=[],
            )
        )

    return sections


def _split_section_by_paragraphs(
    section: MarkdownSection, max_tokens: int
) -> list[str]:
    """Split an oversized section on paragraph boundaries (never mid-paragraph)."""
    prefix = f"{section.heading_line}\n\n" if section.heading_line else ""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section.body) if p.strip()]
    if not paragraphs:
        rendered = section.render()
        return [rendered] if rendered else []

    def render_paragraphs(paras: list[str]) -> str:
        body = "\n\n".join(paras)
        return f"{prefix}{body}".strip() if prefix else body

    chunks: list[str] = []
    current_paras: list[str] = []

    for paragraph in paragraphs:
        trial_paras = current_paras + [paragraph]
        trial_text = render_paragraphs(trial_paras)

        if count_tokens(trial_text) <= max_tokens:
            current_paras = trial_paras
            continue

        if current_paras:
            chunks.append(render_paragraphs(current_paras))
            current_paras = []

        single_text = render_paragraphs([paragraph])
        if count_tokens(single_text) <= max_tokens:
            current_paras = [paragraph]
        else:
            chunks.append(single_text)

    if current_paras:
        chunks.append(render_paragraphs(current_paras))

    return chunks


def chunk_markdown_sections(
    sections: list[MarkdownSection],
    max_tokens: int | None = None,
) -> list[str]:
    """
    Accumulate whole sections into chunks until the token limit would be exceeded.

    Sections are never cut mid-heading. If one section alone exceeds the limit,
    it is split only on blank-line paragraph boundaries.
    """
    settings = get_settings()
    limit = max_tokens or settings.chunk_max_tokens

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current_parts, current_tokens
        if current_parts:
            chunks.append("\n\n".join(current_parts))
        current_parts = []
        current_tokens = 0

    for section in sections:
        section_text = section.render()
        if not section_text:
            continue

        section_tokens = count_tokens(section_text)

        if section_tokens > limit:
            flush()
            chunks.extend(_split_section_by_paragraphs(section, limit))
            continue

        separator_tokens = 2 if current_parts else 0
        projected = current_tokens + separator_tokens + section_tokens

        if current_parts and projected > limit:
            flush()
            current_parts = [section_text]
            current_tokens = section_tokens
        else:
            current_parts.append(section_text)
            current_tokens = projected

    flush()
    return chunks
