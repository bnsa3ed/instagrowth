"""Rolling baselines — 7-day & 28-day mean ± std-dev for anomaly detection.

Default alert threshold is ≥3σ over the 28-day baseline, configurable via
`account_config.anomaly_sigma_threshold`. Covers followers, engagement_rate, reach.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from app.db.client import get_cursor

log = logging.getLogger(__name__)


@dataclass
class Baseline:
    mean: float
    stddev: float
    n: int

    def sigma_of(self, value: float) -> float:
        """How many std-devs `value` is from the mean (0 if no variance)."""
        if self.n < 2 or self.stddev == 0:
            return 0.0
        return abs(value - self.mean) / self.stddev


def _series(table_or_view: str, ig_user_id: str, value_col: str, days: int) -> list[float]:
    with get_cursor(commit=False) as cur:
        cur.execute(
            f"""SELECT {value_col} AS v
                  FROM {table_or_view}
                 WHERE ig_user_id = %s
                   AND {value_col} IS NOT NULL
                   AND snapshot_date >= (current_date - %s * interval '1 day')
                 ORDER BY snapshot_date ASC""",
            (ig_user_id, days),
        )
        return [float(r["v"]) for r in cur.fetchall() if r["v"] is not None]


def _baseline(values: list[float]) -> Baseline:
    n = len(values)
    if n == 0:
        return Baseline(0.0, 0.0, 0)
    mean = statistics.fmean(values)
    stddev = statistics.pstdev(values) if n > 1 else 0.0
    return Baseline(mean, stddev, n)


def followers(ig_user_id: str, days: int = 28) -> Baseline:
    return _baseline(_series("v_follower_series", ig_user_id, "followers_count", days))


def reach(ig_user_id: str, days: int = 28) -> Baseline:
    return _baseline(_series("v_reach_series", ig_user_id, "reach", days))


def engagement(ig_user_id: str, days: int = 28) -> Baseline:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT er
                 FROM v_engagement_series
                WHERE ig_user_id = %s AND er IS NOT NULL
                  AND d >= (current_date - %s * interval '1 day')
                ORDER BY d ASC""",
            (ig_user_id, days),
        )
        vals = [float(r["er"]) for r in cur.fetchall()]
    return _baseline(vals)


def threshold(ig_user_id: str) -> float:
    """Configured σ threshold for this account (default 3.0)."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT anomaly_sigma_threshold FROM account_config WHERE ig_user_id=%s",
            (ig_user_id,))
        row = cur.fetchone()
    return float((row and row.get("anomaly_sigma_threshold")) or 3.0)
