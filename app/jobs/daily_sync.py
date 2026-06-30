"""Daily sync — profile + account insights + stories (the #1 data-loss risk).

Stories expire in 24h; this job MUST run daily. Upserts are idempotent on the natural keys.

Run: `python -m app.jobs.daily_sync`
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.db.client import get_cursor, upsert
from app.db.logging import run_context
from app.db.models import ProfileMetric, StoryRow
from app.instagram.client import InstagramClient
from app.utils import buc

log = logging.getLogger("daily_sync")


def _run() -> None:
    with InstagramClient() as ig:
        ig_user_id = ig.ig_user_id
        profile = ig.get_profile()

        # Account insights: end the window 48h ago (data-delay), max 90-day lookback.
        now = datetime.now(timezone.utc)
        until = int((now - timedelta(hours=48)).timestamp())
        since = until - 30 * 86400
        insights = ig.get_account_insights(since=since, until=until)

        stories = ig.get_stories()

    today = datetime.now(timezone.utc).date()

    # Flatten account-insights (period=day) into the latest-day values.
    acc = {m["name"]: _last_value(m) for m in insights.get("data", [])}

    profile_row = ProfileMetric(
        snapshot_date=today,
        ig_user_id=ig_user_id,
        followers_count=profile.get("followers_count"),
        follows_count=profile.get("follows_count"),
        media_count=profile.get("media_count"),
        reach=acc.get("reach"),
        total_views=acc.get("views"),
        accounts_engaged=acc.get("accounts_engaged"),
        follows_and_unfollows=acc.get("follows_and_unfollows"),
        raw_json={"profile": profile, "insights": insights},
    )

    with get_cursor(commit=True) as cur:
        upsert(cur, "ig_profile_metrics", profile_row.model_dump(exclude_none=True),
               conflict_cols=["ig_user_id", "snapshot_date"])

        for s in stories:
            ins = s.get("insights", {}) or {}
            row = StoryRow(
                story_id=s["id"],
                ig_user_id=ig_user_id,
                publish_ts=s["timestamp"],
                exits=ins.get("exits"),
                views=ins.get("views") or ins.get("impression_count"),
                reach=ins.get("reach"),
                replies=ins.get("replies"),
                taps_forward=ins.get("taps_forward"),
                taps_back=ins.get("taps_back"),
            )
            # Partitioned PK is (story_id, publish_ts).
            upsert(cur, "ig_stories", row.model_dump(exclude_none=True),
                   conflict_cols=["story_id", "publish_ts"])

    missed = _missed_story_capture(ig_user_id)
    return missed


def _last_value(metric: dict):
    vals = metric.get("values") or []
    return vals[-1].get("value") if vals else None


def _missed_story_capture(ig_user_id: str) -> bool:
    """True if no story has been captured in the last 25h (24h-expiry data-loss risk)."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT 1 FROM ig_stories
                WHERE ig_user_id = %s AND captured_ts > now() - interval '25 hours'
                LIMIT 1""",
            (ig_user_id,),
        )
        return cur.fetchone() is None


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with run_context("daily_sync") as run:
        missed = _run()
        run.api_calls_used = 3
        run.add_meta(**buc.snapshot().as_meta())
        if missed:
            run.mark_partial("no stories captured in the last 25h (24h-expiry data-loss risk)")


if __name__ == "__main__":
    main()
