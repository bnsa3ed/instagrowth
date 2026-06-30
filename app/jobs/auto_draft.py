"""Auto-draft — turn approved/suggested topics into near-ready multi-format drafts.

For each topic (status='suggested', top by opportunity_score):
  - call Gemini with `draft-vibecoding-v1` (2 A/B variants when opportunity_score is high),
  - tag best_time + predicted_engagement + confidence,
  - rotate hashtags via hashtag_stats,
  - insert into content_drafts, set topic status='drafted'.

Run: `python -m app.jobs.auto_draft`
"""
from __future__ import annotations

import json
import logging

from app.ai.gemini import generate_structured, load_prompt
from app.analysis import best_time, hashtag_stats, predict
from app.config import settings
from app.db.client import get_cursor
from app.db.logging import PipelineRun, run_context
from app.db.models import ContentDraft

log = logging.getLogger("auto_draft")

from psycopg2.extras import Json

PROMPT_VERSION = "draft-vibecoding-v1"
PROMPT_FILE = "draft-vibecoding-v1.md"
HIGH_OPPORTUNITY = 75.0
MAX_TOPICS_PER_RUN = 3


def _topics_to_draft(ig_user_id: str) -> list[dict]:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT id, title, angle, trend_hook, format, opportunity_score,
                      draft_outline, suggested_hashtags
                 FROM topic_suggestions
                WHERE ig_user_id=%s AND status='suggested'
                ORDER BY COALESCE(opportunity_score,0) DESC LIMIT %s""",
            (ig_user_id, MAX_TOPICS_PER_RUN))
        return [dict(r) for r in cur.fetchall()]


def _few_shot(ig_user_id: str) -> list[str]:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT im.caption
                 FROM ig_media_performance mp JOIN ig_media im ON im.media_id = mp.media_id
                WHERE im.ig_user_id=%s AND im.caption IS NOT NULL
                  AND mp.engagement_rate IS NOT NULL
                ORDER BY mp.engagement_rate DESC LIMIT 5""",
            (ig_user_id,))
        return [r["caption"] for r in cur.fetchall()]


def _config(ig_user_id: str) -> dict:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT brand_voice, taboos, target_hashtags, keywords
                 FROM account_config WHERE ig_user_id=%s""",
            (ig_user_id,))
        row = cur.fetchone()
    return dict(row) if row else {}


def _build_variant(ig_user_id: str, topic: dict, cfg: dict, variant_label: str | None,
                   run: PipelineRun) -> dict | None:
    system_prompt = load_prompt(PROMPT_FILE)
    payload = json.dumps({
        "topic": topic, "account": cfg,
        "few_shot": _few_shot(ig_user_id),
    }, ensure_ascii=False, default=str)
    try:
        ai = generate_structured(system_prompt, payload, ContentDraft)
    except Exception as exc:  # noqa: BLE001
        log.error("draft generation failed for topic %s: %s", topic.get("id"), exc)
        return None
    run.add_cost(ai.cost_usd)
    run.add_meta(used_fallback=ai.used_fallback, model=ai.model)

    draft: ContentDraft = ai.data
    if variant_label:
        draft.variant_label = variant_label
    fmt = topic.get("format") or "Reel"
    cap_len = len(draft.caption or "")
    slot = best_time.top_slot(ig_user_id)
    slot_dt = best_time.slot_to_datetime(slot, settings.account_timezone) if slot else None
    pred = predict.predict_draft(
        ig_user_id, fmt=fmt, caption_len=cap_len,
        hashtag_count=len(draft.hashtags or []),
        slot_score=slot.get("score") if slot else None,
    )
    tags = hashtag_stats.suggest(ig_user_id, cfg.get("target_hashtags") or [],
                                 topic_keywords=cfg.get("keywords"))
    final_tags = tags or draft.hashtags

    row = {
        "ig_user_id": ig_user_id,
        "topic_suggestion_id": topic["id"],
        "format": fmt,
        "caption": draft.caption,
        "hook": draft.hook,
        "body_json": Json(draft.body),
        "hashtags": final_tags,
        "best_time": slot_dt,
        "predicted_engagement": pred.predicted_engagement,
        "pred_confidence": pred.confidence,
        "prompt_version": PROMPT_VERSION,
        "variant_label": draft.variant_label,
        "media_source": "manual",
        "status": "draft",
    }
    return row


def _run(run: PipelineRun) -> int:
    ig_user_id = settings.ig_user_id
    cfg = _config(ig_user_id)
    topics = _topics_to_draft(ig_user_id)
    written = 0
    with get_cursor(commit=True) as cur:
        for topic in topics:
            variants = ["A", "B"] if (topic.get("opportunity_score") or 0) >= HIGH_OPPORTUNITY else [None]
            for v in variants:
                row = _build_variant(ig_user_id, topic, cfg, v, run)
                if not row:
                    continue
                cur.execute(
                    """INSERT INTO content_drafts
                         (ig_user_id, topic_suggestion_id, format, caption, hook, body_json,
                          hashtags, best_time, predicted_engagement, pred_confidence,
                          prompt_version, variant_label, media_source, status)
                       VALUES (%(ig_user_id)s,%(topic_suggestion_id)s,%(format)s,%(caption)s,
                               %(hook)s,%(body_json)s,%(hashtags)s,%(best_time)s,
                               %(predicted_engagement)s,%(pred_confidence)s,%(prompt_version)s,
                               %(variant_label)s,%(media_source)s,%(status)s)""",
                    row,
                )
                written += 1
            # Mark topic as drafted.
            cur.execute("UPDATE topic_suggestions SET status='drafted' WHERE id=%s", (topic["id"],))
    run.add_meta(topics_drafted=len(topics), drafts_written=written)
    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ig_user_id = settings.ig_user_id
    from app.utils.cost import is_ai_throttled
    if is_ai_throttled(ig_user_id):
        log.info("monthly AI cap reached — skipping auto-draft (cost throttle)")
        return
    with run_context("auto_draft") as run:
        _run(run)


if __name__ == "__main__":
    main()
