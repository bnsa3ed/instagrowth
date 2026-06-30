"""Anomaly detection logic — compare today's metrics to baselines, build Anomaly rows.

Also flags a missed-story-capture data-loss condition (no new stories in 25h).
Attribution: when a post-level engagement anomaly occurs, attach the attributed_media_id.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.analysis import baselines
from app.db.client import get_cursor
from app.db.models import Anomaly

log = logging.getLogger(__name__)


def _latest(ig_user_id: str, col: str) -> Optional[float]:
    with get_cursor(commit=False) as cur:
        cur.execute(
            f"""SELECT {col} AS v FROM ig_profile_metrics
                 WHERE ig_user_id=%s AND {col} IS NOT NULL
                 ORDER BY snapshot_date DESC LIMIT 1""",
            (ig_user_id,),
        )
        row = cur.fetchone()
    return float(row["v"]) if row and row["v"] is not None else None


def _attribute_post(ig_user_id: str) -> Optional[str]:
    """If engagement spiked, attribute to the most-recent high-engagement post."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT im.media_id
                 FROM ig_media_performance mp JOIN ig_media im ON im.media_id = mp.media_id
                WHERE im.ig_user_id = %s AND mp.snapshot_ts > now() - interval '48 hours'
                ORDER BY COALESCE(mp.engagement_rate, 0) DESC LIMIT 1""",
            (ig_user_id,),
        )
        row = cur.fetchone()
    return row["media_id"] if row else None


def detect(ig_user_id: str) -> list[Anomaly]:
    """Return anomalies exceeding the account's σ threshold for the latest snapshot."""
    sigma_thr = baselines.threshold(ig_user_id)
    found: list[Anomaly] = []

    checks = [
        ("followers", baselines.followers(ig_user_id), _latest(ig_user_id, "followers_count")),
        ("reach", baselines.reach(ig_user_id), _latest(ig_user_id, "reach")),
    ]
    # engagement uses a different reader
    eng_base = baselines.engagement(ig_user_id)
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT AVG(er) AS v FROM v_engagement_series
                WHERE ig_user_id=%s AND d = (SELECT MAX(d) FROM v_engagement_series WHERE ig_user_id=%s)""",
            (ig_user_id, ig_user_id))
        row = cur.fetchone()
    eng_actual = float(row["v"]) if row and row["v"] is not None else None
    checks.append(("engagement_rate", eng_base, eng_actual))

    for metric, base, actual in checks:
        if actual is None or base.n < 7:
            continue
        sigma = base.sigma_of(actual)
        if sigma >= sigma_thr:
            direction = "spike" if actual > base.mean else "drop"
            attributed = _attribute_post(ig_user_id) if metric == "engagement_rate" else None
            found.append(Anomaly(
                ig_user_id=ig_user_id, metric=metric, direction=direction,
                severity=round(sigma, 2), expected=round(base.mean, 4),
                actual=round(actual, 4), attributed_media_id=attributed,
            ))
    return found


def missed_story_capture(ig_user_id: str) -> bool:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT 1 FROM ig_stories
                WHERE ig_user_id=%s AND captured_ts > now() - interval '25 hours' LIMIT 1""",
            (ig_user_id,),
        )
        return cur.fetchone() is None
