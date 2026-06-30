"""Business Use-Case (BUC) rate-limit tracking.

Meta rate limits via the `X-Business-Use-Case` / `X-App-Usage` response headers
(`calls within 24h = 4800 × impressions` per app+user pair, rolling 24h). We parse
remaining budget from every Graph API response and store it in `pipeline_runs.meta`
so the cost-guard / alerting can throttle before a hard 429.

Usage:
    buc.update_from_headers(resp.headers)         # call after each Graph API response
    if not buc.has_budget(): ...                   # < 15% → slow down / alert
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

ALERT_THRESHOLD = 0.15  # alert when remaining BUC budget drops below 15%


@dataclass
class _Budget:
    call_count: int = 0
    total_time: int = 0
    total_cputime: int = 0
    # The Meta header expresses *usage as a % of 100*; we convert to remaining fraction.
    usage_pct: float = 0.0


@dataclass
class BucState:
    business: _Budget = field(default_factory=_Budget)   # X-Business-Use-Case
    app: _Budget = field(default_factory=_Budget)        # X-App-Usage
    last_raw: dict = field(default_factory=dict)

    def remaining_fraction(self) -> float:
        """Most-constrained remaining budget across business + app usage (0..1)."""
        used = max(self.business.usage_pct, self.app.usage_pct)
        return max(0.0, 1.0 - used / 100.0)

    def as_meta(self) -> dict:
        return {
            "buc_business_usage_pct": round(self.business.usage_pct, 2),
            "buc_app_usage_pct": round(self.app.usage_pct, 2),
            "buc_budget_remaining": round(self.remaining_fraction(), 3),
        }


_state = BucState()
_lock = threading.Lock()


def _parse_usage(value: str) -> _Budget:
    """Parse an X-*-Usage style header into a _Budget (best-effort)."""
    budget = _Budget()
    if not value:
        return budget
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return budget
    # Common shapes: {"call_count":12,"total_cputime":3,"total_time":4}
    # or nested per-method: {"POST":{"call_count":...,"total_time":...}}
    call = total_t = total_cpu = 0.0
    for v in data.values():
        if isinstance(v, dict):
            call += float(v.get("call_count", 0) or 0)
            total_t += float(v.get("total_time", 0) or 0)
            total_cpu += float(v.get("total_cputime", 0) or 0)
        elif isinstance(v, (int, float)):
            # flat {"call_count": N}
            pass
    budget.call_count = int(call)
    budget.total_time = int(total_t)
    budget.total_cputime = int(total_cpu)
    # Heuristic: treat the largest call_count ratio as usage %. Real BUC header gives
    # an explicit %; we fall back gracefully if only raw counts are present.
    budget.usage_pct = float(data.get("usage_pct", 0) or 0) or min(100.0, call)
    return budget


def update_from_headers(headers) -> None:
    """Read X-Business-Use-Case / X-App-Usage from a response; update shared state."""
    biz = headers.get("X-Business-Use-Case") or headers.get("x-business-use-case")
    app = headers.get("X-App-Usage") or headers.get("x-app-usage")
    with _lock:
        if biz:
            _state.business = _parse_usage(biz)
            _state.last_raw["business"] = biz[:200]
        if app:
            _state.app = _parse_usage(app)
            _state.last_raw["app"] = app[:200]


def snapshot() -> BucState:
    with _lock:
        return BucState(
            business=_Budget(
                call_count=_state.business.call_count,
                total_time=_state.business.total_time,
                total_cputime=_state.business.total_cputime,
                usage_pct=_state.business.usage_pct,
            ),
            app=_Budget(
                call_count=_state.app.call_count,
                total_time=_state.app.total_time,
                total_cputime=_state.app.total_cputime,
                usage_pct=_state.app.usage_pct,
            ),
            last_raw=dict(_state.last_raw),
        )


def has_budget() -> bool:
    """False when remaining BUC budget is below the alert threshold."""
    return snapshot().remaining_fraction() > ALERT_THRESHOLD
