"""Token lifecycle management.

Preferred: a Facebook-Login **System User token** (does not expire on time) — this module
is then mostly a no-op health check. Fallback: a 60-day long-lived user token, refreshed via
`ig_refresh_token` on the Instagram Login path. Expiry is tracked in-memory + surfaced to
`pipeline_runs.meta` so the hourly job can alert when ≤7d to expiry.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from app.config import settings
from app.utils.retry import get as retry_get

log = logging.getLogger(__name__)

# Long-lived IG tokens are 60 days; refresh extends them when ≤7d remain.
LONG_LIVED_TTL_SECONDS = 60 * 24 * 3600
REFRESH_THRESHOLD_SECONDS = 7 * 24 * 3600
ALERT_THRESHOLD_SECONDS = 3 * 24 * 3600


@dataclass
class TokenStatus:
    token: str
    is_system_user: bool
    expires_in_seconds: int | None  # None ⇒ unknown / System User (treated as non-expiring)


def current() -> str:
    """The active token (from settings/env). Never log this."""
    return settings.meta_token


def is_system_user_token() -> bool:
    """Heuristic: System User tokens don't expire; we treat a System User setup as the source.

    Set META_TOKEN_KIND=system_user in .env to mark it explicitly; otherwise we assume a
    long-lived user token and run the refresh path.
    """
    import os
    return os.getenv("META_TOKEN_KIND", "").lower() in ("system_user", "system-user", "su")


def status() -> TokenStatus:
    if is_system_user_token():
        return TokenStatus(current(), True, None)
    # Without a debug_token call we assume a fresh long-lived token at process start.
    return TokenStatus(current(), False, LONG_LIVED_TTL_SECONDS)


def _refresh_long_lived(client: httpx.Client) -> str:
    """Exchange a long-lived token for a fresh one (Instagram Login path)."""
    body = retry_get(
        client,
        f"{settings.graph_base}/refresh_access_token",
        grant_type="ig_refresh_token",
        access_token=current(),
    )
    return body["access_token"]


def refresh_if_needed() -> tuple[str, bool, str | None]:
    """Refresh a near-expiry long-lived token; alert if refresh fails near expiry.

    Returns (token, refreshed?, alert_message_or_None). For System User tokens this is a no-op.
    """
    st = status()
    if st.is_system_user:
        log.debug("System User token — no refresh needed")
        return st.token, False, None

    try:
        new_token = _refresh_long_lived(httpx.Client(timeout=20.0))
        log.info("Long-lived token refreshed")
        # NOTE: persisting the new token is environment-specific (Docker secret / Vault).
        # The operator rotates it where META_TOKEN is sourced from.
        return new_token, True, None
    except Exception as exc:  # noqa: BLE001
        log.error("token refresh failed: %s", exc)
        if st.expires_in_seconds is not None and st.expires_in_seconds <= ALERT_THRESHOLD_SECONDS:
            return st.token, False, f"⚠️ فشل تجديد التوكن وينتهي خلال {st.expires_in_seconds//86400} أيام"
        return st.token, False, None


def seconds_until_expiry() -> int | None:
    st = status()
    return st.expires_in_seconds
