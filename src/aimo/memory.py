"""Explicitly saved buyer-shared and personal memory: one storage/validation service.

Both the assistant's two memory tools and the browser API call these functions.
The caller supplies an :class:`Actor` built by the server, never by the model:
the browser session identity, or the persisted turn's ``requested_by`` human plus
the claimed turn attempt. Memory is preference data. It grants no purchasing
authority, changes no policy and replaces no evidence or customer confirmation.

Writes take the buyer lock, then (for chat) a share lock on the turn row, then the
memory rows. The turn check fences superseded worker attempts: a reclaimed lease
changes ``attempt`` and an old attempt can no longer write. Mutations use
optimistic revisions and a durable per-actor idempotency key.
"""

import json
import re
from dataclasses import dataclass
from uuid import uuid4

from pydantic import ValidationError

from aimo.db import Problem, connection, fingerprint, js, now
from aimo.memory_schemas import MemoryChange, MemorySearch, kind_of, value_model

# Documented limits (docs/memory.md).
MAX_PER_OWNER = 50  # per person (personal) and per buyer (shared)
CONTEXT_MAX_ITEMS = 20
CONTEXT_MAX_CHARS = 6000
SEARCH_WORDS = 20

# Deterministic screening for obvious secrets/payment data. It is a floor, not a
# complete classifier; memory never stores credentials, payment details or authority.
SENSITIVE = (
    re.compile(r"(?:\d[ -]?){12,19}"),
    re.compile(r"\bFI\d{2}\s?\d{4}", re.IGNORECASE),
    re.compile(
        r"\b(?:password|passcode|passwd|salasana|api[ _-]?key|secret|token|iban|cvv|cvc|"
        r"pin[ -]?code|credit[ -]?card|luottokortti|bearer)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class Actor:
    """Server-resolved requester. Chat actors also carry the claimed turn attempt."""

    identity_id: str
    buyer_id: str
    turn_id: str | None = None
    attempt: str | None = None
    conversation_id: str | None = None

    @property
    def chat(self):
        return self.turn_id is not None


def browser_actor(identity):
    return Actor(identity_id=identity["id"], buyer_id=identity["buyer_id"])


def chat_actor(agent_identity):
    """Trusted context set by conversations.execute_turn; never from tool arguments."""
    if agent_identity.get("_memory_unavailable"):
        raise Problem(
            "MEMORY_AUTHOR_MISMATCH",
            "Another user sent this message, so saved memory is not used in this retry. "
            "The sender can retry it, or you can send your own message.",
            403,
        )
    fields = ("_requested_by", "_turn_id", "_attempt", "_conversation_id")
    if any(not agent_identity.get(f) for f in fields):
        raise Problem(
            "MEMORY_CONTEXT_REQUIRED",
            "Saved memory is available only in an authenticated customer chat turn.",
            422,
        )
    return Actor(
        identity_id=agent_identity["_requested_by"],
        buyer_id=agent_identity["buyer_id"],
        turn_id=agent_identity["_turn_id"],
        attempt=agent_identity["_attempt"],
        conversation_id=agent_identity["_conversation_id"],
    )


def _human(c, actor):
    """Recheck the human on every call: active approver of this buyer, current role only."""
    row = c.execute(
        "SELECT id FROM identities WHERE id=%s AND buyer_id=%s AND active AND role='approver'",
        (actor.identity_id, actor.buyer_id),
    ).fetchone()
    if not row:
        raise Problem(
            "AUTHORITY_REVOKED", "The requesting customer is inactive or not a buyer user.", 403
        )


def _fence(c, actor):
    """Hold the current attempt for this transaction; return the turn's own user message."""
    turn = c.execute(
        """SELECT t.* FROM conversation_turns t JOIN conversations c ON c.id=t.conversation_id
        WHERE t.id=%s AND t.conversation_id=%s AND c.buyer_id=%s FOR SHARE OF t""",
        (actor.turn_id, actor.conversation_id, actor.buyer_id),
    ).fetchone()
    if (
        not turn
        or str(turn["attempt"]) != str(actor.attempt)
        or turn["state"] != "running"
        or turn["lease_until"] <= now()
        or turn["requested_by"] != actor.identity_id
    ):
        raise Problem("TURN_REPLACED", "This response was replaced; reload the conversation.")
    if turn["submitted_by"] != actor.identity_id:
        # Defence in depth: only the message's author owns what it asks to remember.
        raise Problem(
            "MEMORY_AUTHOR_MISMATCH", "Only the sender of this message can change memory.", 403
        )
    message = c.execute(
        "SELECT id FROM conversation_messages WHERE turn_id=%s AND role='user'", (turn["id"],)
    ).fetchone()
    return turn["conversation_id"], message["id"]


def _validate(key, value, description):
    try:
        clean = value_model(key).model_validate(value).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "value" for e in exc.errors()})
        raise Problem(
            "MEMORY_VALUE_INVALID",
            f"The value does not match the {key} format ({', '.join(fields)}).",
            422,
        ) from None
    if len(json.dumps(clean, ensure_ascii=False).encode()) > 1024:
        raise Problem("MEMORY_VALUE_INVALID", "The memory value is too large.", 422)
    texts = [str(v) for v in clean.values() if not isinstance(v, (bool, int))]
    texts += [str(i) for v in clean.values() if isinstance(v, list) for i in v]
    if description:
        texts.append(description)
    if any(p.search(t) for t in texts for p in SENSITIVE):
        raise Problem(
            "MEMORY_SENSITIVE_DATA",
            "Memory cannot store credentials, secrets, account or payment details.",
            422,
        )
    return clean


