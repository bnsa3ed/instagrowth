"""Best-time-to-post — read the day×hour heatmap and pick the top slot for a format/day.

The heatmap itself is computed nightly by pg_cron (refresh_best_time_slots). This module
is a cheap reader used by the drafter to tag each draft with its best slot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.db.client import get_cursor

log = logging.getLogger(__name__)


def top_slot(ig_user_id: str, within_days: int = 7) -> dict | None:
    """Return the highest-scoring future-ish slot {day_of_week, hour, score}.

    Prefers slots with ≥3 samples; returns None if no history yet.
    """
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT day_of_week, hour, score, avg_engagement_rate
                 FROM best_time_slots
                WHERE ig_user_id = %s AND sample_count >= 3
                ORDER BY score DESC LIMIT 1""",
            (ig_user_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return dict(row)


def slot_to_datetime(slot: dict, tz: str = "Africa/Cairo") -> datetime:
    """Convert a {day_of_week, hour} slot to the next concrete publish timestamp (UTC)."""
    import zoneinfo
    local = zoneinfo.ZoneInfo(tz)
    now = datetime.now(local)
    target_dow = int(slot["day_of_week"]) % 7
    days_ahead = (target_dow - now.weekday() + 1) % 7 or 7  # at least tomorrow
    candidate = (now + timedelta(days=days_ahead)).replace(hour=int(slot["hour"]),
                                                           minute=0, second=0, microsecond=0)
    return candidate.astimezone(timezone.utc)
