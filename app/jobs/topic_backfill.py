"""Topic backfill — set measured_engagement_rate on topics published ≥14 days ago.

Closes the learning loop (Phase 8.6): compares each published topic's real engagement to
the account average so winning topics become few-shot examples in future prompts.

Run: `python -m app.jobs.topic_backfill`
"""
from __future__ import annotations

import logging

from app.db.client import get_cursor
from app.db.logging import run_context

log = logging.getLogger("topic_backfill")


def _run() -> int:
    updated = 0
    with get_cursor(commit=True) as cur:
        # Join topics → published media → that media's latest engagement_rate.
        cur.execute(
            """UPDATE topic_suggestions ts
                  SET measured_engagement_rate = sub.engagement_rate,
                      status = 'measured'
                 FROM (
                   SELECT t.id AS topic_id, mp.engagement_rate
                     FROM topic_suggestions t
                     JOIN ig_media im ON im.media_id = t.published_media_id
                     JOIN LATERAL (
                       SELECT engagement_rate FROM ig_media_performance p
                        WHERE p.media_id = im.media_id
                        ORDER BY snapshot_ts DESC LIMIT 1
                     ) mp ON true
                    WHERE t.status = 'published'
                      AND t.published_media_id IS NOT NULL
                      AND im.publish_date < now() - interval '14 days'
                      AND t.measured_engagement_rate IS NULL
                 ) sub
                WHERE ts.id = sub.topic_id""")
        updated = cur.rowcount
    return updated


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with run_context("topic_backfill") as run:
        run.add_meta(topics_measured=_run())


if __name__ == "__main__":
    main()
