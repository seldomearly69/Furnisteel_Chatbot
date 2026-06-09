"""FastAPI application entry point."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pathlib import Path

import jwt
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings
from app.db.models import ChatMessage, MessageType
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

# Allow the admin UI to call this API from the browser.
_cors_origins = [
    origin.strip()
    for origin in get_settings().cors_allowed_origins.split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _create_access_token() -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin",
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.jwt_access_token_exp_minutes)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _require_admin_token(authorization: str | None = None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"verify_exp": True, "require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    if payload.get("sub") != "admin":
        raise HTTPException(status_code=401, detail="Invalid token subject")
    return token


def _admin_auth_dep(authorization: str | None = Header(default=None)):
    _require_admin_token(authorization=authorization)
    return True


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


class AdminLoginRequest(BaseModel):
    api_key: str


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


@app.post("/admin/auth/token", response_model=AdminTokenResponse)
async def admin_token(body: AdminLoginRequest):
    settings = get_settings()
    if not settings.admin_api_key:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY is not configured")
    if body.api_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return AdminTokenResponse(
        access_token=_create_access_token(),
        expires_in_seconds=settings.jwt_access_token_exp_minutes * 60,
    )


@app.post("/admin/ingest", response_model=IngestStartedResponse)
async def ingest_documents(
    background_tasks: BackgroundTasks,
    force: bool = False,
    _auth=Depends(_admin_auth_dep),
):
    def run_ingest():
        pipeline = DocumentIngestionPipeline()
        pipeline.ingest_all(force=force)

    background_tasks.add_task(run_ingest)
    return IngestStartedResponse(
        message="Ingestion started in background. Use /admin/ingest/sync for results."
    )


@app.post("/admin/ingest/sync", response_model=IngestResponse)
async def ingest_documents_sync(force: bool = False, _auth=Depends(_admin_auth_dep)):
    pipeline = DocumentIngestionPipeline()
    stats = pipeline.ingest_all(force=force)
    return IngestResponse(**stats)


@app.post("/admin/documents/upload")
async def upload_document(file: UploadFile = File(...), _auth=Depends(_admin_auth_dep)):
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
    message_type: str = "text"
    media_url: str | None = None
    media_mime_type: str | None = None


class MessagesPage(BaseModel):
    messages: list[MessageRow]
    has_more: bool


def _serialize_messages(msgs: list[ChatMessage]) -> list[MessageRow]:
    return [
        MessageRow(
            id=str(m.id),
            role=m.role.value,
            content=m.content,
            created_at=m.created_at.isoformat(),
            message_type=m.message_type or MessageType.TEXT.value,
            media_url=m.media_url,
            media_mime_type=m.media_mime_type,
        )
        for m in msgs
    ]


def _message_preview(message: ChatMessage, limit: int = 120) -> str:
    if message.message_type == MessageType.IMAGE.value:
        caption = (message.content or "").strip()
        if caption and caption != "[Image]":
            text = f"📷 {caption}"
        else:
            text = "📷 Image"
    else:
        text = message.content or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


@app.get("/admin/conversations", response_model=list[ConversationRow])
async def list_conversations(
    limit: int = 200, offset: int = 0, _auth=Depends(_admin_auth_dep)
):
    session_factory = get_session_factory()
    with session_factory() as session:
        repo = ChatRepository(session)
        conversations = repo.list_conversations(limit=limit, offset=offset)
        counts = repo.get_message_counts([c.id for c in conversations])

        rows: list[ConversationRow] = []
        for conv in conversations:
            last_msgs = repo.get_recent_messages(conv.id, limit=1)
            last_preview = _message_preview(last_msgs[0]) if last_msgs else None
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


@app.get(
    "/admin/conversations/{conversation_id}/messages",
    response_model=MessagesPage,
)
async def get_conversation_messages(
    conversation_id: str,
    limit: int = 50,
    before: str | None = None,
    after: str | None = None,
    _auth=Depends(_admin_auth_dep),
):
    import uuid
    from datetime import datetime

    if before and after:
        raise HTTPException(
            status_code=400, detail="Use either before or after, not both"
        )
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")

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

        if after:
            try:
                after_dt = datetime.fromisoformat(after)
            except ValueError as e:
                raise HTTPException(status_code=400, detail="Invalid after timestamp") from e
            msgs = repo.get_messages_after(conv_uuid, after_dt, limit=limit)
            return MessagesPage(messages=_serialize_messages(msgs), has_more=False)

        if before:
            try:
                before_dt = datetime.fromisoformat(before)
            except ValueError as e:
                raise HTTPException(
                    status_code=400, detail="Invalid before timestamp"
                ) from e
            msgs = repo.get_messages_before(conv_uuid, before_dt, limit=limit)
            has_more = bool(
                msgs
                and repo.has_messages_before(conv_uuid, msgs[0].created_at)
            )
            return MessagesPage(messages=_serialize_messages(msgs), has_more=has_more)

        msgs = repo.get_latest_messages(conv_uuid, limit=limit)
        has_more = bool(
            msgs and repo.has_messages_before(conv_uuid, msgs[0].created_at)
        )
        return MessagesPage(messages=_serialize_messages(msgs), has_more=has_more)
