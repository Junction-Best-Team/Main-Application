import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from aimo.config import settings


def now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def js(value: Any) -> Jsonb:
    return Jsonb(json.loads(json.dumps(value, default=str)))


@contextmanager
def connection():
    with psycopg.connect(settings().database_url, row_factory=dict_row) as conn:
        yield conn


class Problem(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)
