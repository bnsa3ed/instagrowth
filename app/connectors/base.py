"""Shared connector helpers — normalization + dedup hashing for trend signals.

Each connector returns a list of raw normalized dicts; `trend_scan` computes the
`signal_hash` (sha256 of `url|title`) and idempotently upserts into `trend_signals`.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.utils.retry import get as retry_get

log = logging.getLogger(__name__)


def signal_hash(url: str | None, title: str) -> str:
    return hashlib.sha256(f"{url or ''}|{title}".encode("utf-8")).hexdigest()


def normalize(
    *,
    source: str,
    title: str,
    url: str | None = None,
    summary: str | None = None,
    signal_ts: datetime | None = None,
    momentum: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "title": title.strip(),
        "url": url,
        "summary": (summary or "").strip() or None,
        "signal_ts": (signal_ts or datetime.now(timezone.utc)).isoformat(),
        "momentum": momentum,
        "signal_hash": signal_hash(url, title.strip()),
        "raw_json": raw,
    }


def get_json(url: str, **params: Any) -> Any:
    with httpx.Client(timeout=20.0, headers={"Accept": "application/json",
                                              "User-Agent": "instagrowth/0.1"}) as client:
        return retry_get(client, url, **params)


def get_text(url: str, **params: Any) -> str:
    """Raw text (for HTML sources) with retry."""
    with httpx.Client(timeout=20.0, headers={"User-Agent": "instagrowth/0.1"}) as client:
        from app.utils.retry import retry_call
        r = retry_call(client.get, url, params=params)
        r.raise_for_status()
        return r.text


MAX = settings.trend_max_per_source
