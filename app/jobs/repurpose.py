"""Repurpose — one topic → Reel/Carousel/Story/X/LinkedIn text variants.

Variants are stored in content_drafts and linked by `parent_repurpose_id` (the first variant
is the parent; the rest reference it). No auto cross-posting — drafts are for manual copy/paste.

Run: `python -m app.jobs.repurpose`
"""
from __future__ import annotations

import json
import logging

from app.ai.gemini import generate_structured, load_prompt
from app.config import settings
from app.db.client import get_cursor
from app.db.logging import PipelineRun, run_context
from app.db.models import ContentDraft

log = logging.getLogger("repurpose")

from psycopg2.extras import Json

PROMPT_VERSION = "repurpose-vibecoding-v1"
PROMPT_FILE = "repurpose-vibecoding-v1.md"
FORMATS = ["Reel", "Carousel", "Story", "X", "LinkedIn"]


def _topics(ig_user_id: str) -> list[dict]:
    """Pick recently-drafted topics whose repurpose set is missing."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT ts.id, ts.title, ts.angle, ts.trend_hook, ts.format AS base_format,
                      ts.draft_outline, ts.suggested_hashtags
                 FROM topic_suggestions ts
                WHERE ts.ig_user_id=%s AND ts.status='drafted'
                  AND NOT EXISTS (
                    SELECT 1 FROM content_drafts cd
                     WHERE cd.topic_suggestion_id = ts.id
                       AND cd.parent_repurpose_id IS NOT NULL)
                ORDER BY ts.suggested_at DESC LIMIT 3""",
            (ig_user_id,))
        return [dict(r) for r in cur.fetchall()]


def _config(ig_user_id: str) -> dict:
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT brand_voice, taboos, target_hashtags FROM account_config WHERE ig_user_id=%s",
            (ig_user_id,))
        row = cur.fetchone()
    return dict(row) if row else {}


def _build_one(topic: dict, cfg: dict, fmt: str, run: PipelineRun) -> ContentDraft | None:
    system_prompt = load_prompt(PROMPT_FILE)
    payload = json.dumps({"topic": {**topic, "format": fmt}, "account": cfg},
                         ensure_ascii=False, default=str)
    try:
        ai = generate_structured(system_prompt, payload, ContentDraft)
    except Exception as exc:  # noqa: BLE001
        log.error("repurpose %s failed: %s", fmt, exc)
        return None
    run.add_cost(ai.cost_usd)
    return ai.data


def _run(run: PipelineRun) -> int:
    ig_user_id = settings.ig_user_id
    cfg = _config(ig_user_id)
    written = 0
    with get_cursor(commit=True) as cur:
        for topic in _topics(ig_user_id):
            parent_id = None
            for fmt in FORMATS:
                draft = _build_one(topic, cfg, fmt, run)
                if not draft:
                    continue
                cur.execute(
                    """INSERT INTO content_drafts
                         (ig_user_id, topic_suggestion_id, parent_repurpose_id, format, caption,
                          hook, body_json, hashtags, prompt_version, media_source, status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual','draft')
                       RETURNING id""",
                    (ig_user_id, topic["id"], parent_id, fmt, draft.caption, draft.hook,
                     Json(draft.body), draft.hashtags, PROMPT_VERSION),
                )
                new_id = cur.fetchone()["id"]
                if parent_id is None:
                    parent_id = new_id
                written += 1
    run.add_meta(repurpose_variants=written)
    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ig_user_id = settings.ig_user_id
    from app.utils.cost import is_ai_throttled
    if is_ai_throttled(ig_user_id):
        log.info("monthly AI cap reached — skipping repurpose (cost throttle)")
        return
    with run_context("repurpose") as run:
        _run(run)


if __name__ == "__main__":
    main()
