from __future__ import annotations

import logging

import chromadb

from app.config import get_settings
from app.rag.embeddings import get_chroma_embedding_function

logger = logging.getLogger(__name__)


class ChromaKnowledgeStore:
    def __init__(self):
        settings = get_settings()
        self._client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        self._embed = get_chroma_embedding_function()  # local only, never sent to server
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(self, records: list[dict], source_id: str) -> None:
        if not records:
            return
        self.delete_source(source_id)
        texts = [r["text"] for r in records]
        self._collection.add(
            ids=[r["id"] for r in records],
            documents=texts,
            embeddings=self._embed(texts),  # pre-computed locally
            metadatas=[r["metadata"] for r in records],
        )

    def query(self, text: str, top_k: int | None = None) -> list[dict]:
        settings = get_settings()
        k = top_k or settings.rag_top_k
        result = self._collection.query(
            query_embeddings=self._embed([text]),  # not query_texts
            n_results=k,
        )
        hits: list[dict] = []
        if not result.get("documents"):
            return hits

        for doc, meta, distance in zip(
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ):
            hits.append(
                {
                    "text": doc,
                    "metadata": meta,
                    "distance": distance,
                }
            )
        return hits

    def delete_source(self, source_id: str) -> None:
        try:
            self._collection.delete(where={"file_hash": source_id})
        except Exception:
            logger.debug("No existing chunks for source %s", source_id)

    def has_source(self, source_id: str) -> bool:
        result = self._collection.get(where={"file_hash": source_id}, limit=1)
        return bool(result.get("ids"))

    def count(self) -> int:
        return self._collection.count()
