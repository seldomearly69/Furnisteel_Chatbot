from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg2://furnisteel:changeme@localhost:5432/furnisteel_chat"
    )

    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection: str = "furnisteel_knowledge"

    # Vector embeddings (OpenAI)
    openai_embedding_model: str = "text-embedding-3-small"

    # Chunking/token budgeting
    chunk_max_tokens: int = 512
    chunk_tokenizer_model: str = "gpt-4o-mini"

    # Retrieval
    rag_top_k: int = 5
    rag_candidate_k: int = 25
    retrieval_history_messages: int = 5
    completion_history_messages: int = 10

    # Reranking (Cohere)
    cohere_api_key: str = ""
    cohere_rerank_model: str = "rerank-english-v3.0"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_retrieval_query_model: str = "gpt-4o-mini"

    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_verify_token: str = "furnisteel_verify"
    whatsapp_app_secret: str = ""
    whatsapp_callback_url: str = ""
    whatsapp_app_id: str = ""

    app_host: str = "0.0.0.0"
    app_port: int = 8080
    documents_dir: str = "./data/documents"
    company_name: str = "Furnisteel Systems Pte Ltd"
    admin_api_key: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_access_token_exp_minutes: int = 720

    @property
    def chroma_http_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