def item(row):
    return {
        k: row[k]
        for k in (
            "id",
            "scope",
            "owner_id",
            "kind",
            "key",
            "value",
            "description",
            "revision",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "source_conversation_id",
            "source_message_id",
        )
    }


def model_view(row):
    """Compact view for the conversational model: identifiers, revision and content only."""
    return {
        "id": str(row["id"]),
        "scope": "buyer (shared)" if row["scope"] == "buyer" else "personal (you)",
        "key": row["key"],
        "value": row["value"],
        "description": row["description"],
        "revision": row["revision"],
        "updated_at": row["updated_at"].date().isoformat(),
    }


def _tsquery(text):
    words = list(dict.fromkeys(w for w in re.findall(r"[^\W_]+", (text or "").casefold())))
    words = [w for w in words if len(w) >= 2][:SEARCH_WORDS]
    return " | ".join(w + ":*" for w in words) or None


ACCESSIBLE = "buyer_id=%s AND (scope='buyer' OR owner_id=%s)"
SELECT = "SELECT *, {rank} AS rank FROM memories WHERE " + ACCESSIBLE


def _rank(query):
    return "ts_rank(search, to_tsquery('simple', %s))" if query else "0::real"


def search(actor, request: MemorySearch):
    query = _tsquery(request.query) if request.query else None
    if request.query and not query:
        return {"items": [], "next_offset": None}
    params = ([query] if query else []) + [actor.buyer_id, actor.identity_id]
    sql = SELECT.format(rank=_rank(query))
    if request.scope != "all":
        sql += " AND scope=%s"
        params.append("buyer" if request.scope == "buyer" else "user")
    if request.kind:
        sql += " AND kind=%s"
        params.append(request.kind)
    if query:
        sql += " AND search @@ to_tsquery('simple', %s)"
        params.append(query)
    sql += " ORDER BY rank DESC, updated_at DESC, id LIMIT %s OFFSET %s"
    params += [request.limit + 1, request.offset]
    with connection() as c:
        _human(c, actor)
        rows = c.execute(sql, params).fetchall()
    return {
        "items": [item(r) for r in rows[: request.limit]],
        "next_offset": request.offset + request.limit if len(rows) > request.limit else None,
    }


def get(actor, memory_id):
    with connection() as c:
        _human(c, actor)
        row = c.execute(
            "SELECT * FROM memories WHERE id=%s AND " + ACCESSIBLE,
            (memory_id, actor.buyer_id, actor.identity_id),
        ).fetchone()
    if not row:
        raise Problem("MEMORY_NOT_FOUND", "Memory not found.", 404)
    return item(row)


