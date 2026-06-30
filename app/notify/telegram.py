"""Telegram delivery (python-telegram-bot).

- `send(text, run_id=...)` — fire-and-forget message from cron jobs (Bot API).
- Idempotent on `run_id` (the receiver-side dedupe key; we also keep our own send guard).
- Retries via `app/utils/retry.py` semantics (httpx under the hood).
The always-on HITL bot lives in `app/bot/hitl.py` (separate Application/poller).
"""
from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger(__name__)

_sent_run_ids: set[str] = set()


def _bot():
    from telegram import Bot  # type: ignore
    return Bot(token=settings.telegram_bot_token)


def send(text: str, *, run_id: str | None = None, parse_mode: str | None = "Markdown") -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.warning("Telegram not configured — skipping send (run_id=%s)", run_id)
        return
    if run_id and run_id in _sent_run_ids:
        log.info("Telegram already sent for run_id=%s — dedupe", run_id)
        return
    bot = _bot()
    # Telegram caps messages at 4096 chars; chunk long reports.
    for chunk in _chunks(text, 3900):
        bot.send_message(chat_id=settings.telegram_chat_id, text=chunk, parse_mode=parse_mode)
    if run_id:
        _sent_run_ids.add(run_id)


def _chunks(text: str, size: int):
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
