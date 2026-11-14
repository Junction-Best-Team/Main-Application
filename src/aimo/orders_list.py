"""The customer's orders list (CNF-034, Q-77, Q-78): derived, never an update of an order.

One query over three sources, newest first, one row per thing the customer cares about:

- `scheduled`: an active standing order (scheduled authorization), dated by its next run;
- `placed`: an order request that became a (mock) order;
- `cancelled`: an order request with a row in `order_request_cancellations`; a request replaced
  by a retry (`run_retry`) is hidden;
- `pending`: a request being processed and placed (current revision not expired). An expired,
  unconfirmed request is hidden.

Orders stay immutable (CNF-020); nothing here writes.
"""

from aimo.db import Problem, connection
from aimo.db import now as clock
from aimo.purchases import context

LIST_SQL = """
WITH rows AS (
  SELECT CASE
           WHEN o.id IS NOT NULL THEN 'placed'
           WHEN x.proposal_id IS NOT NULL THEN 'cancelled'
           ELSE 'pending' END AS status,
         r.request->>'request_id' AS title,
         NULL::date AS scheduled_for,
         p.id::text AS proposal_id, o.id::text AS order_id, NULL::text AS schedule_id,
         r.snapshot->>'gross_total' AS gross_total, r.snapshot->>'currency' AS currency,
         COALESCE(jsonb_array_length(r.request->'lines'), 0) AS line_count,
         x.reason AS cancel_reason,
         COALESCE(o.created_at, x.created_at, p.updated_at) AS sort_at,
         p.id::text AS sort_key
  FROM proposals p
  JOIN proposal_revisions r ON r.proposal_id=p.id AND r.revision=p.current_revision
  LEFT JOIN orders o ON o.proposal_id=p.id
  LEFT JOIN order_request_cancellations x ON x.proposal_id=p.id
  WHERE p.buyer_id=%(buyer)s
    AND (o.id IS NOT NULL
         OR (x.proposal_id IS NOT NULL AND x.reason <> 'run_retry')
         OR (x.proposal_id IS NULL AND r.expires_at > %(now)s))
  UNION ALL
  SELECT 'scheduled', COALESCE(a.request->>'request_id', 'Standing order'), a.next_run_date,
         NULL, NULL, a.id::text, a.agreed_gross_total::text, a.currency,
         COALESCE(jsonb_array_length(a.request->'lines'), 0), NULL,
         (a.next_run_date::timestamp AT TIME ZONE 'Europe/Helsinki'), a.id::text
  FROM scheduled_authorizations a
  WHERE a.buyer_id=%(buyer)s AND a.status='active' AND a.next_run_date IS NOT NULL
)
SELECT * FROM rows ORDER BY sort_at DESC, sort_key DESC LIMIT %(limit)s OFFSET %(offset)s
"""


def orders_page(identity, offset=0, limit=20, now=None):
    if identity["role"] != "approver":
        raise Problem("FORBIDDEN", "Only a buyer session can list orders.", 403)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        context(c, identity)
        rows = c.execute(
            LIST_SQL,
            {
                "buyer": identity["buyer_id"],
                "now": now or clock(),
                "limit": limit + 1,
                "offset": offset,
            },
        ).fetchall()
    return {
        "items": [_item(row) for row in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


def _item(row):
    return {
        "status": row["status"],
        "title": row["title"],
        "scheduled_for": row["scheduled_for"].isoformat() if row["scheduled_for"] else None,
        "proposal_id": row["proposal_id"],
        "order_id": row["order_id"],
        "schedule_id": row["schedule_id"],
        "gross_total": row["gross_total"],
        "currency": row["currency"],
        "line_count": row["line_count"],
        "cancel_reason": row["cancel_reason"],
        "updated_at": row["sort_at"],
    }
