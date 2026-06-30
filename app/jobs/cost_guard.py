"""Cost guardrail job — aggregate monthly AI spend; alert at 80%, throttle at 100%.

The throttle itself is enforced inside the non-essential AI jobs via
`app.utils.cost.is_ai_throttled()`; this job is the alerting + observability half.

Run: `python -m app.jobs.cost_guard`
"""
from __future__ import annotations

import logging

from app.config import settings
from app.db.logging import run_context
from app.utils import cost

log = logging.getLogger("cost_guard")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ig_user_id = settings.ig_user_id
    with run_context("cost_guard") as run:
        spent = cost.monthly_spend_usd()
        cap = cost.cap_usd(ig_user_id)
        frac = cost.spend_fraction(ig_user_id)
        run.add_meta(monthly_spend_usd=round(spent, 4), cap_usd=cap, spend_fraction=round(frac, 3))

        if frac >= 1.0:
            msg = (f"🛑 وصل الإنفاق الشهري {spent:.2f}$ من الطابعة {cap:.2f}$ (100%). "
                   f"تم تقليل الذكاء الاصطناعي غير الأساسي — لسه شغّالين جمع البيانات ورادار الأنومالي.")
            run.mark_partial("cost cap reached — AI throttled")
            from app.notify import telegram
            try:
                telegram.send(msg, run_id="cost-throttle")
            except Exception as exc:  # noqa: BLE001
                log.error("cost alert failed: %s", exc)
        elif frac >= cost.ALERT_FRACTION:
            msg = (f"⚠️ الإنفاق الشهري وصل {frac:.0%} ({spent:.2f}$ من {cap:.2f}$). "
                   f"قرب من الطابعة — راجع استخدام الذكاء الاصطناعي.")
            from app.notify import telegram
            try:
                telegram.send(msg, run_id="cost-warn")
            except Exception as exc:  # noqa: BLE001
                log.error("cost alert failed: %s", exc)


if __name__ == "__main__":
    main()
