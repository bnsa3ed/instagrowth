"""Weekly report — orchestrate media sync → Gemini structured report → archive + deliver.

Reads from the `weekly_summary` view + top media; generates the Egyptian Arabic strategy
report; runs the engagement-rate self-check (±10%); archives to `ai_reports` with prompt
version + cost; delivers via Telegram/email (idempotent on run_id).

Run: `python -m app.jobs.weekly_report`
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.ai.gemini import AIResult, generate_structured, load_prompt
from app.config import settings
from app.db.client import get_cursor
from app.db.logging import PipelineRun, run_context
from app.db.models import WeeklyReport
from app.jobs.weekly_media_sync import _run as run_media_sync
from app.notify import email as notify_email
from app.notify import telegram as notify_telegram

log = logging.getLogger("weekly_report")

PROMPT_VERSION = "egyptian-strategy-v1"
PROMPT_FILE = "egyptian-strategy-v1.md"
SELF_CHECK_TOL = 0.10  # ±10% on engagement_rate_avg


def _load_inputs(ig_user_id: str) -> tuple[dict, float]:
    # Refresh the weekly_summary rollup so avg_engagement_rate reflects the just-synced media.
    try:
        with get_cursor(commit=True) as cur:
            cur.execute("REFRESH MATERIALIZED VIEW weekly_summary")
    except Exception as exc:  # noqa: BLE001
        log.warning("weekly_summary refresh failed (continuing with stale view): %s", exc)

    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT ig_user_id, niche, brand_voice, taboos
                 FROM account_config WHERE ig_user_id = %s""", (ig_user_id,))
        cfg = cur.fetchone() or {}

        cur.execute("SELECT * FROM weekly_summary WHERE ig_user_id = %s LIMIT 1", (ig_user_id,))
        summary = cur.fetchone() or {}

        cur.execute(
            """SELECT im.media_id, im.caption, im.media_type, mp.reach, mp.views, mp.engagement_rate
                 FROM ig_media_performance mp
                 JOIN ig_media im ON im.media_id = mp.media_id
                WHERE im.ig_user_id = %s AND mp.snapshot_ts > now() - interval '7 days'
                ORDER BY COALESCE(mp.engagement_rate, 0) DESC LIMIT 5""", (ig_user_id,))
        top_media = [dict(r) for r in cur.fetchall()]

    db_eng = float(summary.get("avg_engagement_rate") or 0)
    inputs = {
        "account": {k: cfg.get(k) for k in ("niche", "brand_voice", "taboos")},
        "weekly_summary": {k: (dict(v) if hasattr(v, "items") else v)
                            for k, v in dict(summary).items()},
        "top_media": top_media,
        "db_engagement_rate_avg": db_eng,
    }
    return inputs, db_eng


def _write_report(ig_user_id: str, result: AIResult, period_start, period_end, summary_txt: str) -> str:
    run_id_val = None
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO ai_reports
                 (ig_user_id, period_start, period_end, model, prompt_version,
                  input_tokens, output_tokens, cost_usd, summary, report_markdown, report_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (ig_user_id, period_start, period_end, result.model, PROMPT_VERSION,
             result.input_tokens, result.output_tokens, result.cost_usd, summary_txt,
             result.data.full_report_markdown,
             json.dumps(result.data.model_dump(), ensure_ascii=False, default=str)),
        )
        run_id_val = str(cur.fetchone()["id"])
    return run_id_val


def _run(run: PipelineRun) -> None:
    ig_user_id = settings.ig_user_id
    inputs, db_eng = _load_inputs(ig_user_id)

    system_prompt = load_prompt(PROMPT_FILE)
    ai = generate_structured(system_prompt, json.dumps(inputs, ensure_ascii=False, default=str),
                             WeeklyReport)

    # Engagement-rate self-check (±10% of DB value).
    echoed = ai.data.engagement_rate_avg
    drift = None
    if db_eng > 0:
        rel = abs(echoed - db_eng) / db_eng
        if rel > SELF_CHECK_TOL:
            drift = f"engagement_rate drift {rel:.0%} (echoed {echoed:.4f} vs db {db_eng:.4f})"
            log.warning(drift)

    now = datetime.now(timezone.utc).date()
    report_id = _write_report(ig_user_id, ai, now - timedelta(days=7), now, ai.data.headline)

    run.add_cost(ai.cost_usd)
    run.add_meta(model=ai.model, used_fallback=ai.used_fallback,
                 report_id=report_id, engagement_self_check=drift or "ok")
    if drift:
        run.mark_partial(drift)

    # Deliver (idempotent on report_id). Non-fatal if delivery fails — report is archived.
    body = f"{ai.data.full_report_markdown}\n\n_(id: {report_id})_"
    for deliver in (notify_telegram.send, notify_email.send_report):
        try:
            deliver(body, run_id=report_id)
        except Exception as exc:  # noqa: BLE001
            log.error("delivery failed (%s): %s", deliver.__module__, exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with run_context("weekly_report") as run:
        # Refresh media first so the rollup + inputs are fresh.
        try:
            run_media_sync(run)
        except Exception as exc:  # noqa: BLE001
            log.warning("media sync skipped/failed before report: %s", exc)
        _run(run)


if __name__ == "__main__":
    main()
