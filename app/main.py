"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings
from app.db.repository import ChatRepository
from app.db.session import get_session_factory
from app.db.session import init_db
from app.ingestion.pipeline import DocumentIngestionPipeline
from app.rag.chroma_store import ChromaKnowledgeStore
from app.whatsapp.handlers import register_whatsapp_handlers

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings = get_settings()
    Path(settings.documents_dir).mkdir(parents=True, exist_ok=True)
    logger.info("Database initialized; documents dir: %s", settings.documents_dir)
    yield


app = FastAPI(
    title="Furnisteel WhatsApp Chatbot",
    description="Customer-facing WhatsApp bot with RAG and PostgreSQL chat history",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the local admin UI to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _configure_whatsapp() -> None:
    settings = get_settings()
    if not settings.whatsapp_token or not settings.whatsapp_phone_id:
        logger.warning(
            "WhatsApp credentials not configured; webhook endpoints disabled"
        )
        return

    from pywa_async import WhatsApp

    wa = WhatsApp(
        phone_id=settings.whatsapp_phone_id,
        token=settings.whatsapp_token,
        server=app,
        verify_token=settings.whatsapp_verify_token,
        app_id=settings.whatsapp_app_id,
        app_secret=settings.whatsapp_app_secret or None,
        callback_url=settings.whatsapp_callback_url or None,
    )
    register_whatsapp_handlers(wa)
    logger.info("WhatsApp webhook configured")


_configure_whatsapp()

@app.get("/health")
async def health():
    settings = get_settings()
    store = ChromaKnowledgeStore()
    return {
        "status": "ok",
        "company": settings.company_name,
        "knowledge_chunks": store.count(),
    }


class IngestResponse(BaseModel):
    files: int
    chunks: int
    skipped: int
    errors: int


class IngestStartedResponse(BaseModel):
    message: str


@app.post("/admin/ingest", response_model=IngestStartedResponse)
async def ingest_documents(background_tasks: BackgroundTasks, force: bool = False):
    def run_ingest():
        pipeline = DocumentIngestionPipeline()
        pipeline.ingest_all(force=force)

    background_tasks.add_task(run_ingest)
    return IngestStartedResponse(
        message="Ingestion started in background. Use /admin/ingest/sync for results."
    )


@app.post("/admin/ingest/sync", response_model=IngestResponse)
async def ingest_documents_sync(force: bool = False):
    pipeline = DocumentIngestionPipeline()
    stats = pipeline.ingest_all(force=force)
    return IngestResponse(**stats)


@app.post("/admin/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".md", ".markdown"}:
        raise HTTPException(status_code=400, detail="Only Markdown files are supported")

    dest_dir = Path(settings.documents_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / (file.filename or "upload.bin")
    content = await file.read()
    dest_path.write_bytes(content)

    pipeline = DocumentIngestionPipeline()
    count = pipeline.ingest_file(dest_path)
    return {"filename": dest_path.name, "chunks_ingested": count}


class ConversationRow(BaseModel):
    id: str
    whatsapp_user_id: str
    display_name: str | None
    created_at: str
    updated_at: str
    message_count: int
    last_message_preview: str | None


class MessageRow(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


@app.get("/admin/conversations", response_model=list[ConversationRow])
async def list_conversations(limit: int = 200, offset: int = 0):
    session_factory = get_session_factory()
    with session_factory() as session:
        repo = ChatRepository(session)
        conversations = repo.list_conversations(limit=limit, offset=offset)
        counts = repo.get_message_counts([c.id for c in conversations])

        rows: list[ConversationRow] = []
        for conv in conversations:
            last_msgs = repo.get_recent_messages(conv.id, limit=1)
            last_preview = last_msgs[0].content[:120] if last_msgs else None
            rows.append(
                ConversationRow(
                    id=str(conv.id),
                    whatsapp_user_id=conv.whatsapp_user_id,
                    display_name=conv.display_name,
                    created_at=conv.created_at.isoformat(),
                    updated_at=conv.updated_at.isoformat(),
                    message_count=counts.get(conv.id, 0),
                    last_message_preview=last_preview,
                )
            )
        return rows


@app.get("/admin/conversations/{conversation_id}/messages", response_model=list[MessageRow])
async def get_conversation_messages(conversation_id: str, limit: int = 500, offset: int = 0):
    import uuid

    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid conversation id") from e

    session_factory = get_session_factory()
    with session_factory() as session:
        repo = ChatRepository(session)
        conv = repo.get_conversation(conv_uuid)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        msgs = repo.get_messages(conv_uuid, limit=limit, offset=offset)
        return [
            MessageRow(
                id=str(m.id),
                role=m.role.value,
                content=m.content,
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ]
