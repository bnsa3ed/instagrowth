"""Weekly digest — followers Δ, avg engagement, posts published, cost spent, forecast accuracy.

Sundays 07:00 (after the weekly report). A compact summary distinct from the full strategy report.

Run: `python -m app.jobs.weekly_digest`
"""
from __future__ import annotations

import logging

from app.analysis import predict
from app.config import settings
from app.db.client import get_cursor
from app.db.logging import run_context
from app.utils import cost

log = logging.getLogger("weekly_digest")


def _summary(ig_user_id: str) -> dict:
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM weekly_summary WHERE ig_user_id=%s LIMIT 1", (ig_user_id,))
        summary = dict(cur.fetchone() or {})
        cur.execute(
            """SELECT COUNT(*) AS n FROM ig_media
                WHERE ig_user_id=%s AND publish_date > now() - interval '7 days'""",
            (ig_user_id,))
        posts = (cur.fetchone() or {}).get("n", 0)
    fc = predict.follower_forecast(ig_user_id)
    return {"summary": summary, "posts_published": posts,
            "monthly_spend_usd": round(cost.monthly_spend_usd(), 2),
            "cap_usd": cost.cap_usd(ig_user_id), "forecast": fc}


def _render(s: dict) -> str:
    ws = s["summary"]
    fdelta = ws.get("followers_delta")
    er = ws.get("avg_engagement_rate") or 0
    fc = s["forecast"]
    lines = [
        "📋 ملخص الأسبوع (Weekly Digest)",
        f"• التغير في المتابعين: {fdelta if fdelta is not None else '—'}",
        f"• متوسط التفاعل: {float(er) * 100 if er else 0:.2f}%",
        f"• بوستات نُشرت: {s['posts_published']}",
        f"• الإنفاق على AI هذا الشهر: {s['monthly_spend_usd']}$ / {s['cap_usd']}$",
    ]
    if fc.get("forecast") is not None:
        lines.append(f"• توقّع المتابعين بعد 30 يوم: {fc['forecast']} "
                     f"(نطاق {fc['confidence_low']}–{fc['confidence_high']})")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ig_user_id = settings.ig_user_id
    with run_context("weekly_digest") as run:
        s = _summary(ig_user_id)
        run.add_meta(posts_published=s["posts_published"],
                     monthly_spend_usd=s["monthly_spend_usd"],
                     forecast=s["forecast"].get("forecast"))
        try:
            from app.notify import telegram
            telegram.send(_render(s), run_id="weekly-digest")
        except Exception as exc:  # noqa: BLE001
            log.error("digest delivery failed: %s", exc)


if __name__ == "__main__":
    main()
