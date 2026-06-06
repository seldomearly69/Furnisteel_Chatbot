from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.models import Base


def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def _migrate_chat_messages(engine) -> None:
    inspector = inspect(engine)
    if "chat_messages" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("chat_messages")}
    statements: list[str] = []

    if "message_type" not in existing:
        statements.append(
            "ALTER TABLE chat_messages "
            "ADD COLUMN message_type VARCHAR(32) NOT NULL DEFAULT 'text'"
        )
    if "media_url" not in existing:
        statements.append(
            "ALTER TABLE chat_messages ADD COLUMN media_url VARCHAR(1024)"
        )
    if "media_key" not in existing:
        statements.append(
            "ALTER TABLE chat_messages ADD COLUMN media_key VARCHAR(512)"
        )
    if "media_mime_type" not in existing:
        statements.append(
            "ALTER TABLE chat_messages ADD COLUMN media_mime_type VARCHAR(128)"
        )

    if not statements:
        return

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_chat_messages(engine)
