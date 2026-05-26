"""HKT 18:00 (UTC 10:00) email digest for pending R&D proposals."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

import structlog

from rnd_agent.db import fetch_pending_proposals
from rnd_agent.settings import Settings

log = structlog.get_logger()


async def send_pending_digest(settings: Settings) -> int:
    """Email a summary when pending proposals exist.

    Returns:
        Number of pending proposals included in the digest (0 if skipped).
    """
    if not settings.smtp_host or not settings.smtp_to:
        log.info("rnd_digest_skipped_no_smtp")
        return 0

    pending = await fetch_pending_proposals(settings.pg_dsn())
    if not pending:
        log.info("rnd_digest_skipped_no_pending")
        return 0

    body = _format_digest(pending)
    subject = f"[theeyebeta] R&D proposals pending review ({len(pending)})"
    await asyncio.to_thread(
        _send_smtp,
        settings,
        subject=subject,
        body=body,
    )
    log.info("rnd_digest_sent", pending_count=len(pending))
    return len(pending)


def _format_digest(rows: list[dict[str, Any]]) -> str:
    lines = [
        "Pending R&D proposals require operator review.",
        "",
    ]
    for row in rows[:20]:
        lines.append(
            f"- {row['id']} [{row['category']}] {row['target']}: {str(row['rationale'])[:120]}..."
        )
    if len(rows) > 20:
        lines.append(f"... and {len(rows) - 20} more.")
    lines.append("")
    lines.append("Review in admin-service → Proposals.")
    return "\n".join(lines)


def _send_smtp(settings: Settings, *, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = settings.smtp_to
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
