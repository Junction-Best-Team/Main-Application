"""Shared helpers for the WS-C characterization tests (second buyer, state counters)."""

import os
from hashlib import md5

from aimo.auth import hasher
from aimo.db import connection, js

OTHER_BUYER = "other"
OTHER_APPROVER = "other-buyer"
OTHER_AGENT = "other-agent"
OTHER_PASSWORD = "other-test-password-only"

COUNTED_TABLES = (
    "proposals",
    "proposal_revisions",
    "approvals",
    "orders",
    "customer_confirmations",
    "audit_events",
    "idempotency",
    "prepare_requests",
    "conversations",
    "conversation_messages",
    "conversation_turns",
    "policies",
)


def add_second_buyer(buyer_id=OTHER_BUYER):
    """Create a second real buyer: policy, approver with password, legacy agent, internal agent."""
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES(%s,'999',1)", (buyer_id,))
        rules = c.execute("SELECT rules FROM policies WHERE buyer_id='demo-hotel'").fetchone()[
            "rules"
        ]
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES(%s,1,%s)", (buyer_id, js(rules))
        )
        c.execute(
            "INSERT INTO identities VALUES(%s,%s,'agent',true,%s,%s)",
            (
                OTHER_AGENT,
                buyer_id,
                "!test-agent-no-bearer-login",
                js({"currency": "EUR", "autonomous_limit": "1500.00"}),
            ),
        )
        c.execute(
            "INSERT INTO identities VALUES(%s,%s,'approver',true,%s,%s)",
            (
                OTHER_APPROVER,
                buyer_id,
                hasher.hash(OTHER_PASSWORD),
                js(
                    {
                        "currency": "EUR",
                        "max_gross": "5000.00",
                        "exceptions": ["spend", "substitution", "overbuy"],
                    }
                ),
            ),
        )
        internal = "internal:" + md5(buyer_id.encode()).hexdigest()
        c.execute(
            "INSERT INTO identities VALUES(%s,%s,'agent',true,'!internal-no-bearer-login',%s)",
            (internal, buyer_id, js({"currency": "EUR", "autonomous_limit": "0"})),
        )
        c.execute("INSERT INTO internal_agents VALUES(%s,%s)", (buyer_id, internal))
        return {
            name: c.execute("SELECT * FROM identities WHERE id=%s", (ident,)).fetchone()
            for name, ident in (
                ("approver", OTHER_APPROVER),
                ("agent", OTHER_AGENT),
                ("internal", internal),
            )
        }


def counts():
    with connection() as c:
        return {
            t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in COUNTED_TABLES
        }


def login_headers(client, username="buyer", password=None):
    password = password or os.environ["DEMO_BUYER_PASSWORD"]
    response = client.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}
