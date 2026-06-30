"""Hacker News connector — top AI/dev stories via the Algolia search API (free)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.connectors.base import MAX, get_json, normalize

log = logging.getLogger(__name__)

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
AI_TAGS = (
    "AI", "LLM", "GPT", "Claude", "Gemini", "Copilot", "vibecoding", "agent",
    "machine learning", "transformer",
)


def fetch(ig_user_id: str, max_items: int = MAX) -> list[dict]:
    out: list[dict] = []
    for tag in AI_TAGS:
        if len(out) >= max_items:
            break
        try:
            data = get_json(SEARCH_URL,
                            tags="story", query=tag,
                            hitsPerPage=min(20, max_items - len(out)))
        except Exception as exc:  # noqa: BLE001
            log.warning("HN fetch failed (%s): %s", tag, exc)
            continue
        for hit in data.get("hits", []):
            title = hit.get("title") or hit.get("story_title") or ""
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if not title:
                continue
            ts = datetime.fromtimestamp(hit.get("created_at_i", 0) or 0, tz=timezone.utc)
            out.append(normalize(source="hn", title=title, url=url,
                                 summary=hit.get("story_text"),
                                 signal_ts=ts, raw=hit))
    return out[:max_items]
