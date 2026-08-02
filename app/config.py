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
    rag_image_top_k: int = 12
    rag_image_candidate_k: int = 40
    retrieval_history_messages: int = 5
    completion_history_messages: int = 10
    rag_confidence_threshold: float = 0.4
    rag_max_retrieval_rounds: int = 2

    # Reranking (Cohere)
    cohere_api_key: str = ""
    cohere_rerank_model: str = "rerank-english-v3.0"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_retrieval_query_model: str = "gpt-4o-mini"
    openai_vision_detail: str = "auto"
    max_outbound_images: int = 5

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
    first_message_greeting_enabled: bool = True
    first_message_greeting: str = ""
    admin_api_key: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_access_token_exp_minutes: int = 720
    cors_allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,https://dashboard.fmfurnisteel.com"
    )

    # Cloudflare R2 (S3-compatible) for WhatsApp image storage
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_url_base: str = ""
    r2_key_prefix: str = "whatsapp"
    r2_endpoint_url: str = ""
    r2_region: str = "auto"

    @property
    def chroma_http_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

    def resolved_first_message_greeting(self) -> str:
        """Greeting sent on a customer's first message (no RAG). Set via FIRST_MESSAGE_GREETING in .env."""
        default = (
            "Hello! Thank you for contacting {company_name}.\n\n"
            "I'm here to help with questions about our products, services, and past projects. "
            "How can I assist you today?"
        )
        template = (self.first_message_greeting or default).strip()
        text = template.replace("{company_name}", self.company_name)
        return text.replace("\\n", "\n")


@lru_cache
def get_settings() -> Settings:
    return Settings()
