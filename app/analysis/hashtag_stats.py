"""Hashtag optimization — pick a rotated set of broad + niche tags from real performance.

Reads `v_hashtag_stats` (per-tag reach/engagement, decay handling). Caps ~10–15 tags and
mixes broad (target_hashtags) with niche (top performers) while avoiding penalized repetition
vs the last few posts.
"""
from __future__ import annotations

import logging

from app.db.client import get_cursor

log = logging.getLogger(__name__)

CAP = 12


def suggest(ig_user_id: str, seed_hashtags: list[str], topic_keywords: list[str] | None = None,
            recent_limit: int = 3) -> list[str]:
    """Return a rotated tag set: top performers + broad seeds + niche topic tags."""
    import re
    with get_cursor(commit=False) as cur:
        cur.execute(
            """SELECT hashtag, avg_engagement_rate, avg_reach
                 FROM v_hashtag_stats
                WHERE ig_user_id = %s
                ORDER BY COALESCE(avg_reach,0) DESC LIMIT 20""",
            (ig_user_id,))
        perf = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT caption FROM ig_media
                WHERE ig_user_id=%s AND caption IS NOT NULL
                ORDER BY publish_date DESC LIMIT %s""",
            (ig_user_id, recent_limit))
        recent = {m.group(1).lower() for r in cur.fetchall() if r["caption"]
                  for m in re.finditer(r"#([A-Za-z0-9_]+)", r["caption"])}

    # Top historical performers (decay: skip those over-used in recent posts).
    out: list[str] = []
    seen = set()
    for p in perf:
        t = p["hashtag"]
        if t in recent or t in seen:
            continue
        out.append("#" + t); seen.add(t)
        if len(out) >= CAP // 2:
            break
    # Broad seeds.
    for t in seed_hashtags:
        t = t.lstrip("#")
        if t.lower() not in seen:
            out.append("#" + t); seen.add(t.lower())
    # Niche topic-derived tags (extra freshness), cap total.
    for kw in (topic_keywords or []):
        if len(out) >= CAP:
            break
        tag = "#" + kw.lower().replace(" ", "")
        if tag.lstrip("#") not in seen:
            out.append(tag); seen.add(tag.lstrip("#"))
    return out[:CAP]
