"""Weekly media sync — fetch media since cursor → per-media insights → upsert.

Re-fetches the last 30 days of media performance (Meta retains media insights 2 yrs).
Maintains a cursor in pipeline_runs.meta so only *new* master rows are fetched.

Run: `python -m app.jobs.weekly_media_sync`
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.db.client import get_cursor, upsert
from app.db.logging import PipelineRun, run_context
from app.db.models import MediaPerformanceRow, MediaRow
from app.instagram.client import InstagramClient
from app.utils import buc

log = logging.getLogger("weekly_media_sync")

LOOKBACK_DAYS = 30


def _last_cursor() -> int:
    """unix ts of the last successful media sync, default LOOKBACK_DAYS ago."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT meta->>'media_since_cursor' AS c
                 FROM pipeline_runs
                WHERE job_name = 'weekly_media_sync' AND status = 'success'
                ORDER BY started_at DESC LIMIT 1"""
        )
        row = cur.fetchone()
        if row and row.get("c"):
            return int(row["c"])
    return int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp())


def _run(run: PipelineRun) -> None:
    since = _last_cursor()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    snap_ts = datetime.now(timezone.utc)

    with InstagramClient() as ig:
        media = ig.get_media_since(since_ts=since)

    api_calls = 0
    with InstagramClient() as ig_ins:  # reuse one client for all insight calls
        with get_cursor(commit=True) as cur:
            for m in media:
                media_id = m["id"]
                media_type = "REELS" if m.get("media_product_type") == "REELS" else m.get("media_type")
                publish = m.get("timestamp")

                master = MediaRow(
                    media_id=media_id,
                    ig_user_id=ig.ig_user_id,
                    media_type=media_type,
                    caption=m.get("caption"),
                    permalink=m.get("permalink"),
                    publish_date=publish,
                    last_synced_at=snap_ts,
                )
                upsert(cur, "ig_media", master.model_dump(exclude_none=True),
                       conflict_cols=["media_id"])

                ins = ig_ins.get_media_insights(media_id, media_type or "")
                api_calls += 1

                perf = MediaPerformanceRow(
                    media_id=media_id,
                    snapshot_ts=snap_ts,
                    likes_count=ins.get("likes"),
                    comments_count=ins.get("comments"),
                    reach=ins.get("reach"),
                    views=ins.get("views"),
                    saved=ins.get("saved"),
                    shares=ins.get("shares"),
                    plays=ins.get("plays"),
                )
                upsert(cur, "ig_media_performance", perf.model_dump(exclude_none=True),
                       conflict_cols=["media_id", "snapshot_ts"])

    run.api_calls_used = api_calls
    run.add_meta(media_since_cursor=now_ts, media_fetched=len(media))


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with run_context("weekly_media_sync") as run:
        _run(run)
        run.add_meta(**buc.snapshot().as_meta())


if __name__ == "__main__":
    main()
