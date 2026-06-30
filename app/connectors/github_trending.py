"""GitHub Trending connector — scrapes github.com/trending (free, no API key).

A lightweight HTML scrape of the trending page. The page structure is stable enough for
title+url extraction; we keep the raw HTML slice for inspection in raw_json on failure.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.connectors.base import MAX, get_text, normalize

log = logging.getLogger(__name__)

URL = "https://github.com/trending?since=daily"
REPO_RE = re.compile(r'<h2 class="h3 lh-condensed">.*?<a href="(/[^"]+)"', re.S)


def fetch(ig_user_id: str, max_items: int = MAX) -> list[dict]:
    try:
        html = get_text(URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("GitHub trending fetch failed: %s", exc)
        return []

    out: list[dict] = []
    for path in REPO_RE.findall(html)[:max_items]:
        slug = path.strip().strip("/")
        title = slug
        url = f"https://github.com/{slug}"
        out.append(normalize(source="github", title=title, url=url,
                             signal_ts=datetime.now(timezone.utc), raw={"repo": slug}))
    return out
