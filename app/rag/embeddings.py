# app/rag/embeddings.py
from openai import OpenAI
from app.config import get_settings


class OpenAIEmbeddingFunction:
    """Minimal OpenAI embedding function compatible with openai>=1.0."""

    def __init__(self):
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY must be set for OpenAI embeddings")
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model

    def __call__(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(input=texts, model=self._model)
        return [item.embedding for item in response.data]


def get_chroma_embedding_function() -> OpenAIEmbeddingFunction:
    return OpenAIEmbeddingFunction()