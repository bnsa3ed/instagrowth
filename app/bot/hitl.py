"""Human-in-the-loop (HITL) Telegram bot — mandatory Approve/Edit/Skip gate for publishing.

This is the always-on `bot` Docker service. It:
  - renders an inline Approve/Edit/Skip keyboard when `request_approval(job_id)` is called
    (from app/jobs/auto_publish.py via the cron service — here it runs as the long-lived
    bot; cross-process delivery is best done via a shared DB flag + this bot polling,
    or a Telegram message the bot itself sends).
  - on Approve  → create the IG container and mark publish_jobs.status='created'.
  - on Edit     → mark draft status='draft' (owner edits then re-approves).
  - on Skip     → mark publish_jobs.status='failed' (skipped) + draft 'skipped'.

Callback data is `hitl:<action>:<publish_job_id>` so the bot stays stateless.
Run: `python -m app.bot.hitl`
"""
from __future__ import annotations

import logging

from app.config import settings
from app.db.client import get_cursor
from app.instagram.client import InstagramClient

log = logging.getLogger("hitl")

APPROVE, EDIT, SKIP = "approve", "edit", "skip"


def _keyboard(job_id: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"hitl:{APPROVE}:{job_id}"),
        InlineKeyboardButton("✏️ Edit", callback_data=f"hitl:{EDIT}:{job_id}"),
        InlineKeyboardButton("⏭️ Skip", callback_data=f"hitl:{SKIP}:{job_id}"),
    ]])


def request_approval(job_id: str) -> None:
    """Fire-and-forget approval prompt to the owner. Called when a publish job is queued."""
    from app.notify.telegram import _bot
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT cd.caption, cd.format, cd.best_time, cd.media_url
                 FROM publish_jobs pj JOIN content_drafts cd ON cd.id = pj.content_draft_id
                WHERE pj.id=%s""", (job_id,))
        j = cur.fetchone()
    if not j:
        return
    text = (f"🔔 محتاج موافقة قبل النشر\nالفورمات: {j['format']}\n"
            f"الموعد: {j['best_time']}\n\n{j['caption'] or ''}"[:1000])
    _bot().send_message(chat_id=settings.telegram_chat_id, text=text,
                        reply_markup=_keyboard(job_id))


def _on_approve(job_id: str) -> None:
    """Create the IG container now; the cron auto_publish publishes it at scheduled time."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT cd.format, cd.caption, cd.media_url
                 FROM publish_jobs pj JOIN content_drafts cd ON cd.id = pj.content_draft_id
                WHERE pj.id=%s""", (job_id,))
        j = cur.fetchone()
    if not j:
        return
    with InstagramClient() as ig:
        if (j["format"] or "").upper() == "CAROUSEL_ALBUM":
            # Carousel: build item containers then the parent (item URLs would be in body_json).
            container = ig.create_container("CAROUSEL_ALBUM", j["media_url"], j["caption"] or "",
                                            children=[j["media_url"]])
        elif (j["format"] or "").upper() in ("REELS", "REEL", "VIDEO"):
            container = ig.create_container("REELS", j["media_url"], j["caption"] or "")
        else:
            container = ig.create_container("IMAGE", j["media_url"], j["caption"] or "")
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE publish_jobs SET container_id=%s, status='created' WHERE id=%s",
            (container, job_id))


def _on_edit(job_id: str) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE publish_jobs SET status='failed', error='edit requested'
                WHERE id=%s""", (job_id,))
        cur.execute(
            """UPDATE content_drafts SET status='draft'
                WHERE id=(SELECT content_draft_id FROM publish_jobs WHERE id=%s)""", (job_id,))


def _on_skip(job_id: str) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE publish_jobs SET status='failed', error='skipped' WHERE id=%s", (job_id,))
        cur.execute(
            """UPDATE content_drafts SET status='skipped'
                WHERE id=(SELECT content_draft_id FROM publish_jobs WHERE id=%s)""", (job_id,))


def _build_app():
    from telegram import Update
    from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                              ContextTypes)

    app = Application.builder().token(settings.telegram_bot_token).build()

    async def _start(update: "Update", _: "ContextTypes.DEFAULT_TYPE") -> None:
        await update.message.reply_text("Instagrowth HITL bot جاهز ✅")

    async def _callback(update: "Update", _: "ContextTypes.DEFAULT_TYPE") -> None:
        q = update.callback_query
        await q.answer()
        _, action, job_id = (q.data or "").split(":") + ["", ""]
        try:
            if action == APPROVE:
                _on_approve(job_id)
                reply = "تمت الموافقة ✅ — هيتنشر في موعده."
            elif action == EDIT:
                _on_edit(job_id)
                reply = "تم التحويل للمسودة للتعديل ✏️"
            elif action == SKIP:
                _on_skip(job_id)
                reply = "تم التخطي ⏭️"
            else:
                reply = "أمر غير معروف."
        except Exception as exc:  # noqa: BLE001
            log.exception("HITL callback failed")
            reply = f"حصل خطأ: {exc}"
        await q.edit_message_text(reply)

    app.add_handler(CommandHandler("start", _start))
    app.add_handler(CallbackQueryHandler(_callback, pattern=r"^hitl:"))
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set — cannot start HITL bot")
    _build_app().run_polling()


if __name__ == "__main__":
    main()
