"""Anomaly radar job — runs after daily sync; writes `anomalies` + instant Telegram alerts.

Also alerts on a missed-story-capture data-loss condition (no new stories in 25h).

Run: `python -m app.jobs.anomaly_detect`
"""
from __future__ import annotations

import logging

from app.analysis import anomalies
from app.config import settings
from app.db.client import get_cursor
from app.db.logging import run_context

log = logging.getLogger("anomaly_detect")


def _persist(items: list) -> int:
    """Insert anomaly rows (each detection is a distinct event — plain INSERT)."""
    n = 0
    with get_cursor(commit=True) as cur:
        for a in items:
            cur.execute(
                """INSERT INTO anomalies
                     (ig_user_id, metric, direction, severity, expected, actual,
                      attributed_media_id, notified)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE)""",
                (a.ig_user_id, a.metric, a.direction, a.severity, a.expected,
                 a.actual, a.attributed_media_id),
            )
            n += 1
    return n


def _alert_text(items: list, missed_stories: bool) -> str:
    lines = ["🚨 تنبيه فوري (Anomaly Radar)"]
    for a in items:
        arrow = "⬆️" if a.direction == "spike" else "⬇️"
        att = f" (بوست: {a.attributed_media_id})" if a.attributed_media_id else ""
        lines.append(f"{arrow} {a.metric}: {a.actual:g} مقابل المتوقع {a.expected:g} ({a.severity:g}σ){att}")
    if missed_stories:
        lines.append("⚠️ مفيش ستوريز اتسجلت من 25 ساعة — خطر فقد بيانات (الستوريز بتنتهي خلال 24 ساعة)!")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ig_user_id = settings.ig_user_id
    with run_context("anomaly_detect") as run:
        items = anomalies.detect(ig_user_id)
        missed = anomalies.missed_story_capture(ig_user_id)
        if items:
            _persist(items)
        if items or missed:
            from app.notify import telegram
            try:
                telegram.send(_alert_text(items, missed), run_id=f"anomaly-{run.run_id}")
            except Exception as exc:  # noqa: BLE001
                log.error("anomaly alert delivery failed: %s", exc)
        run.add_meta(anomalies=len(items), missed_story_capture=missed)


if __name__ == "__main__":
    main()
