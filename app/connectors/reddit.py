"""Reddit connector — top AI/coding posts via PRAW (free tier; configure env in .env).

Subreddits: LocalLLaMA, ChatGPTCoding, SideProject, SaaS. Falls back gracefully if PRAW
isn't configured (REDDIT_CLIENT_ID / REDDIT_SECRET / REDDIT_USER_AGENT).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.connectors.base import MAX, normalize

log = logging.getLogger(__name__)

SUBREDDITS = ("LocalLLaMA", "ChatGPTCoding", "SideProject", "SaaS")


def fetch(ig_user_id: str, max_items: int = MAX) -> list[dict]:
    if not (os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_SECRET")):
        log.info("Reddit creds not set — skipping Reddit")
        return []
    try:
        import praw  # type: ignore
    except ImportError:
        log.warning("praw not installed — skipping Reddit")
        return []

    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_SECRET"],
        user_agent=os.getenv("REDDIT_USER_AGENT", "instagrowth/0.1"),
    )
    reddit.read_only = True

    out: list[dict] = []
    per = max(1, max_items // len(SUBREDDITS))
    for sub_name in SUBREDDITS:
        try:
            for sub in reddit.subreddit(sub_name).top(time_filter="week", limit=per):
                if not sub.title:
                    continue
                out.append(normalize(
                    source="reddit", title=sub.title,
                    url=sub.url if not sub.is_self else f"https://reddit.com{sub.permalink}",
                    summary=sub.selftext[:300] if sub.selftext else None,
                    signal_ts=datetime.fromtimestamp(sub.created_utc, tz=timezone.utc),
                    raw={"subreddit": sub_name, "score": sub.score}))
        except Exception as exc:  # noqa: BLE001
            log.warning("Reddit r/%s failed: %s", sub_name, exc)
    return out[:max_items]
