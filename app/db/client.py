"""Postgres access via a psycopg2 connection pool.

The Supabase REST client lacks raw SQL / reliable upsert, so all writes go through psycopg
with raw-SQL idempotent upserts (service_role bypasses RLS). Reads use the same pool.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2.pool import ThreadedConnectionPool

from app.config import settings

log = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None


def _pool_init() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        if not settings.supabase_db_url:
            raise RuntimeError("SUPABASE_DB_URL is not set — cannot connect to Postgres.")
        _pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=8,
            dsn=settings.supabase_db_url,
            cursor_factory=RealDictCursor,
        )
        log.debug("psycopg2 ThreadedConnectionPool initialised")
    return _pool


@contextmanager
def get_conn() -> Iterator:
    """Context manager yielding a pooled psycopg2 connection (autocommit=False)."""
    pool = _pool_init()
    conn = pool.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(commit: bool = True):
    """Context manager yielding a RealDictCursor; commits on success, rolls back on error."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                yield cur
                if commit:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise


def upsert(cur, table: str, row: dict, conflict_cols: list[str], *, update: bool = True) -> None:
    """Generic idempotent upsert into `table`.

    `row` keys are columns; `conflict_cols` is the natural key (UNIQUE/PK).
    `update=False` → INSERT ... ON CONFLICT DO NOTHING.
    JSON/list values are adapted via psycopg2 Json().
    """
    cols = list(row.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    adapted = [Json(v) if isinstance(v, (dict, list)) else v for v in row.values()]
    conflict = ", ".join(conflict_cols)

    if update:
        set_cols = [c for c in cols if c not in conflict_cols]
        if set_cols:
            set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in set_cols)
            action = f"DO UPDATE SET {set_clause}"
        else:
            action = "DO NOTHING"
    else:
        action = "DO NOTHING"

    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) {action}"
    )
    cur.execute(sql, adapted)
