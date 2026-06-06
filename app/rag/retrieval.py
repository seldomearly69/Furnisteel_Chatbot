"""RAG retrieval: query generation, vector search, Cohere rerank."""

from __future__ import annotations

import logging

from openai import OpenAI

from app.config import get_settings
from app.rag.chroma_store import ChromaKnowledgeStore
from app.rag.rerank import CohereReranker
from app.utils.openai_content import content_as_text

logger = logging.getLogger(__name__)

def _preview(text: str, limit: int = 240) -> str:
    text = (text or "").replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


RETRIEVAL_QUERY_SYSTEM = """You generate search queries for a company knowledge base.

Given the recent conversation (especially the latest user messages), write one concise search query that will retrieve the most relevant documentation.

Rules:
- Output ONLY the query text (no quotes, labels, or explanation).
- Resolve pronouns and follow-ups using conversation context (e.g. "it" → the product being discussed).
- Include product names, model numbers, policies, or technical terms when relevant.
- Prefer specific nouns over full sentences.
"""


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

    def generate_retrieval_query(self, history: list[dict]) -> str:
        """Turn the last N conversation messages into a search query via OpenAI."""
        if not history:
            return ""

        if len(history) == 1 and history[0].get("role") == "user":
            query = content_as_text(history[0]["content"]).strip()
            logger.info("RAG querygen bypass (single user msg): %s", _preview(query, 120))
            return query

        logger.info(
            "RAG querygen input messages=%d last=%s",
            len(history),
            _preview(content_as_text(history[-1].get("content", "")), 160),
        )
        response = self._client.chat.completions.create(
            model=self._settings.openai_retrieval_query_model,
            messages=[
                {"role": "system", "content": RETRIEVAL_QUERY_SYSTEM},
                *history,
            ],
            temperature=0.0,
        )
        query = (response.choices[0].message.content or "").strip()
        logger.info("RAG querygen output: %s", _preview(query, 200))
        return query

    def retrieve(self, query: str) -> list[dict]:
        """Embed-search in ChromaDB, then rerank candidates with Cohere."""
        if not query.strip():
            return []

        logger.info(
            "RAG vector search start candidates_k=%d query=%s",
            self._settings.rag_candidate_k,
            _preview(query, 160),
        )
        candidates = self._store.query(query, top_k=self._settings.rag_candidate_k)
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

        if not self._settings.cohere_api_key:
            logger.warning(
                "COHERE_API_KEY not set; returning vector search results without rerank"
            )
            return candidates[: self._settings.rag_top_k]

        logger.info(
            "RAG rerank start model=%s top_n=%d",
            self._settings.cohere_rerank_model,
            self._settings.rag_top_k,
        )
        ranked = self._get_reranker().rerank(
            query=query,
            documents=[c["text"] for c in candidates],
            top_n=self._settings.rag_top_k,
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
                "RAG hit[%d] score=%.4f source=%s chunk=%s text=%s",
                i,
                float(h.get("rerank_score") or 0.0),
                meta.get("source_file", "unknown"),
                meta.get("chunk_index", "?"),
                _preview(h.get("text", ""), 200),
            )
        return hits

    @staticmethod
    def format_context(hits: list[dict]) -> str:
        if not hits:
            return "No relevant knowledge base entries found."

        parts: list[str] = []
        for index, hit in enumerate(hits, start=1):
            source = hit["metadata"].get("source_file", "unknown")
            score = hit.get("rerank_score")
            header = f"[{index}] Source: {source}"
            if score is not None:
                header += f" (relevance: {score:.3f})"
            parts.append(f"{header}\n{hit['text']}")
        return "\n\n---\n\n".join(parts)
