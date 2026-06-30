"""Token health — hourly refresh or alert when ≤7d to expiry.

System User tokens (preferred) are non-expiring → this is a cheap no-op health check.
60-day long-lived tokens are refreshed via `app/instagram/token.py`; alert on refresh failure.

Run: `python -m app.jobs.token_health`
"""
from __future__ import annotations

import logging

from app.db.logging import run_context
from app.instagram import token
from app.notify import telegram as notify_telegram

log = logging.getLogger("token_health")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with run_context("token_health") as run:
        status = token.status()
        secs = token.seconds_until_expiry()

        if status.is_system_user:
            run.add_meta(token_kind="system_user", expires=None)
            log.debug("System User token present (non-expiring)")
            return

        refreshed, alert = token.refresh_if_needed()
        run.add_meta(token_kind="long_lived", refreshed=refreshed,
                     expires_in_days=(secs // 86400) if secs else None)

        if alert:
            run.mark_partial("token alert")
            try:
                notify_telegram.send(alert, run_id="token_health")
            except Exception as exc:  # noqa: BLE001
                log.error("token alert delivery failed: %s", exc)


if __name__ == "__main__":
    main()
