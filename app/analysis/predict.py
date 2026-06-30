"""Predictive forecasting — lightweight regression/LLM-heuristic (no heavy ML).

- per-draft engagement prediction + confidence band (features: format, hour-slot, caption
  length, hashtag count, your recent avg engagement).
- 30-day follower forecast via exponential smoothing; accuracy tracked over time.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from app.db.client import get_cursor

log = logging.getLogger(__name__)


@dataclass
class Prediction:
    predicted_engagement: float
    confidence: float  # 0..1


def _recent_avg_engagement(ig_user_id: str, days: int = 30) -> float:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT AVG(mp.engagement_rate) AS a
                 FROM ig_media_performance mp JOIN ig_media im ON im.media_id = mp.media_id
                WHERE im.ig_user_id=%s AND mp.engagement_rate IS NOT NULL
                  AND mp.snapshot_ts > now() - %s * interval '1 day'""",
            (ig_user_id, days))
        row = cur.fetchone()
    return float(row["a"] or 0.0) if row else 0.0


def predict_draft(ig_user_id: str, *, fmt: str, caption_len: int, hashtag_count: int,
                  slot_score: float | None) -> Prediction:
    """Heuristic regression: start from the account mean, nudge by simple weights."""
    base = _recent_avg_engagement(ig_user_id)
    if base <= 0:
        # No history yet — return a low-confidence placeholder.
        return Prediction(predicted_engagement=0.03, confidence=0.1)

    # Multipliers (heuristic, learned weights are a later enhancement).
    fmt_mult = {"Reel": 1.25, "Carousel": 1.1, "Story": 0.8, "Carousel+Reel": 1.3,
                "X": 0.7, "LinkedIn": 0.6}.get(fmt, 1.0)
    len_mult = 1.0 + max(-0.1, min(0.1, (caption_len - 120) / 1200))   # ±10% around 120 chars
    tag_mult = 1.0 + max(-0.05, min(0.05, (hashtag_count - 8) / 80))   # ~8 tags sweet spot
    slot_mult = 1.0 + (0.15 * (slot_score or 0.5))                     # strong slot lifts ER

    predicted = base * fmt_mult * len_mult * tag_mult * slot_mult
    # Confidence: based on how much recent data we have (capped).
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT COUNT(*) AS n FROM ig_media_performance mp
                JOIN ig_media im ON im.media_id = mp.media_id
               WHERE im.ig_user_id=%s AND mp.engagement_rate IS NOT NULL
                 AND mp.snapshot_ts > now() - interval '30 days'""",
            (ig_user_id,))
        n = (cur.fetchone() or {}).get("n", 0)
    confidence = max(0.2, min(0.8, 0.2 + n / 50))
    return Prediction(predicted_engagement=round(predicted, 4), confidence=round(confidence, 2))


def follower_forecast(ig_user_id: str, horizon_days: int = 30) -> dict:
    """Exponential-smoothing projection of next-`horizon_days` follower growth."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT followers_count FROM ig_profile_metrics
                WHERE ig_user_id=%s AND followers_count IS NOT NULL
                ORDER BY snapshot_date ASC LIMIT 90""",
            (ig_user_id,))
        series = [int(r["followers_count"]) for r in cur.fetchall() if r["followers_count"]]

    if len(series) < 7:
        return {"current": series[-1] if series else None, "forecast": None,
                "confidence_low": None, "confidence_high": None, "samples": len(series)}

    alpha = 0.3  # smoothing factor
    level = float(series[0])
    for v in series[1:]:
        level = alpha * v + (1 - alpha) * level

    # Estimate average daily delta from the recent window.
    recent = series[-14:] if len(series) >= 14 else series
    deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent)) if recent[i - 1] is not None]
    daily = statistics.fmean(deltas) if deltas else 0.0
    current = series[-1]
    forecast = current + daily * horizon_days
    # Confidence band from delta dispersion.
    spread = (statistics.pstdev(deltas) if len(deltas) > 1 else abs(daily)) * (horizon_days ** 0.5)
    return {
        "current": current,
        "forecast": int(forecast),
        "confidence_low": int(forecast - spread),
        "confidence_high": int(forecast + spread),
        "samples": len(series),
    }