def _priority(row):
    """Deterministic: fixed facts, then text matches, instructions, other preferences."""
    if kind_of(row["key"]) == "default" or row["key"] == "preference.reply_style":
        tier = 0
    elif row["rank"] > 0:
        tier = 1
    elif row["kind"] == "instruction":
        tier = 2
    else:
        tier = 3
    return (
        tier,
        0 if row["scope"] == "user" else 1,
        -row["rank"],
        -row["updated_at"].timestamp(),
        str(row["id"]),
    )


def context(actor, latest_message):
    """Bounded automatic context for one turn: this buyer's shared and this user's items."""
    query = _tsquery(latest_message)
    params = ([query] if query else []) + [actor.buyer_id, actor.identity_id]
    with connection() as c:
        _human(c, actor)
        # Bounded by MAX_PER_OWNER for the shared and the personal owner.
        rows = c.execute(SELECT.format(rank=_rank(query)), params).fetchall()
    chosen, size = [], 0
    for row in sorted(rows, key=_priority):
        view = model_view(row)
        length = len(json.dumps(view, ensure_ascii=False))
        if len(chosen) >= CONTEXT_MAX_ITEMS or size + length > CONTEXT_MAX_CHARS:
            break
        chosen.append(view)
        size += length
    return {"items": chosen, "total": len(rows), "omitted": len(rows) - len(chosen)}


def _owned_row(c, actor, memory_id):
    row = c.execute(
        "SELECT * FROM memories WHERE id=%s AND " + ACCESSIBLE + " FOR UPDATE",
        (memory_id, actor.buyer_id, actor.identity_id),
    ).fetchone()
    if not row:
        raise Problem("MEMORY_NOT_FOUND", "Memory not found.", 404)
    return row


def _check_revision(row, expected):
    if row["revision"] != expected:
        raise Problem(
            "MEMORY_REVISION_CONFLICT",
            f"This memory changed; its current revision is {row['revision']}. "
            "Reload it and confirm the change again.",
        )


def request_hash(change: MemoryChange):
    # The expected revision is excluded: a retried chat attempt re-reads the item after
    # its own earlier write, and the stable key already names the target.
    return fingerprint(
        change.model_dump(mode="json", exclude={"expected_revision"}) | {"v": "memory-1"}
    )


def chat_key(actor, change: MemoryChange):
    """Stable across retried attempts of the same persisted turn, unlike tool-call IDs."""
    target = f"{change.scope}:{change.key}" if change.action == "save" else str(change.memory_id)
    return f"chat:{actor.turn_id}:{change.action}:{target}"


def _result(status, memory_id, revision, row=None, replayed=False):
    return {
        "status": status,
        "memory_id": memory_id,
        "revision": revision,
        "memory": item(row) if row else None,
        "replayed": replayed,
    }


def _replayed(c, actor, key, digest):
    """The saved result of an earlier identical write, without needing its live row.

    A write whose item has since been forgotten replays as ``deleted``; it is never
    recreated, and a forgotten write's cleared hash cannot be compared.
    """
    old = c.execute(
        "SELECT * FROM memory_mutations WHERE buyer_id=%s AND actor_id=%s AND key=%s",
        (actor.buyer_id, actor.identity_id, key),
    ).fetchone()
    if not old:
        return None
    if old["request_hash"] is not None and old["request_hash"] != digest:
        raise Problem(
            "IDEMPOTENCY_CONFLICT",
            "This request key already changed memory differently"
            + (" in this turn; ask in a new message." if actor.chat else "."),
        )
    row = c.execute(
        "SELECT * FROM memories WHERE id=%s AND " + ACCESSIBLE,
        (old["memory_id"], actor.buyer_id, actor.identity_id),
    ).fetchone()
    status = old["outcome"] if row is not None else "deleted"
    return _result(status, old["memory_id"], old["result_revision"], row, True)


def replay(actor, change: MemoryChange):
    """For a retried chat attempt: the earlier result of this exact write, or None.

    Checked before the live item is read, so a replayed delete (or a write to an item
    forgotten since) reports its saved outcome instead of MEMORY_NOT_FOUND.
    """
    with connection() as c:
        _human(c, actor)
        _fence(c, actor)
        return _replayed(c, actor, chat_key(actor, change), request_hash(change))


