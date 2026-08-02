"""RAG retrieval: query generation, vector search, Cohere rerank."""

from __future__ import annotations

import logging

from openai import OpenAI

from app.config import get_settings
from app.ingestion.image_metadata import extract_image_url, extract_section_title
from app.rag.chroma_store import ChromaKnowledgeStore
from app.rag.image_intent import is_image_intent
from app.rag.rerank import CohereReranker
from app.utils.openai_content import content_as_text

logger = logging.getLogger(__name__)

def _preview(text: str, limit: int = 240) -> str:
    text = (text or "").replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


# RETRIEVAL_QUERY_SYSTEM = """You generate search queries for a company knowledge base.

# Given the recent conversation (especially the latest user messages), write one concise search query that will retrieve the most relevant documentation.

# Rules:
# - Output ONLY the query text (no quotes, labels, or explanation).
# - Resolve pronouns and follow-ups using conversation context (e.g. "it" → the product being discussed).
# - Include product names, model numbers, policies, or technical terms when relevant.
# - Prefer specific nouns over full sentences.
# """


class KnowledgeRetriever:
    def __init__(
        self,
        openai_client: OpenAI,
        store: ChromaKnowledgeStore | None = None,
        reranker: CohereReranker | None = None,
    ):
        self._client = openai_client
        self._store = store or ChromaKnowledgeStore()
        self._settings = get_settings()
        self._reranker = reranker

    def _get_reranker(self) -> CohereReranker:
        if self._reranker is None:
            self._reranker = CohereReranker()
        return self._reranker

    # def generate_retrieval_query(self, history: list[dict]) -> str:
    #     """Turn the last N conversation messages into a search query via OpenAI."""
    #     if not history:
    #         return ""

    #     if len(history) == 1 and history[0].get("role") == "user":
    #         query = content_as_text(history[0]["content"]).strip()
    #         logger.info("RAG querygen bypass (single user msg): %s", _preview(query, 120))
    #         return query

    #     logger.info(
    #         "RAG querygen input messages=%d last=%s",
    #         len(history),
    #         _preview(content_as_text(history[-1].get("content", "")), 160),
    #     )
    #     response = self._client.chat.completions.create(
    #         model=self._settings.openai_retrieval_query_model,
    #         messages=[
    #             {"role": "system", "content": RETRIEVAL_QUERY_SYSTEM},
    #             *history,
    #         ],
    #         temperature=0.0,
    #     )
    #     query = (response.choices[0].message.content or "").strip()
    #     logger.info("RAG querygen output: %s", _preview(query, 200))
    #     return query

    def retrieve(self, query: str, *, user_message: str = "", skip_rerank: bool = False) -> list[dict]:
        """Embed-search in ChromaDB, then rerank candidates with Cohere."""
        if not query.strip():
            return []

        image_intent = is_image_intent(query) or is_image_intent(user_message)
        top_k = (
            self._settings.rag_image_top_k
            if image_intent
            else self._settings.rag_top_k
        )
        candidate_k = (
            self._settings.rag_image_candidate_k
            if image_intent
            else self._settings.rag_candidate_k
        )

        logger.info(
            "RAG vector search start image_intent=%s candidates_k=%d top_k=%d query=%s",
            image_intent,
            candidate_k,
            top_k,
            _preview(query, 160),
        )
        
        candidates = self._store.query(query, top_k=candidate_k)
        if not image_intent:
            candidates = [c for c in candidates if (c.get("metadata") or {}).get("source_file") != "furnisteel_project_gallery.md"]

        if not candidates:
            logger.info("RAG vector search: 0 candidates")
            return []

        logger.info("RAG vector search: %d candidates", len(candidates))
        for i, c in enumerate(candidates[: min(5, len(candidates))], start=1):
            meta = c.get("metadata") or {}
            logger.debug(
                "RAG candidate[%d] distance=%.4f source=%s chunk=%s text=%s",
                i,
                float(c.get("distance") or 0.0),
                meta.get("source_file", "unknown"),
                meta.get("chunk_index", "?"),
                _preview(c.get("text", ""), 200),
            )

        if skip_rerank:
            logger.info(
                "Rerank skipped. Returning results without rerank"
            )
            return candidates[:top_k]
        
        if not self._settings.cohere_api_key:
            logger.warning(
                "COHERE_API_KEY not set; returning vector search results without rerank"
            )
            return candidates[:top_k]

        logger.info(
            "RAG rerank start model=%s top_n=%d",
            self._settings.cohere_rerank_model,
            top_k,
        )
        ranked = self._get_reranker().rerank(
            query=query,
            documents=[c["text"] for c in candidates],
            top_n=top_k,
        )
        hits: list[dict] = []
        for result in ranked:
            if 0 <= result.index < len(candidates):
                hit = dict(candidates[result.index])
                hit["rerank_score"] = result.score
                hits.append(hit)
        logger.info("RAG rerank done: %d hits", len(hits))
        for i, h in enumerate(hits, start=1):
            meta = h.get("metadata") or {}
            logger.debug(
                "RAG hit[%d] score=%.4f source=%s chunk=%s image=%s text=%s",
                i,
                float(h.get("rerank_score") or 0.0),
                meta.get("source_file", "unknown"),
                meta.get("chunk_index", "?"),
                bool(meta.get("image_url")),
                _preview(h.get("text", ""), 200),
            )
        return hits

    def retrieve_with_confidence(self, query: str, *, user_message: str = "") -> tuple[str, float]:
        hits = self.retrieve(query, user_message=user_message)
        context = self.format_context(hits)
        top_score = max((h.get("rerank_score") or 0.0) for h in hits) if hits else 0.0
        return context, top_score

    def retrieve_images(self, query: str, top_k: int | None = None) -> list[dict]:
        """Retrieve chunks specifically for image/gallery lookups. Only returns
        candidates that have an image_url in metadata — never pricing/spec-only text."""
        k = top_k or self._settings.rag_image_top_k
        candidate_k = self._settings.rag_image_candidate_k

        candidates = self._store.query(query, top_k=candidate_k)
        image_candidates = [c for c in candidates if (c.get("metadata") or {}).get("image_url")]

        logger.info(
            "RAG image search query=%s candidates=%d image_candidates=%d",
            _preview(query, 120), len(candidates), len(image_candidates),
        )

        if not image_candidates:
            return []

        if not self._settings.cohere_api_key:
            return image_candidates[:k]

        ranked = self._get_reranker().rerank(
            query=query,
            documents=[c["text"] for c in image_candidates],
            top_n=min(k, len(image_candidates)),
        )
        hits: list[dict] = []
        for result in ranked:
            if 0 <= result.index < len(image_candidates):
                hit = dict(image_candidates[result.index])
                hit["rerank_score"] = result.score
                hits.append(hit)
        return hits

    @staticmethod
    def collect_image_entries(hits: list[dict]) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        seen: set[str] = set()
        for hit in hits:
            meta = hit.get("metadata") or {}
            url = meta.get("image_url") or extract_image_url(hit.get("text", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            title = meta.get("image_title") or extract_section_title(hit.get("text", ""))
            entries.append((title or "Project image", url))
        return entries

    @classmethod
    def format_context(cls, hits: list[dict]) -> str:
        if not hits:
            return "No relevant knowledge base entries found."

        parts: list[str] = []
        image_entries = cls.collect_image_entries(hits)
        if image_entries:
            lines = [f"- {title}: {url}" for title, url in image_entries]
            parts.append(
                "Available images in retrieved context "
                f"({len(image_entries)} total — use these exact URLs for [[IMAGE:...]]):\n"
                + "\n".join(lines)
            )

        for index, hit in enumerate(hits, start=1):
            source = hit["metadata"].get("source_file", "unknown")
            score = hit.get("rerank_score")
            header = f"[{index}] Source: {source}"
            if score is not None:
                header += f" (relevance: {score:.3f})"
            parts.append(f"{header}\n{hit['text']}")

        return "\n\n---\n\n".join(parts)
