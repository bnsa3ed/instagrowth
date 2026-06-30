"""Email delivery via SMTP — polished RTL Arabic HTML + plain-text fallback.

Renders the markdown report to HTML inside a branded, responsive, right-to-left email
template. Idempotent on run_id; 3 retries with backoff.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from app.config import settings
from app.utils.retry import retry_call

log = logging.getLogger(__name__)

_sent_run_ids: set[str] = set()


def _markdown_to_html(md: str) -> str:
    import markdown  # type: ignore
    return markdown.markdown(md, extensions=["extra", "sane_lists", "nl2br"])


_CSS = """
h1,h2,h3,h4{color:#4a3aff;line-height:1.45;margin:22px 0 8px}
h2{font-size:19px;border-bottom:2px solid #eee;padding-bottom:6px}
h3{font-size:16px}
p{margin:0 0 12px}
ul,ol{margin:0 0 12px;padding-right:22px}
li{margin:0 0 6px}
strong{color:#14162b}
blockquote{border-right:4px solid #4a3aff;margin:12px 0;padding:8px 16px;background:#faf9ff;color:#555;border-radius:4px}
code{background:#f1f1f4;padding:2px 5px;border-radius:4px;font-size:13px;font-family:Menlo,Consolas,monospace}
a{color:#4a3aff}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:14px}
th,td{border:1px solid #eee;padding:8px 10px;text-align:right}
th{background:#faf9ff}
"""


def _wrap_html(title: str, body_html: str, banner: str = "#4a3aff") -> str:
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only"><title>{escape(title)}</title>
<style>{_CSS}</style></head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:'Segoe UI',Tahoma,'Helvetica Neue',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:28px 12px;">
    <tr><td align="center">
      <table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 18px rgba(20,22,43,0.08);">
        <tr><td style="background:linear-gradient(135deg,{banner},#7b2ff7);padding:26px 34px;">
          <h1 style="margin:0;color:#fff;font-size:23px;font-weight:800;letter-spacing:.2px;">📊 {escape(title)}</h1>
          <p style="margin:8px 0 0;color:#e9e6ff;font-size:13px;">استراتيجية النمو · العامية المصرية · Instagrowth</p>
        </td></tr>
        <tr><td style="padding:30px 34px;color:#1f2330;font-size:15px;line-height:1.95;">{body_html}</td></tr>
        <tr><td style="padding:16px 34px;background:#faf9ff;color:#8a8fa3;font-size:12px;border-top:1px solid #eee;">
          أُنشئ تلقائياً بواسطة Instagrowth — لا ترد على هذه الرسالة.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _send_smtp(to_addr: str, subject: str, markdown: str, title: str, banner: str) -> None:
    body_html = _markdown_to_html(markdown)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_addr
    msg.attach(MIMEText(markdown, "plain", "utf-8"))
    msg.attach(MIMEText(_wrap_html(title, body_html, banner), "html", "utf-8"))

    ctx = ssl.create_default_context()

    def _do() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as srv:
            srv.starttls(context=ctx)
            srv.login(settings.smtp_user, settings.smtp_password)
            srv.send_message(msg)

    retry_call(_do, retries=3)


def send_report(markdown: str, *, run_id: str | None = None,
                subject: str = "📊 تقرير Instagrowth الأسبوعي",
                title: str = "تقرير الأسبوع", banner: str = "#4a3aff") -> None:
    if not settings.smtp_host:
        log.warning("SMTP not configured — skipping email (run_id=%s)", run_id)
        return
    if run_id and run_id in _sent_run_ids:
        log.info("Email already sent for run_id=%s — dedupe", run_id)
        return
    to_addr = settings.smtp_from or settings.smtp_user
    _send_smtp(to_addr, subject, markdown, title, banner)
    if run_id:
        _sent_run_ids.add(run_id)


def send_alert(text: str, *, run_id: str | None = None) -> None:
    send_report(text, run_id=run_id, subject="🚨 Instagrowth Alert",
                title="تنبيه فوري", banner="#e53935")