def mutate(actor, change: MemoryChange, idempotency_key=None):
    key = chat_key(actor, change) if actor.chat else "api:" + (idempotency_key or "")
    if not actor.chat and not idempotency_key:
        raise Problem("IDEMPOTENCY_KEY_REQUIRED", "Supply an idempotency key.", 422)
    digest = request_hash(change)
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (actor.buyer_id,))
        _human(c, actor)
        source = _fence(c, actor) if actor.chat else (None, None)
        earlier = _replayed(c, actor, key, digest)
        if earlier:
            return earlier
        if change.action == "save":
            outcome, row = _save(c, actor, change, source)
        elif change.action == "update":
            outcome, row = _update(c, actor, change, source)
        else:
            outcome, row = _delete(c, actor, change)
        c.execute(
            """INSERT INTO memory_mutations
            (buyer_id,actor_id,key,request_hash,action,outcome,memory_id,result_revision,turn_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                actor.buyer_id,
                actor.identity_id,
                key,
                digest,
                change.action,
                outcome,
                row["id"],
                row["revision"],
                actor.turn_id,
            ),
        )
    return _result(outcome, row["id"], row["revision"], None if outcome == "deleted" else row)


def _save(c, actor, change, source):
    scope = "buyer" if change.scope == "buyer" else "user"
    owner = actor.identity_id if scope == "user" else None
    value = _validate(change.key, change.value, change.description)
    existing = c.execute(
        """SELECT id,revision FROM memories WHERE buyer_id=%s AND scope=%s
        AND owner_id IS NOT DISTINCT FROM %s AND key=%s""",
        (actor.buyer_id, scope, owner, change.key),
    ).fetchone()
    if existing:
        raise Problem(
            "MEMORY_EXISTS",
            f"A {change.scope} memory with key {change.key} already exists "
            f"(id {existing['id']}, revision {existing['revision']}). Update that exact item "
            "with its expected revision, or ask the customer which item to change.",
        )
    count = c.execute(
        """SELECT count(*) AS n FROM memories WHERE buyer_id=%s AND scope=%s
        AND owner_id IS NOT DISTINCT FROM %s""",
        (actor.buyer_id, scope, owner),
    ).fetchone()["n"]
    if count >= MAX_PER_OWNER:
        raise Problem(
            "MEMORY_LIMIT",
            f"At most {MAX_PER_OWNER} {change.scope} memories can be saved; forget one first.",
        )
    row = c.execute(
        """INSERT INTO memories(id,buyer_id,scope,owner_id,kind,key,value,description,
        created_by,updated_by,source_conversation_id,source_message_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (
            uuid4(),
            actor.buyer_id,
            scope,
            owner,
            kind_of(change.key),
            change.key,
            js(value),
            change.description,
            actor.identity_id,
            actor.identity_id,
            *source,
        ),
    ).fetchone()
    return "created", row


def _update(c, actor, change, source):
    row = _owned_row(c, actor, change.memory_id)
    _check_revision(row, change.expected_revision)
    value = _validate(row["key"], change.value, change.description)
    description = change.description if change.description is not None else row["description"]
    if value == row["value"] and description == row["description"]:
        return "unchanged", row
    row = c.execute(
        """UPDATE memories SET value=%s,description=%s,revision=revision+1,updated_at=%s,
        updated_by=%s,source_conversation_id=%s,source_message_id=%s
        WHERE id=%s RETURNING *""",
        (js(value), description, now(), actor.identity_id, *source, row["id"]),
    ).fetchone()
    return "updated", row


def _delete(c, actor, change):
    row = _owned_row(c, actor, change.memory_id)
    _check_revision(row, change.expected_revision)
    c.execute("DELETE FROM memories WHERE id=%s", (row["id"],))
    # Forget leaves no hidden copy: clear content fingerprints of earlier writes.
    c.execute(
        "UPDATE memory_mutations SET request_hash=NULL WHERE memory_id=%s AND action!='delete'",
        (row["id"],),
    )
    return "deleted", row
