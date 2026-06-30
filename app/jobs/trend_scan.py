"""Trend scan — run all connectors + Grounding → idempotent upsert into trend_signals.

Mon/Wed/Fri 08:00. Dedup on signal_hash (ON CONFLICT DO NOTHING). Momentum inferred from
how fast a signal repeats across sources (re-seeing a hash bumps momentum toward 'peaked').

Run: `python -m app.jobs.trend_scan`
"""
from __future__ import annotations

import logging

from app.ai import grounding
from app.config import settings
from app.connectors import github_trending, hn, huggingface, producthunt, reddit, rss
from app.connectors.base import signal_hash
from app.db.client import get_cursor, upsert
from app.db.logging import run_context

log = logging.getLogger("trend_scan")

CONNECTORS = [hn, producthunt, github_trending, huggingface, reddit, rss]


def _run() -> int:
    ig_user_id = settings.ig_user_id
    seen: dict[str, dict] = {}

    for mod in CONNECTORS:
        try:
            items = mod.fetch(ig_user_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("connector %s failed: %s", mod.__name__, exc)
            continue
        for it in items:
            h = it.get("signal_hash") or signal_hash(it.get("url"), it.get("title", ""))
            it["signal_hash"] = h
            it.setdefault("ig_user_id", ig_user_id)
            seen[h] = it

    # Grounding (live web).
    try:
        with get_cursor(commit=False) as cur:
            cur.execute("SELECT keywords FROM account_config WHERE ig_user_id=%s", (ig_user_id,))
            row = cur.fetchone()
        keywords = (row and row.get("keywords")) or []
        for g in grounding.query(list(keywords)):
            h = signal_hash(g.get("url"), g.get("title", ""))
            g["signal_hash"] = h
            g["ig_user_id"] = ig_user_id
            seen[h] = g
    except Exception as exc:  # noqa: BLE001
        log.warning("grounding stage failed: %s", exc)

    written = 0
    with get_cursor(commit=True) as cur:
        for it in seen.values():
            row = {
                "ig_user_id": it["ig_user_id"],
                "source": it["source"],
                "title": it["title"],
                "url": it.get("url"),
                "summary": it.get("summary"),
                "signal_ts": it.get("signal_ts"),
                "momentum": it.get("momentum"),
                "signal_hash": it["signal_hash"],
                "raw_json": it.get("raw_json"),
            }
            upsert(cur, "trend_signals", row, conflict_cols=["signal_hash"], update=False)
            written += 1
    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with run_context("trend_scan") as run:
        run.add_meta(signals_seen=_run())


if __name__ == "__main__":
    main()
