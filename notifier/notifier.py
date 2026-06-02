from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import DateTime, String, func

logging.basicConfig(
    level=os.getenv("NOTIFIER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("notifier")


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True)
    whatsapp_user_id: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class Settings:
    database_url: str

    # Scheduling
    notifier_timezone: str = "Asia/Singapore"
    notifier_cron: str = "0 9 * * *"  # minute hour day month day_of_week
    run_on_start: bool = False

    # Email
    email_to: str = ""
    email_subject: str = "New WhatsApp customers (last 24h)"

    # Gmail / Google Workspace SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # use Google "App Password" (recommended)
    smtp_from: str = ""  # usually same as smtp_user
    smtp_starttls: bool = True

    @staticmethod
    def from_env() -> "Settings":
        def getenv(name: str, default: str = "") -> str:
            return os.getenv(name, default).strip()

        def getbool(name: str, default: str = "false") -> bool:
            return getenv(name, default).lower() in {"1", "true", "yes", "y", "on"}

        db = getenv("DATABASE_URL")
        if not db:
            raise RuntimeError("DATABASE_URL is required for notifier")

        return Settings(
            database_url=db,
            notifier_timezone=getenv("NOTIFIER_TIMEZONE", "Asia/Singapore"),
            notifier_cron=getenv("NOTIFIER_CRON", "0 9 * * *"),
            run_on_start=getbool("NOTIFIER_RUN_ON_START", "false"),
            email_to=getenv("NEW_CUSTOMERS_EMAIL_TO"),
            email_subject=getenv(
                "NEW_CUSTOMERS_EMAIL_SUBJECT", "New WhatsApp customers (last 24h)"
            ),
            smtp_host=getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(getenv("SMTP_PORT", "587") or "587"),
            smtp_user=getenv("SMTP_USER"),
            smtp_password=getenv("SMTP_PASSWORD"),
            smtp_from=getenv("SMTP_FROM"),
            smtp_starttls=getbool("SMTP_STARTTLS", "true"),
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_new_customers(settings: Settings) -> list[Conversation]:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    since = _utcnow() - timedelta(hours=24)
    with Session() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.created_at >= since)
            .order_by(Conversation.created_at.desc())
        )
        return list(session.scalars(stmt))


def _render_email_body(settings: Settings, customers: list[Conversation]) -> str:
    tz = ZoneInfo(settings.notifier_timezone)
    window_end = _utcnow()
    window_start = window_end - timedelta(hours=24)

    lines: list[str] = []
    lines.append("Furnisteel WhatsApp Chatbot — Daily new customer report")
    lines.append("")
    lines.append(
        "Window: "
        f"{window_start.astimezone(tz).isoformat()} → {window_end.astimezone(tz).isoformat()}"
    )
    lines.append(f"Total new customers: {len(customers)}")
    lines.append("")

    if not customers:
        lines.append("No new customers in the last 24 hours.")
        return "\n".join(lines)

    lines.append("New customers:")
    for c in customers:
        created_local = c.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
        name = c.display_name or "-"
        lines.append(f"- {created_local} | wa_id={c.whatsapp_user_id} | name={name}")

    return "\n".join(lines)


def _send_email(settings: Settings, body: str) -> None:
    if not settings.email_to:
        raise RuntimeError("NEW_CUSTOMERS_EMAIL_TO is required")
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is required")
    if not settings.smtp_user:
        raise RuntimeError("SMTP_USER is required")
    if not settings.smtp_password:
        raise RuntimeError("SMTP_PASSWORD is required")

    from_addr = settings.smtp_from or settings.smtp_user

    msg = EmailMessage()
    msg["Subject"] = settings.email_subject
    msg["From"] = from_addr
    msg["To"] = settings.email_to
    msg.set_content(body)

    logger.info(
        "Sending email via SMTP host=%s:%s to=%s subject=%s",
        settings.smtp_host,
        settings.smtp_port,
        settings.email_to,
        settings.email_subject,
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.ehlo()
        if settings.smtp_starttls:
            server.starttls()
            server.ehlo()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def run_once() -> None:
    settings = Settings.from_env()
    logger.info("Notifier run: fetching new customers (last 24h)")
    customers = _fetch_new_customers(settings)
    body = _render_email_body(settings, customers)
    _send_email(settings, body)
    logger.info("Notifier run: done (customers=%d)", len(customers))


def main() -> None:
    settings = Settings.from_env()
    tz = ZoneInfo(settings.notifier_timezone)

    trigger = CronTrigger.from_crontab(settings.notifier_cron, timezone=tz)
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(run_once, trigger, id="daily_new_customers", replace_existing=True)

    logger.info(
        "Notifier scheduled cron=%s tz=%s run_on_start=%s",
        settings.notifier_cron,
        settings.notifier_timezone,
        settings.run_on_start,
    )

    if settings.run_on_start:
        try:
            run_once()
        except Exception:
            logger.exception("Notifier run_on_start failed")

    scheduler.start()


if __name__ == "__main__":
    main()

