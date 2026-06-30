"""AI-newsletter RSS connector (feedparser).

Curated feeds: Simon Willison, TLDR AI, Ben's Bites, The Rundown AI. Override via
RSS_FEEDS (newline-separated) in .env.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import feedparser

from app.connectors.base import MAX, normalize

log = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://simonwillison.net/atom/everything/",      # Simon Willison
    "https://tldr.tech/api/rss/ai",                    # TLDR AI
    "https://bensbites.beehiiv.com/feed",              # Ben's Bites
    "https://www.therundown.ai/subscribe",             # placeholder; replace with real RSS
]


def _feeds() -> list[str]:
    env = os.getenv("RSS_FEEDS", "")
    return [f.strip() for f in env.splitlines() if f.strip()] or DEFAULT_FEEDS


def fetch(ig_user_id: str, max_items: int = MAX) -> list[dict]:
    out: list[dict] = []
    per = max(1, max_items // max(1, len(_feeds())))
    for url in _feeds():
        try:
            parsed = feedparser.parse(url)
        except Exception as exc:  # noqa: BLE001
            log.warning("RSS parse failed (%s): %s", url, exc)
            continue
        for entry in parsed.entries[:per]:
            title = entry.get("title", "").strip()
            if not title:
                continue
            ts = None
            if entry.get("published_parsed"):
                ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            out.append(normalize(
                source="rss", title=title, url=entry.get("link"),
                summary=(entry.get("summary") or "")[:300] or None,
                signal_ts=ts, raw={"feed": url}))
        if len(out) >= max_items:
            break
    return out[:max_items]
