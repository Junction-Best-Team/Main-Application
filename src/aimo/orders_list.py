"""The customer's orders list (CNF-034, Q-77, Q-78): derived, never an update of an order.

One query over three sources, newest first, one row per thing the customer cares about:

- `scheduled`: an active or paused standing order (scheduled authorization), dated by its next
  run, `paused` marking the paused one; a request that a standing order's run produced also
  carries `schedule_id` and `schedule_title`;
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
WITH label AS (
  -- The same label as ScheduleResponse.title: the source order's request label.
  SELECT a.id,
         COALESCE(sr.request->>'request_id', 'Standing order') AS title
  FROM scheduled_authorizations a
  JOIN orders so ON so.id=a.source_order_id
  JOIN proposal_revisions sr ON sr.proposal_id=so.proposal_id AND sr.revision=so.revision
  WHERE a.buyer_id=%(buyer)s
), rows AS (
  SELECT CASE
           WHEN o.id IS NOT NULL THEN 'placed'
           WHEN x.proposal_id IS NOT NULL THEN 'cancelled'
           ELSE 'pending' END AS status,
         r.request->>'request_id' AS title,
         NULL::date AS scheduled_for,
         p.id::text AS proposal_id, o.id::text AS order_id, link.authorization_id::text AS schedule_id,
         link.title AS schedule_title, false AS paused,
         r.snapshot->>'gross_total' AS gross_total, r.snapshot->>'currency' AS currency,
         COALESCE(jsonb_array_length(r.request->'lines'), 0) AS line_count,
         x.reason AS cancel_reason, o.created_at AS placed_at,
         COALESCE(o.created_at, x.created_at, p.updated_at) AS sort_at,
         p.id::text AS sort_key,
         COALESCE((SELECT array_agg(t.l->>'name' ORDER BY NULLIF(t.l->>'gross', '')::numeric DESC NULLS LAST, t.n)
                   FROM jsonb_array_elements(r.snapshot->'lines') WITH ORDINALITY AS t(l, n)
                   WHERE t.l->>'name' IS NOT NULL), '{}') AS names,
         COALESCE((SELECT array_agg(t.l->>'product_id' ORDER BY t.n)
                   FROM jsonb_array_elements(r.request->'lines') WITH ORDINALITY AS t(l, n)), '{}') AS product_ids,
         r.request->>'destination' AS destination, r.request->>'delivery_date' AS delivery_date
  FROM proposals p
  JOIN proposal_revisions r ON r.proposal_id=p.id AND r.revision=p.current_revision
  LEFT JOIN orders o ON o.proposal_id=p.id
  LEFT JOIN order_request_cancellations x ON x.proposal_id=p.id
  LEFT JOIN LATERAL (
    SELECT sr.authorization_id, l.title FROM scheduled_runs sr
    JOIN label l ON l.id=sr.authorization_id
    WHERE sr.proposal_id=p.id LIMIT 1
  ) link ON true
  WHERE p.buyer_id=%(buyer)s
    AND (o.id IS NOT NULL
         OR (x.proposal_id IS NOT NULL AND x.reason <> 'run_retry')
         OR (x.proposal_id IS NULL AND r.expires_at > %(now)s))
  UNION ALL
  SELECT 'scheduled', l.title, a.next_run_date, NULL, NULL, a.id::text, l.title,
         a.status = 'paused', a.agreed_gross_total::text, a.currency,
         COALESCE(jsonb_array_length(a.request->'lines'), 0), NULL, NULL::timestamptz,
         COALESCE(a.next_run_date::timestamp AT TIME ZONE 'Europe/Helsinki', a.updated_at),
         a.id::text,
         COALESCE((SELECT array_agg(t.l->>'name' ORDER BY NULLIF(t.l->>'line_gross', '')::numeric DESC NULLS LAST, t.n)
                   FROM jsonb_array_elements(a.agreed_lines) WITH ORDINALITY AS t(l, n)
                   WHERE t.l->>'name' IS NOT NULL), '{}'),
         COALESCE((SELECT array_agg(t.l->>'product_id' ORDER BY t.n)
                   FROM jsonb_array_elements(a.agreed_lines) WITH ORDINALITY AS t(l, n)), '{}'),
         a.request->>'destination', (a.next_run_date + a.delivery_offset_days)::text
  FROM scheduled_authorizations a JOIN label l ON l.id=a.id
  WHERE a.buyer_id=%(buyer)s AND a.status IN ('active', 'paused')
)
SELECT *, count(*) OVER () AS total FROM rows
WHERE {filter}
ORDER BY sort_at DESC, sort_key DESC LIMIT %(limit)s OFFSET %(offset)s
"""

# Status and search filter shared by the page and the count. `q` is matched with strpos on
# lower-cased text, so LIKE wildcards in what the customer types stay literal.
FILTER = """(cardinality(%(statuses)s::text[]) = 0 OR status = ANY(%(statuses)s::text[]))
AND (%(q)s = '' OR strpos(lower(concat_ws(' ', title, schedule_title, order_id, proposal_id,
     schedule_id, destination, delivery_date, array_to_string(names, ' '),
     array_to_string(product_ids, ' '))), lower(%(q)s)) > 0)"""

LIST_SQL = LIST_SQL.replace("{filter}", FILTER)

COUNT_SQL = (
    LIST_SQL.split("SELECT *, count(*) OVER ()")[0]
    + "SELECT count(*) AS total FROM rows WHERE "
    + FILTER
)

MAX_QUERY_LENGTH = 80
MAX_LINE_NAMES = 5

STATUSES = ("scheduled", "pending", "placed", "cancelled")


def orders_page(identity, offset=0, limit=20, now=None, statuses=None, query=None):
    """`statuses`: keep only these (empty or None keeps all); `query`: trimmed, case-insensitive
    substring over titles, ids, destination, delivery date, line names and product ids;
    `total` counts every match."""
    if identity["role"] != "approver":
        raise Problem("FORBIDDEN", "Only a buyer session can list orders.", 403)
    statuses = list(statuses or [])
    unknown = sorted(set(statuses) - set(STATUSES))
    if unknown:
        raise Problem(
            "INVALID_ORDER_STATUS",
            f"Unknown order status {', '.join(unknown)}; use {', '.join(STATUSES)}.",
            422,
        )
    query = (query or "").strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise Problem(
            "INVALID_ORDER_QUERY",
            f"The search text is at most {MAX_QUERY_LENGTH} characters.",
            422,
        )
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        context(c, identity)
        params = {
            "buyer": identity["buyer_id"],
            "now": now or clock(),
            "statuses": statuses,
            "q": query,
            "limit": limit + 1,
            "offset": offset,
        }
        rows = c.execute(LIST_SQL, params).fetchall()
        # A page past the end has no row to carry the window total, so count separately then.
        total = rows[0]["total"] if rows else c.execute(COUNT_SQL, params).fetchone()["total"]
    return {
        "items": [_item(row) for row in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
        "total": total,
    }


def _item(row):
    return {
        "status": row["status"],
        "title": row["title"],
        "scheduled_for": row["scheduled_for"].isoformat() if row["scheduled_for"] else None,
        "proposal_id": row["proposal_id"],
        "order_id": row["order_id"],
        "schedule_id": row["schedule_id"],
        "schedule_title": row["schedule_title"],
        "paused": row["paused"],
        "gross_total": row["gross_total"],
        "currency": row["currency"],
        "line_count": row["line_count"],
        "line_names": row["names"][:MAX_LINE_NAMES],
        "cancel_reason": row["cancel_reason"],
        "placed_at": row["placed_at"],
        "updated_at": row["sort_at"],
    }
