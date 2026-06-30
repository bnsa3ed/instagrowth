"""Auto-publish — Content Publishing API lifecycle behind a mandatory HITL gate.

Flow (per plan §9.6):
  1. Approved drafts (status='approved') WITH media_url  → create a `publish_jobs` row
     (status='queued', scheduled_at=draft.best_time) and ask the always-on bot to show the
     Approve/Edit/Skip keyboard.
  2. On Approve (handled by app/bot/hitl.py) → create the IG container + set job status='created'.
  3. This job publishes due jobs (status='created' AND scheduled_at <= now) → write back the
     resulting `published_media_id` to content_drafts AND topic_suggestions (closes the loop).
  Drafts WITHOUT media_url are NOT queued; they ping the owner to attach media.

Run: `python -m app.jobs.auto_publish`
"""
from __future__ import annotations

import logging

from app.config import settings
from app.db.client import get_cursor
from app.db.logging import run_context
from app.instagram.client import InstagramClient

log = logging.getLogger("auto_publish")


def _queue_approved(ig_user_id: str) -> int:
    """Create publish_jobs for newly-approved drafts that have media; ping owner otherwise."""
    queued = 0
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT cd.id, cd.best_time, cd.media_url, cd.media_source, cd.format
                 FROM content_drafts cd
                WHERE cd.ig_user_id=%s AND cd.status='approved'
                  AND NOT EXISTS (SELECT 1 FROM publish_jobs pj WHERE pj.content_draft_id = cd.id)""",
            (ig_user_id,))
        drafts = [dict(r) for r in cur.fetchall()]

    from app.notify import telegram
    with get_cursor(commit=True) as cur:
        for d in drafts:
            if not d.get("media_url"):
                try:
                    telegram.send(
                        f"📝 مسودة معتمدة محتاجة ميديا قبل النشر (draft {d['id']}) — ارفع الأصل "
                        f"على Storage والصق الرابط في media_url",
                        run_id=f"need-media-{d['id']}")
                except Exception as exc:  # noqa: BLE001
                    log.warning("media-needed ping failed: %s", exc)
                continue
            cur.execute(
                """INSERT INTO publish_jobs (content_draft_id, scheduled_at, status)
                   VALUES (%s, %s, 'queued')""",
                (d["id"], d.get("best_time")),
            )
            queued += 1
            # Ask the HITL bot to render the Approve/Edit/Skip keyboard for this job.
            try:
                from app.bot import hitl
                hitl.request_approval(_last_job_id(cur, d["id"]))
            except Exception as exc:  # noqa: BLE001
                log.warning("HITL request failed (job will still await approval): %s", exc)
    return queued


def _last_job_id(cur, draft_id: str):
    cur.execute("SELECT id FROM publish_jobs WHERE content_draft_id=%s ORDER BY created_at DESC LIMIT 1",
                (draft_id,))
    row = cur.fetchone()
    return row["id"] if row else None


def _publish_due(ig_user_id: str) -> int:
    """Publish containers whose scheduled time has arrived; back-link the resulting media_id."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT pj.id, pj.container_id, cd.id AS draft_id, cd.format, cd.caption,
                      cd.media_url, cd.topic_suggestion_id
                 FROM publish_jobs pj JOIN content_drafts cd ON cd.id = pj.content_draft_id
                WHERE pj.status='created' AND pj.scheduled_at <= now()""")
        due = [dict(r) for r in cur.fetchall()]
    if not due:
        return 0

    published = 0
    with InstagramClient() as ig:
        with get_cursor(commit=True) as cur:
            for j in due:
                try:
                    media_id = ig.publish_container(j["container_id"])
                except Exception as exc:  # noqa: BLE001
                    cur.execute(
                        "UPDATE publish_jobs SET status='failed', error=%s, attempts=attempts+1 WHERE id=%s",
                        (str(exc)[:500], j["id"]))
                    log.error("publish failed for job %s: %s", j["id"], exc)
                    continue
                cur.execute(
                    "UPDATE publish_jobs SET status='published', published_media_id=%s WHERE id=%s",
                    (media_id, j["id"]))
                # Close the loop: back-link to draft + topic.
                cur.execute(
                    "UPDATE content_drafts SET status='published' WHERE id=%s", (j["draft_id"],))
                if j.get("topic_suggestion_id"):
                    cur.execute(
                        """UPDATE topic_suggestions
                              SET status='published', published_media_id=%s WHERE id=%s""",
                        (media_id, j["topic_suggestion_id"]))
                published += 1
    return published


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ig_user_id = settings.ig_user_id
    with run_context("auto_publish") as run:
        queued = _queue_approved(ig_user_id)
        published = _publish_due(ig_user_id)
        run.add_meta(jobs_queued=queued, jobs_published=published)


if __name__ == "__main__":
    main()
