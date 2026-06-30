"""pipeline_runs audit logging — one row per job run (observability + idempotency).

Usage:
    with run_context('daily_sync') as run:
        ... do work ...
        run.api_calls_used = n
        run.meta = {'buc_budget_remaining': ...}
    # on exit: status='success' (or 'failed'/'partial' on exception), finished_at set.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from psycopg2.extras import Json

from app.db.client import get_cursor

log = logging.getLogger(__name__)


class PipelineRun:
    def __init__(self, job_name: str, run_id: str | None = None):
        self.job_name = job_name
        self.run_id = run_id or str(uuid.uuid4())
        self.api_calls_used = 0
        self.meta: dict[str, Any] = {}
        self._status = "success"

    def mark_partial(self, reason: str = "") -> None:
        self._status = "partial"
        if reason:
            self.meta["partial_reason"] = reason

    def add_cost(self, cost_usd: float) -> None:
        self.meta["cost_usd"] = round(self.meta.get("cost_usd", 0.0) + cost_usd, 6)

    def add_meta(self, **kw: Any) -> None:
        self.meta.update(kw)


def start_run(cur, job_name: str, run_id: str | None = None) -> PipelineRun:
    run = PipelineRun(job_name, run_id)
    cur.execute(
        "INSERT INTO pipeline_runs (run_id, job_name, status) VALUES (%s, %s, 'success')",
        (run.run_id, run.job_name),
    )
    return run


def finish_run(cur, run: PipelineRun, status: str | None = None, error: str | None = None) -> None:
    cur.execute(
        """UPDATE pipeline_runs
              SET finished_at = %s,
                  status = %s,
                  api_calls_used = %s,
                  error = %s,
                  meta = %s
            WHERE run_id = %s""",
        (
            datetime.now(timezone.utc),
            status or run._status,
            run.api_calls_used,
            error,
            Json(run.meta) if run.meta else None,
            run.run_id,
        ),
    )


@contextmanager
def run_context(job_name: str) -> Iterator[PipelineRun]:
    """Wrap a job: insert a pipeline_runs row at start, set final status on exit.

    The run's `run_id` doubles as an idempotency/dedup key for delivery.
    """
    run = PipelineRun(job_name)
    with get_cursor(commit=True) as cur:
        start_run(cur, job_name, run.run_id)
    try:
        yield run
    except Exception as exc:
        log.exception("%s failed", job_name)
        with get_cursor(commit=True) as cur:
            finish_run(cur, run, status="failed", error=str(exc))
        raise
    else:
        with get_cursor(commit=True) as cur:
            finish_run(cur, run)
