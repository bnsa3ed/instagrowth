"""Topic ideation — trend_signals + weekly_summary + competitor saturation → topic_suggestions.

Runs on scan days. Reads the versioned `topics-vibecoding-v1` prompt, calls Gemini with
structured output (`TopicIdeation`), and persists validated topics. Off-niche trends are
rejected by prompt rule; relevance is double-checked against account_config before insert.

Run: `python -m app.jobs.topic_ideation`
"""
from __future__ import annotations

import json
import logging

from app.ai.gemini import generate_structured, load_prompt
from app.config import settings
from app.db.client import get_cursor, upsert
from app.db.logging import PipelineRun, run_context
from app.db.models import TopicIdeation

log = logging.getLogger("topic_ideation")

PROMPT_VERSION = "topics-vibecoding-v1"
PROMPT_FILE = "topics-vibecoding-v1.md"


def _load_inputs(ig_user_id: str) -> dict:
    with get_cursor(commit=False) as cur:
        cur.execute("""SELECT niche, subtopics, keywords, target_hashtags, brand_voice, taboos
                         FROM account_config WHERE ig_user_id=%s""", (ig_user_id,))
        cfg = dict(cur.fetchone() or {})
        cur.execute("""SELECT source, title, url, summary, signal_ts, momentum
                         FROM trend_signals
                        WHERE ig_user_id=%s AND signal_ts > now() - interval '7 days'
                        ORDER BY signal_ts DESC LIMIT 40""", (ig_user_id,))
        signals = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM weekly_summary WHERE ig_user_id=%s LIMIT 1", (ig_user_id,))
        summary = dict(cur.fetchone() or {})
        cur.execute("""SELECT title, url FROM trend_signals
                        WHERE ig_user_id=%s AND source='competitor'
                        ORDER BY signal_ts DESC LIMIT 10""", (ig_user_id,))
        competitors = [dict(r) for r in cur.fetchall()]
    return {"account": cfg, "trend_signals": signals,
            "weekly_summary": summary, "competitor_signals": competitors}


def _relevance_ok(cfg: dict, title: str) -> bool:
    """Cheap post-filter: reject obvious off-niche suggestions (prompt does the heavy lifting)."""
    block = " ".join(cfg.get("offtopic_blocklist") or []).lower()
    return not any(b and b in title.lower() for b in [block] if b)


def _run(run: PipelineRun) -> int:
    ig_user_id = settings.ig_user_id
    inputs = _load_inputs(ig_user_id)
    if not inputs["account"]:
        log.warning("no account_config row for %s — skipping ideation", ig_user_id)
        return 0

    system_prompt = load_prompt(PROMPT_FILE)
    ai = generate_structured(system_prompt,
                             json.dumps(inputs, ensure_ascii=False, default=str),
                             TopicIdeation)

    inserted = 0
    with get_cursor(commit=True) as cur:
        for t in ai.data.topics:
            if not _relevance_ok(inputs["account"], t.title):
                continue
            upsert(cur, "topic_suggestions", {
                "ig_user_id": ig_user_id,
                "title": t.title,
                "angle": t.angle,
                "trend_hook": t.trend_hook,
                "format": t.format,
                "niche_fit": t.niche_fit,
                "opportunity_score": t.opportunity_score,
                "suggested_hashtags": t.suggested_hashtags,
                "draft_outline": t.draft_outline,
                "status": "suggested",
                "prompt_version": PROMPT_VERSION,
            }, conflict_cols=["ig_user_id", "title"], update=False)
            inserted += 1

    run.add_cost(ai.cost_usd)
    run.add_meta(model=ai.model, topics_inserted=inserted, used_fallback=ai.used_fallback)

    # Deliver top 3–5 to Telegram (distinct from the Sunday report).
    if inserted:
        top = ai.data.topics[:5]
        body = "\n\n".join(f"• *{t.title}* ({t.format}, فرصة {t.opportunity_score:.0f})\n{t.why_now}"
                           for t in top)
        try:
            from app.notify import telegram
            telegram.send(f"💡 أفكار محتوى الأسبوع:\n\n{body}", run_id=f"topics-{PROMPT_VERSION}")
        except Exception as exc:  # noqa: BLE001
            log.warning("topic delivery failed: %s", exc)
    return inserted


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ig_user_id = settings.ig_user_id
    from app.utils.cost import is_ai_throttled
    if is_ai_throttled(ig_user_id):
        log.info("monthly AI cap reached — skipping topic ideation (cost throttle)")
        return
    with run_context("topic_ideation") as run:
        _run(run)


if __name__ == "__main__":
    main()
