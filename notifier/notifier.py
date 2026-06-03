from __future__ import annotations

import html
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


def _tz_label(dt: datetime) -> str:
    return dt.tzname() or ""


def _friendly_datetime(dt: datetime, tz: ZoneInfo) -> str:
    """e.g. Mon, 2 Jun 2025 at 9:15 AM (SGT)"""
    local = dt.astimezone(tz)
    hour = local.strftime("%I").lstrip("0") or "12"
    label = _tz_label(local)
    suffix = f" ({label})" if label else ""
    return (
        f"{local.strftime('%a')}, {local.day} {local.strftime('%b %Y')} "
        f"at {hour}:{local.strftime('%M %p')}{suffix}"
    )


def _friendly_range(start: datetime, end: datetime, tz: ZoneInfo) -> str:
    """e.g. 2 Jun 2025, 9:00 AM – 3 Jun 2025, 9:00 AM (SGT)"""
    s = start.astimezone(tz)
    e = end.astimezone(tz)
    label = _tz_label(s) or _tz_label(e)
    suffix = f" ({label})" if label else ""

    def short(d: datetime) -> str:
        hour = d.strftime("%I").lstrip("0") or "12"
        return f"{d.day} {d.strftime('%b %Y')}, {hour}:{d.strftime('%M %p')}"

    return f"{short(s)} – {short(e)}{suffix}"


@dataclass(frozen=True)
class EmailContent:
    plain: str
    html: str


def _render_email(settings: Settings, customers: list[Conversation]) -> EmailContent:
    tz = ZoneInfo(settings.notifier_timezone)
    window_end = _utcnow()
    window_start = window_end - timedelta(hours=24)
    count = len(customers)
    window_text = _friendly_range(window_start, window_end, tz)

    plain_lines: list[str] = [
        "Furnisteel — New WhatsApp customers",
        "",
        f"Report period: {window_text}",
        f"New customers: {count}",
        "",
    ]

    if not customers:
        plain_lines.append("No new customers in the last 24 hours.")
    else:
        plain_lines.append("Customers (newest first):")
        plain_lines.append("")
        for c in customers:
            when = _friendly_datetime(c.created_at, tz)
            name = c.display_name or "—"
            plain_lines.append(f"  • {when}")
            plain_lines.append(f"    Name: {name}")
            plain_lines.append(f"    WhatsApp: {c.whatsapp_user_id}")
            plain_lines.append("")

    plain = "\n".join(plain_lines).rstrip() + "\n"

    if not customers:
        rows_html = (
            '<tr><td colspan="3" style="padding:20px 16px;text-align:center;'
            'color:#667781;font-size:14px;">'
            "No new customers in the last 24 hours."
            "</td></tr>"
        )
    else:
        row_parts: list[str] = []
        for c in customers:
            when = html.escape(_friendly_datetime(c.created_at, tz))
            name = html.escape(c.display_name or "—")
            wa = html.escape(c.whatsapp_user_id)
            row_parts.append(
                f"<tr>"
                f'<td style="padding:12px 16px;border-bottom:1px solid #e9edef;'
                f'color:#111b21;font-size:14px;white-space:nowrap;">{when}</td>'
                f'<td style="padding:12px 16px;border-bottom:1px solid #e9edef;'
                f'color:#111b21;font-size:14px;">{name}</td>'
                f'<td style="padding:12px 16px;border-bottom:1px solid #e9edef;'
                f'color:#54656f;font-size:14px;font-family:ui-monospace,monospace;">'
                f"{wa}</td>"
                f"</tr>"
            )
        rows_html = "\n".join(row_parts)

    count_badge = (
        f'<span style="display:inline-block;background:#25d366;color:#fff;'
        f'font-weight:600;font-size:13px;padding:4px 10px;border-radius:12px;">'
        f"{count}</span>"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(settings.email_subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:560px;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:#075e54;padding:20px 24px;">
              <div style="color:#ffffff;font-size:18px;font-weight:600;line-height:1.3;">
                Furnisteel
              </div>
              <div style="color:#d9fdd3;font-size:13px;margin-top:4px;">
                New WhatsApp customers
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 24px 8px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="font-size:13px;color:#667781;padding-bottom:4px;">Report period</td>
                  <td align="right" style="font-size:13px;color:#667781;padding-bottom:4px;">New customers</td>
                </tr>
                <tr>
                  <td style="font-size:15px;color:#111b21;font-weight:500;line-height:1.4;">
                    {html.escape(window_text)}
                  </td>
                  <td align="right" valign="middle">{count_badge}</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 8px 16px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="border-collapse:collapse;">
                <thead>
                  <tr style="background:#f0f2f5;">
                    <th align="left" style="padding:10px 16px;font-size:12px;font-weight:600;color:#54656f;text-transform:uppercase;letter-spacing:0.03em;">Joined</th>
                    <th align="left" style="padding:10px 16px;font-size:12px;font-weight:600;color:#54656f;text-transform:uppercase;letter-spacing:0.03em;">Name</th>
                    <th align="left" style="padding:10px 16px;font-size:12px;font-weight:600;color:#54656f;text-transform:uppercase;letter-spacing:0.03em;">WhatsApp ID</th>
                  </tr>
                </thead>
                <tbody>
                  {rows_html}
                </tbody>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 24px 20px;border-top:1px solid #e9edef;">
              <p style="margin:0;font-size:12px;color:#8696a0;line-height:1.5;">
                Automated daily report from the Furnisteel WhatsApp chatbot.
                Customers are anyone who started a new conversation in the last 24 hours.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return EmailContent(plain=plain, html=html_body)


def _send_email(settings: Settings, content: EmailContent) -> None:
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
    msg.set_content(content.plain)
    msg.add_alternative(content.html, subtype="html")

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
    content = _render_email(settings, customers)
    _send_email(settings, content)
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

