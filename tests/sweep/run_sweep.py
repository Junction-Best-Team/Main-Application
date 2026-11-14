"""Black-box sweep of the eight agent tools against a RUNNING server.

Not a unit test: it uses only the public HTTP/MCP surface, the way an external agent would, so a
pass means "each tool works end to end". Works in fixture mode (no API key) and in live mode;
the mode actually used is read from the server and printed, never assumed.

    uv run python tests/sweep/run_sweep.py                 # DEMO_BASE_URL or http://localhost:8000
    uv run python tests/sweep/run_sweep.py --strict        # a SKIP counts as a failure

Credentials come from the environment or .env (DEMO_AGENT_TOKEN, DEMO_BUYER_PASSWORD) and are
never printed. Exit code: 0 all passed (skips allowed unless --strict), 1 any failure.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import date, timedelta
from uuid import uuid4

import httpx
from dotenv import load_dotenv

TOOLS = {
    "search_products",
    "get_product",
    "get_purchase_policy",
    "check_price_and_availability",
    "prepare_order",
    "get_proposal",
    "commit_order",
    "get_order",
}
OUTCOMES = {"ready_to_commit", "approval_required", "denied", "needs_resolution"}


class Skip(Exception):
    """The check could not run for a stated reason. Never reported as a pass."""


def need(condition, message):
    if not condition:
        raise AssertionError(message)


class Sweep:
    def __init__(self, base, token, password, product, substitute):
        self.base = base.rstrip("/")
        self.password = password
        self.product, self.substitute = product, substitute
        self.agent = httpx.Client(
            base_url=self.base, headers={"Authorization": "Bearer " + token}, timeout=90
        )
        self.buyer = httpx.Client(base_url=self.base, timeout=30)
        self.csrf = None
        self.mode = "unknown"
        self.date = str(date.today() + timedelta(days=2))
        self.proposal = None
        self.receipt = None
        self.results = []

    # -- helpers -----------------------------------------------------------------------------
    def get(self, path, **kw):
        return self.agent.get("/api/agent/" + path, **kw)

    def post(self, path, body):
        return self.agent.post("/api/agent/" + path, json=body)

    def purchase(self, **over):
        body = {
            "request_id": "sweep-" + str(uuid4())[:8],
            "destination": "hotel-helsinki",
            "delivery_date": self.date,
            "requirements": {"lactose_free": True},
            "lines": [{"product_id": self.product, "amount": "10", "unit": "L"}],
        }
        return body | over

    def buyer_login(self):
        if self.csrf:
            return
        r = self.buyer.post(
            "/api/login",
            json={"username": "buyer", "password": self.password},
            headers={"Origin": self.base},
        )
        need(r.status_code == 200, f"buyer login failed: HTTP {r.status_code}")
        self.csrf = r.json()["csrf_token"]

    def run(self, name, fn):
        try:
            detail = fn() or ""
            self.results.append((name, "PASS", detail))
        except Skip as e:
            self.results.append((name, "SKIP", str(e)))
        except Exception as e:  # noqa: BLE001 - report every failure kind, do not crash the sweep
            self.results.append((name, "FAIL", f"{type(e).__name__}: {e}"[:300]))

    # -- checks ------------------------------------------------------------------------------
    def health(self):
        r = httpx.get(self.base + "/health/ready", timeout=60)
        need(r.status_code == 200, f"/health/ready returned {r.status_code}: {r.text[:120]}")
        self.mode = r.json()["upstream_mode"]
        return f"upstream_mode={self.mode}"

    def auth_required(self):
        r = httpx.get(self.base + "/api/agent/purchase-policy", timeout=30)
        need(r.status_code in (401, 403), f"no token should be refused, got {r.status_code}")
        r = httpx.get(
            self.base + "/api/agent/purchase-policy",
            headers={"Authorization": "Bearer wrong-token-0000000000000000"},
            timeout=30,
        )
        need(r.status_code in (401, 403), f"bad token should be refused, got {r.status_code}")

    def get_purchase_policy(self):
        r = self.get("purchase-policy")
        need(r.status_code == 200, f"HTTP {r.status_code}")
        p = r.json()
        for k in ("buyer_id", "agent_id", "policy_version", "rules"):
            need(k in p, f"missing {k}")
        need(p["editable"] is False, "policy must be read-only to the agent")
        return f"policy v{p['policy_version']}, limit {p['rules']['autonomous_limit']}"

    def search_exact_id(self):
        r = self.post(
            "search_products",
            {"query": self.product, "requirements": {"lactose_free": True}, "limit": 5},
        )
        need(r.status_code == 200, f"HTTP {r.status_code}: {r.text[:120]}")
        ids = [p["id"] for p in r.json()["products"]]
        need(ids and ids[0] == self.product, f"exact id not first: {ids}")
        return f"top hit {ids[0]}"

    def search_text(self):
        r = self.post(
            "search_products",
            {"query": "lactose-free milk", "requirements": {"lactose_free": True}, "limit": 5},
        )
        need(r.status_code == 200, f"HTTP {r.status_code}: {r.text[:120]}")
        found = r.json()["products"]
        need(len(found) >= 1, "no results for a basic lactose-free milk query")
        return f"{len(found)} results"

    def search_rejects_unsupported_filter(self):
        r = self.post("search_products", {"query": "milk", "requirements": {"organic": True}})
        need(r.status_code in (400, 422), f"unsupported filter must be rejected, got {r.status_code}")

    def get_product(self):
        r = self.get("products/" + self.product)
        need(r.status_code == 200, f"HTTP {r.status_code}")
        need(self.product in json.dumps(r.json()), "response does not mention the product id")
        r = self.get("products/does-not-exist-0")
        need(r.status_code == 404, f"unknown product should be 404, got {r.status_code}")

    def check_price_and_availability(self):
        r = self.post(
            "check_price_and_availability",
            {"product_ids": [self.product, self.substitute], "delivery_date": self.date},
        )
        need(r.status_code == 200, f"HTTP {r.status_code}: {r.text[:160]}")
        body = r.json()
        need(body["mode"] in ("live", "fixture"), f"evidence not labelled: {body.get('mode')}")
        need(set(body["products"]) == {self.product, self.substitute}, "missing product evidence")
        return f"evidence mode={body['mode']}"

    def prepare_order(self):
        r = self.post("prepare_order", self.purchase())
        need(r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}")
        p = r.json()
        need(p["policy_outcome"] in OUTCOMES, f"unknown outcome {p['policy_outcome']}")
        need(p["revision"] >= 1 and p["proposal_id"], "proposal missing id/revision")
        need(p["next_action"]["type"], "no next_action")
        self.proposal = p
        return f"outcome={p['policy_outcome']}, next={p['next_action']['type']}"

    def get_proposal(self):
        need(self.proposal, "no proposal (prepare_order failed)")
        r = self.get("proposals/" + self.proposal["proposal_id"])
        need(r.status_code == 200, f"HTTP {r.status_code}")
        p = r.json()
        need(p["proposal_id"] == self.proposal["proposal_id"], "wrong proposal returned")
        need(p["revision"] == self.proposal["revision"], "revision changed unexpectedly")

    def commit_gate_blocks_denied(self):
        denied = self.post("prepare_order", self.purchase(budget_gross="1")).json()
        need(denied["policy_outcome"] == "denied", f"hard budget not denied: {denied}")
        r = self.post(
            "commit_order",
            {
                "proposal_id": denied["proposal_id"],
                "revision": denied["revision"],
                "idempotency_key": "sweep-" + str(uuid4()),
            },
        )
        need(r.status_code >= 400, "a denied proposal must not commit")
        return f"denied proposal refused with HTTP {r.status_code}"

    def commit_order(self):
        need(self.proposal, "no proposal (prepare_order failed)")
        p = self.proposal
        if p["policy_outcome"] == "approval_required":
            self.buyer_login()
            approval_id = p["approval_id"]
            r = self.buyer.post(
                f"/api/approvals/{approval_id}/decision",
                json={"revision": p["revision"], "decision": "approve"},
                headers={"X-CSRF-Token": self.csrf, "Origin": self.base},
            )
            need(r.status_code == 200, f"buyer approval failed: HTTP {r.status_code}")
        elif p["policy_outcome"] != "ready_to_commit":
            reasons = [x["code"] for x in p.get("reasons", [])]
            raise Skip(f"proposal is {p['policy_outcome']} ({reasons}); nothing committable")
        body = {
            "proposal_id": p["proposal_id"],
            "revision": p["revision"],
            "idempotency_key": "sweep-" + str(uuid4()),
        }
        first = self.post("commit_order", body)
        need(first.status_code == 200, f"HTTP {first.status_code}: {first.text[:200]}")
        need(first.json()["status"] == "accepted_mock", f"unexpected status {first.json()}")
        again = self.post("commit_order", body)
        need(again.json() == first.json(), "retry with the same key must return the same receipt")
        self.receipt = first.json()
        return "accepted_mock, identical receipt on retry"

    def approval_path(self):
        """Exception flow: split purchase needs the buyer. Agent cannot commit until they decide."""
        lines = [
            {"product_id": self.product, "amount": "600", "unit": "L"},
            {
                "product_id": self.substitute,
                "amount": "400",
                "unit": "L",
                "substitutes_for": self.product,
            },
        ]
        r = self.post("prepare_order", self.purchase(lines=lines))
        need(r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}")
        p = r.json()
        if p["policy_outcome"] != "approval_required":
            reasons = [x["code"] for x in p["reasons"]]
            raise Skip(f"split purchase is {p['policy_outcome']} ({reasons}); no approval to test")
        body = {
            "proposal_id": p["proposal_id"],
            "revision": p["revision"],
            "idempotency_key": "sweep-" + str(uuid4()),
        }
        early = self.post("commit_order", body)
        need(early.status_code >= 400, "commit must be refused before the buyer decides")
        self.buyer_login()
        inbox = self.buyer.get("/api/approvals")
        need(inbox.status_code == 200, f"inbox HTTP {inbox.status_code}")
        need(
            p["proposal_id"] in [i["proposal_id"] for i in inbox.json()["items"]],
            "pending proposal missing from the buyer inbox",
        )
        d = self.buyer.post(
            f"/api/approvals/{p['approval_id']}/decision",
            json={"revision": p["revision"], "decision": "approve"},
            headers={"X-CSRF-Token": self.csrf, "Origin": self.base},
        )
        need(d.status_code == 200, f"buyer decision HTTP {d.status_code}")
        done = self.post("commit_order", body)
        need(done.status_code == 200, f"commit after approval HTTP {done.status_code}")
        return "refused before approval; in inbox; committed after buyer approval"

    def get_order(self):
        if not self.receipt:
            raise Skip("no order was committed")
        r = self.get("orders/" + self.receipt["order_id"])
        need(r.status_code == 200, f"HTTP {r.status_code}")
        need(r.json() == self.receipt, "get_order differs from the commit receipt")
        r = self.get("orders/" + str(uuid4()))
        need(r.status_code == 404, f"unknown order should be 404, got {r.status_code}")

    def mcp_tools(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def go():
            async with httpx.AsyncClient(headers=dict(self.agent.headers)) as http:
                async with streamable_http_client(self.base + "/mcp/", http_client=http) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = {t.name for t in (await session.list_tools()).tools}
                        res = await session.call_tool("get_purchase_policy", {})
                        return listed, res

        listed, res = asyncio.run(go())
        need(listed == TOOLS, f"tool set differs: {sorted(listed ^ TOOLS)}")
        need(not res.isError, "MCP get_purchase_policy errored")
        return "8 tools discovered; policy callable"

    def all(self):
        for name, fn in [
            ("health/ready", self.health),
            ("auth required", self.auth_required),
            ("get_purchase_policy", self.get_purchase_policy),
            ("search_products (exact id)", self.search_exact_id),
            ("search_products (text)", self.search_text),
            ("search_products (rejects bad filter)", self.search_rejects_unsupported_filter),
            ("get_product", self.get_product),
            ("check_price_and_availability", self.check_price_and_availability),
            ("prepare_order", self.prepare_order),
            ("get_proposal", self.get_proposal),
            ("commit gate (denied cannot commit)", self.commit_gate_blocks_denied),
            ("commit_order (+ approval, retry)", self.commit_order),
            ("approval path (inbox, then commit)", self.approval_path),
            ("get_order", self.get_order),
            ("MCP tool discovery", self.mcp_tools),
        ]:
            self.run(name, fn)


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default=os.getenv("DEMO_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--product", default="464306", help="lactose-free milk used for the purchase")
    ap.add_argument("--substitute", default="464398")
    ap.add_argument("--strict", action="store_true", help="count SKIP as failure")
    args = ap.parse_args()
    for var in ("DEMO_AGENT_TOKEN", "DEMO_BUYER_PASSWORD"):
        if not os.getenv(var):
            sys.exit(f"{var} is not set (see .env.example)")
    sweep = Sweep(
        args.base_url,
        os.environ["DEMO_AGENT_TOKEN"],
        os.environ["DEMO_BUYER_PASSWORD"],
        args.product,
        args.substitute,
    )
    sweep.all()
    width = max(len(n) for n, _, _ in sweep.results)
    for name, status, detail in sweep.results:
        print(f"{status:4}  {name:<{width}}  {detail}")
    counts = {s: sum(1 for _, x, _ in sweep.results if x == s) for s in ("PASS", "SKIP", "FAIL")}
    print(f"\n{counts['PASS']} passed, {counts['SKIP']} skipped, {counts['FAIL']} failed")
    print(f"upstream commercial data in this run: {sweep.mode.upper()}")
    bad = counts["FAIL"] or (args.strict and counts["SKIP"])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
