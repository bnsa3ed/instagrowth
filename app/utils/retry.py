"""HTTP retry helper — exponential backoff + jitter, honoring Retry-After.

Wraps every outbound httpx call. Retries on 429/5xx and the Meta Business Use-Case
throttle subcodes (4 app, 17 user, 32 Pages, 613 BUC, 80005 instagram).
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

# Subcodes that indicate BUC/rate limiting in a Meta error body (graph.facebook.com).
META_THROTTLE_SUBCODES = {4, 17, 32, 613, 80005}

# Exponential backoff schedule (seconds) ± jitter, per plan §6.3.
BACKOFF_SCHEDULE = [(2, 1), (8, 4), (30, 10)]
MAX_RETRIES = 3


class RetryableError(Exception):
    """Raised when a call exhausts its retries."""


def _meta_subcode(exc: Exception) -> int | None:
    """Extract an error subcode from a Meta JSON error payload, if present."""
    data = getattr(exc, "response", None)
    if data is not None and hasattr(data, "json"):
        try:
            body = data.json()
        except Exception:  # noqa: BLE001
            return None
        for err in body.get("error", {}).values() if isinstance(body.get("error"), dict) else []:
            pass
        try:
            return int(body["error"]["error_subcode"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _retry_after(exc: Exception) -> float | None:
    data = getattr(exc, "response", None)
    if data is not None and hasattr(data, "headers"):
        ra = data.headers.get("Retry-After")
        if ra:
            try:
                return float(ra)
            except ValueError:
                return None
    return None


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429 or code >= 500:
            return True
        if code == 400 and _meta_subcode(exc) in META_THROTTLE_SUBCODES:
            return True
    return False


def retry_call(
    fn: Callable[..., Any],
    *args: Any,
    retries: int = MAX_RETRIES,
    schedule: list[tuple[float, float]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> Any:
    """Call `fn(*args, **kwargs)`; retry retryable failures with backoff + jitter.

    `fn` is expected to raise httpx.HTTPStatusError / TransportError on failure.
    """
    schedule = schedule or BACKOFF_SCHEDULE
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_retryable(exc) or attempt == retries:
                raise
            base, jitter = schedule[min(attempt, len(schedule) - 1)]
            delay = base + random.uniform(-jitter, jitter)
            ra = _retry_after(exc)
            if ra is not None:
                delay = max(delay, ra)
            log.warning("retryable error (%s); backoff %.1fs (attempt %d/%d)",
                        type(exc).__name__, delay, attempt + 1, retries)
            sleep(delay)
    raise RetryableError(str(last_exc))


def get(client: httpx.Client, url: str, **params: Any) -> dict:
    """GET with retries; returns parsed JSON. Raises httpx.HTTPStatusError on terminal failure."""
    resp = retry_call(
        client.get, url, params=params,
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()


def post(client: httpx.Client, url: str, **kwargs: Any) -> dict:
    """POST with retries; returns parsed JSON."""
    resp = retry_call(client.post, url, **kwargs, headers={"Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()
