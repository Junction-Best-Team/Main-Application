"""Scheduled (standing) re-orders, WS-E. Every order placed here is a MOCK order.

Only the commit guard exists so far. It fails closed: no scheduled authorization or run exists
yet, so the scheduler identity can commit nothing. The run engine replaces this body.
"""

from aimo.db import Problem


def ensure_commit_allowed(c, identity, p, r, snapshot, evaluated):
    raise Problem(
        "SCHEDULE_NOT_AUTHORIZED",
        "A scheduler identity commits only against a valid scheduled authorization.",
        403,
    )
