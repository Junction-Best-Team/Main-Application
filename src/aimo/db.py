import atexit
import hashlib
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from psycopg import Error
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout, TooManyRequests

from aimo.config import settings
from aimo.observability import elapsed, event, failure


def now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def js(value: Any) -> Jsonb:
    return Jsonb(json.loads(json.dumps(value, default=str)))


_pools = {}
_pool_lock = Lock()


def pool():
    cfg = settings()
    key = (cfg.database_url, cfg.db_pool_max_size, cfg.db_pool_timeout_seconds)
    with _pool_lock:
        if key not in _pools:
            _pools[key] = ConnectionPool(
                cfg.database_url,
                min_size=0,
                max_size=cfg.db_pool_max_size,
                timeout=cfg.db_pool_timeout_seconds,
                max_waiting=50,
                max_idle=60,
                kwargs={"row_factory": dict_row, "connect_timeout": 5},
                check=ConnectionPool.check_connection,
                open=True,
            )
        return _pools[key]


def close_pools():
    with _pool_lock:
        old = list(_pools.values())
        _pools.clear()
    for item in old:
        item.close()


atexit.register(close_pools)


@contextmanager
def connection():
    started = time.monotonic()
    acquired = None
    try:
        with pool().connection() as conn:
            acquired = time.monotonic()
            yield conn
    except (PoolTimeout, TooManyRequests) as exc:
        event(
            "database.pool_exhausted",
            level=logging.WARNING,
            error_code="DATABASE_BUSY",
            error_type=type(exc).__name__,
            duration_ms=elapsed(started),
        )
        raise Problem(
            "DATABASE_BUSY", "Database capacity is temporarily unavailable; retry later.", 503
        ) from None
    except Error as exc:
        event(
            "database.transaction_failed",
            level=logging.WARNING,
            duration_ms=elapsed(started),
            sqlstate=exc.sqlstate,
            phase="acquire" if acquired is None else "transaction",
            **failure(exc),
        )
        raise
    finally:
        duration = elapsed(started)
        if duration >= 1000:
            event("database.slow_connection", level=logging.WARNING, duration_ms=duration,
                  acquisition_ms=round((acquired - started) * 1000, 2) if acquired else None,
                  transaction_ms=elapsed(acquired) if acquired else None)


class Problem(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 409,
        retry_after: int | None = None,
        details=None,
    ):
        self.code, self.message, self.status = code, message, status
        self.retry_after = retry_after
        if details is not None:
            self.details = details  # JSON-ready, client-safe (the browser sees error.details)
        super().__init__(message)

    details = None  # structured, client-safe extra fields; a subclass may set an instance value

    def body(self) -> dict:
        """The `error` object sent to the browser and to the model: code, message, details."""
        error = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return error
