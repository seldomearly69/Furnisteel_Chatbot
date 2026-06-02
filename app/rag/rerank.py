from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


@lru_cache
def _get_cohere_client():
    import cohere

    settings = get_settings()
    if not settings.cohere_api_key:
        raise RuntimeError("COHERE_API_KEY must be set to use reranking")
    return cohere.Client(api_key=settings.cohere_api_key)


class CohereReranker:
    def __init__(self):
        self._settings = get_settings()
        if not self._settings.cohere_api_key:
            raise RuntimeError("COHERE_API_KEY must be set to use reranking")

    def rerank(
        self, query: str, documents: list[str], top_n: int
    ) -> list[RerankResult]:
        if not documents:
            return []

        client = _get_cohere_client()
        response = client.rerank(
            model=self._settings.cohere_rerank_model,
            query=query,
            documents=documents,
            top_n=min(top_n, len(documents)),
        )

        return [
            RerankResult(index=item.index, score=item.relevance_score)
            for item in response.results
        ]
