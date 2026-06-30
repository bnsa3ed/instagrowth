"""Telegram delivery (python-telegram-bot v21+ — async).

- `send(text, run_id=...)` — fire-and-forget message from cron jobs (Bot API).
- Idempotent on `run_id` (the receiver-side dedupe key + our own in-process guard).
- Markdown-resilient: falls back to plain text if Telegram rejects the formatting.
- Works from sync (cron) AND async (bot/hitl) contexts.

The always-on HITL bot lives in `app/bot/hitl.py` (separate Application/poller).
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings

log = logging.getLogger(__name__)

_sent_run_ids: set[str] = set()


def _bot():
    from telegram import Bot  # type: ignore
    return Bot(token=settings.telegram_bot_token)


def _await(coro):
    """Run an async coroutine from sync code; safe if a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # An event loop is already running (we're inside the async bot) — run in a worker thread.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def send(text: str, *, run_id: str | None = None, parse_mode: str | None = "Markdown") -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.warning("Telegram not configured — skipping send (run_id=%s)", run_id)
        return
    if run_id and run_id in _sent_run_ids:
        log.info("Telegram already sent for run_id=%s — dedupe", run_id)
        return

    async def _send_all() -> None:
        bot = _bot()
        from telegram.error import TelegramError  # type: ignore
        for chunk in _chunks(text, 3900):
            try:
                await bot.send_message(chat_id=settings.telegram_chat_id, text=chunk,
                                       parse_mode=parse_mode)
            except TelegramError as exc:
                if parse_mode:
                    # Markdown parse failure (unmatched * _ ` etc.) → retry as plain text.
                    log.warning("Telegram markdown rejected (%s); retrying plain text", exc)
                    await bot.send_message(chat_id=settings.telegram_chat_id, text=chunk)
                else:
                    raise

    _await(_send_all())
    if run_id:
        _sent_run_ids.add(run_id)


def _chunks(text: str, size: int):
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
