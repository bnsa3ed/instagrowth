"""US5 auto-publish logic test.

Exercises the full queue → HITL approve → publish → back-link loop with SYNTHETIC media
and a MOCKED Content Publishing API. Nothing is created or published on Instagram.

Run: .venv/bin/python scripts/test_us5_logic.py
"""
from __future__ import annotations

from unittest.mock import patch

from app.config import settings
from app.db.client import get_cursor
from app.instagram.client import InstagramClient

IG = settings.ig_user_id
SYNTH_MEDIA = "https://placehold.co/600x600.png"


def _setup_draft() -> tuple[str, str]:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """SELECT id, topic_suggestion_id FROM content_drafts
                WHERE topic_suggestion_id IS NOT NULL
                ORDER BY created_at DESC LIMIT 1""")
        r = cur.fetchone()
        assert r, "no draft with a linked topic found (run auto_draft first)"
        # Approved + synthetic media + best_time = now (so it's immediately due).
        cur.execute(
            """UPDATE content_drafts
                  SET status='approved', media_url=%s, best_time=now()
                WHERE id=%s""",
            (SYNTH_MEDIA, r["id"]))
        return r["id"], r["topic_suggestion_id"]


def _row(cur, sql, *args):
    cur.execute(sql, *args)
    return cur.fetchone()


def main() -> None:
    draft_id, topic_id = _setup_draft()
    print(f"test draft: {draft_id} (topic {topic_id})")

    # Mock the Content Publishing API so NO real container/post is created on Instagram.
    with patch.object(InstagramClient, "create_container", return_value="SYNTH_CONTAINER_123"), \
         patch.object(InstagramClient, "publish_container", return_value="SYNTH_MEDIA_ID_456"), \
         patch("app.bot.hitl.request_approval") as mock_req:
        from app.bot import hitl
        from app.jobs import auto_publish

        # 1) Queue the approved draft → 'queued' publish_job + HITL prompt.
        auto_publish._queue_approved(IG)
        assert mock_req.called, "HITL request_approval not triggered"
        with get_cursor(commit=False) as cur:
            job = _row(cur, "SELECT id, status, scheduled_at FROM publish_jobs "
                            "WHERE content_draft_id=%s ORDER BY created_at DESC LIMIT 1", (draft_id,))
        assert job and job["status"] == "queued", f"expected queued job, got {job}"
        print(f"  ✓ step 1: publish_job {job['id']} queued (scheduled {job['scheduled_at']}); HITL prompt fired")

        # 2) HITL Approve → (mocked) container → job 'created'.
        hitl._on_approve(job["id"])
        with get_cursor(commit=False) as cur:
            j2 = _row(cur, "SELECT status, container_id FROM publish_jobs WHERE id=%s", (job["id"],))
        assert j2["status"] == "created" and j2["container_id"] == "SYNTH_CONTAINER_123", j2
        print(f"  ✓ step 2: approved → container {j2['container_id']}, status 'created'")

        # 3) publish_due → (mocked) publish → 'published' + back-links to draft + topic.
        auto_publish._publish_due(IG)
        with get_cursor(commit=False) as cur:
            j3 = _row(cur, "SELECT status, published_media_id FROM publish_jobs WHERE id=%s", (job["id"],))
            d = _row(cur, "SELECT status FROM content_drafts WHERE id=%s", (draft_id,))
            t = _row(cur, "SELECT status, published_media_id FROM topic_suggestions WHERE id=%s", (topic_id,))
        assert j3["status"] == "published" and j3["published_media_id"] == "SYNTH_MEDIA_ID_456", j3
        assert d["status"] == "published", d
        assert t["status"] == "published" and t["published_media_id"] == "SYNTH_MEDIA_ID_456", t
        print(f"  ✓ step 3: published → media_id {j3['published_media_id']}")
        print(f"  ✓ back-links: draft={d['status']}, topic={t['status']} "
              f"(published_media_id={t['published_media_id']})")

    # 4) HITL Skip path (no API) — verify status transitions on a second job.
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO publish_jobs (content_draft_id, scheduled_at, status)
               VALUES (%s, now(), 'queued') RETURNING id""", (draft_id,))
        jid = cur.fetchone()["id"]
    from app.bot import hitl
    hitl._on_skip(jid)
    with get_cursor(commit=False) as cur:
        sk = _row(cur, "SELECT status, error FROM publish_jobs WHERE id=%s", (jid,))
    assert sk["status"] == "failed" and "skipped" in (sk["error"] or ""), sk
    print(f"  ✓ step 4: skip path → job {jid} {sk['status']} ({sk['error']})")

    # Cleanup synthetic state so the live account data isn't polluted.
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM publish_jobs WHERE content_draft_id=%s", (draft_id,))
        cur.execute("UPDATE content_drafts SET status='draft', media_url=NULL WHERE id=%s", (draft_id,))
        cur.execute("UPDATE topic_suggestions SET status='suggested', published_media_id=NULL WHERE id=%s",
                    (topic_id,))
    print("  ✓ cleaned up synthetic publish state")
    print("\nALL US5 LOGIC CHECKS PASSED ✅  (no real Instagram publish occurred)")


if __name__ == "__main__":
    main()
