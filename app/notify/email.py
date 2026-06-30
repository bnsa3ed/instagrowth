"""Email delivery via SMTP (HTML + markdown). Idempotent on run_id; 3 retries with backoff."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.utils.retry import retry_call

log = logging.getLogger(__name__)

_sent_run_ids: set[str] = set()


def _send_smtp(to_addr: str, subject: str, markdown: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_addr
    msg.attach(MIMEText(markdown, "plain", "utf-8"))
    # Very small HTML wrapper around the preformatted markdown.
    msg.attach(MIMEText(f"<pre style='white-space:pre-wrap'>{markdown}</pre>", "html", "utf-8"))

    ctx = ssl.create_default_context()
    def _do() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as srv:
            srv.starttls(context=ctx)
            srv.login(settings.smtp_user, settings.smtp_password)
            srv.send_message(msg)

    retry_call(_do, retries=3)


def send_report(markdown: str, *, run_id: str | None = None, subject: str = "📊 تقرير الأسبوع") -> None:
    if not settings.smtp_host:
        log.warning("SMTP not configured — skipping email (run_id=%s)", run_id)
        return
    if run_id and run_id in _sent_run_ids:
        log.info("Email already sent for run_id=%s — dedupe", run_id)
        return
    to_addr = settings.smtp_from or settings.smtp_user
    _send_smtp(to_addr, subject, markdown)
    if run_id:
        _sent_run_ids.add(run_id)


def send_alert(text: str, *, run_id: str | None = None) -> None:
    send_report(text, run_id=run_id, subject="🚨 Instagrowth Alert")
