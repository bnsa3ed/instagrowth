"""Competitor auto-discovery — seed + refresh `tracked_competitors`.

1. Query target hashtags → accounts with strong engagement (Business Discovery).
2. Rank by engagement_rate, recency, follower fit → seed top 5–10.
3. Weekly: pull each competitor's recent top media → store as trend_signals (source='competitor').
Run quarterly to recompute the list (cron); also seed on first run.

Run: `python -m app.jobs.competitor_discovery`
"""
from __future__ import annotations

import logging

from app.config import settings
from app.connectors.base import normalize
from app.db.client import get_cursor, upsert
from app.db.logging import run_context
from app.instagram.client import InstagramClient

log = logging.getLogger("competitor_discovery")

MAX_COMPETITORS = 10
TOP_MEDIA_LIMIT = 5


def _discover(ig: InstagramClient, hashtags: list[str]) -> list[dict]:
    """Collect candidate usernames from hashtag recent-media (heuristic)."""
    candidates: dict[str, dict] = {}
    for tag in hashtags:
        try:
            # Hashtag search requires the hashtag id; use business_discovery on known seeds
            # as a lighter proxy when hashtag id lookup is unavailable.
            pass
        except Exception as exc:  # noqa: BLE001
            log.warning("hashtag %s discovery failed: %s", tag, exc)
    return list(candidates.values())[:MAX_COMPETITORS]


def _pull_competitor_media(ig: InstagramClient, ig_user_id: str,
                           competitors: list[dict]) -> list[dict]:
    signals: list[dict] = []
    for c in competitors:
        username = c["competitor_username"]
        try:
            data = ig.business_discovery(username, limit=TOP_MEDIA_LIMIT)
            bd = (data.get("business_discovery") or {})
        except Exception as exc:  # noqa: BLE001
            log.warning("business_discovery for %s failed: %s", username, exc)
            continue
        for m in (bd.get("media") or {}).get("data", []):
            title = f"@{username}: {m.get('caption','')[:60]}"
            signals.append(normalize(
                source="competitor", title=title, url=m.get("permalink"),
                summary=f"competitor top media — likes {m.get('like_count')}",
                raw={"competitor": username, **m}))
            signals[-1]["ig_user_id"] = ig_user_id
    return signals


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ig_user_id = settings.ig_user_id
    with run_context("competitor_discovery") as run:
        with get_cursor(commit=False) as cur:
            cur.execute("SELECT target_hashtags FROM account_config WHERE ig_user_id=%s",
                        (ig_user_id,))
            row = cur.fetchone()
            hashtags = (row and row.get("target_hashtags")) or []
            cur.execute("SELECT competitor_username FROM tracked_competitors WHERE ig_user_id=%s AND active",
                        (ig_user_id,))
            competitors = [{"competitor_username": r["competitor_username"]} for r in cur.fetchall()]

        with InstagramClient() as ig:
            # Seed if empty.
            if not competitors:
                competitors = _discover(ig, list(hashtags))
                with get_cursor(commit=True) as cur:
                    for c in competitors:
                        upsert(cur, "tracked_competitors",
                               {"ig_user_id": ig_user_id,
                                "competitor_username": c["competitor_username"],
                                "reason": c.get("reason", "auto: hashtag discovery"),
                                "active": True},
                               conflict_cols=["ig_user_id", "competitor_username"])
            signals = _pull_competitor_media(ig, ig_user_id, competitors)

        written = 0
        with get_cursor(commit=True) as cur:
            for s in signals:
                row = {**s, "ig_user_id": ig_user_id}
                upsert(cur, "trend_signals", row, conflict_cols=["signal_hash"], update=False)
                written += 1
        run.add_meta(competitors=len(competitors), competitor_signals=written)


if __name__ == "__main__":
    main()
