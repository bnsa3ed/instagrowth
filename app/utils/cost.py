"""Monthly AI-cost aggregation + throttle gate.

Spend is aggregated from `pipeline_runs.meta->cost_usd` for the current calendar month.
At 80% of `account_config.monthly_cost_cap_usd` → alert; at 100% → non-essential AI jobs
(topic ideation, drafting, repurposing) self-throttle via `is_ai_throttled()`, while data
acquisition + the anomaly radar keep running (they're cheap/essential).
"""
from __future__ import annotations

import logging

from app.db.client import get_cursor

log = logging.getLogger(__name__)

ALERT_FRACTION = 0.80


def monthly_spend_usd(ig_user_id: str | None = None) -> float:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT COALESCE(SUM((meta->>'cost_usd')::numeric), 0)::float AS total
                 FROM pipeline_runs
                WHERE date_trunc('month', started_at) = date_trunc('month', now())
                  AND meta ? 'cost_usd'""")
        return float(cur.fetchone()["total"] or 0.0)


def cap_usd(ig_user_id: str) -> float:
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT monthly_cost_cap_usd FROM account_config WHERE ig_user_id=%s",
                    (ig_user_id,))
        row = cur.fetchone()
    return float((row and row.get("monthly_cost_cap_usd")) or 20.0)


def spend_fraction(ig_user_id: str) -> float:
    cap = cap_usd(ig_user_id)
    return (monthly_spend_usd() / cap) if cap > 0 else 0.0


def is_ai_throttled(ig_user_id: str) -> bool:
    """True when monthly spend has reached the cap → skip non-essential AI jobs."""
    return spend_fraction(ig_user_id) >= 1.0
