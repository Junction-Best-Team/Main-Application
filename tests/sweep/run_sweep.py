"""Black-box sweep of the buyer-facing HTTP surface against a RUNNING server.

Not a unit test: it uses only the public HTTP API, the way the browser does, so a pass means
"the server is up, authenticates and isolates buyers, enforces CSRF/Origin on every state change and
serves the chat and purchase endpoints end to end". It needs no LLM, no Valio key and no built frontend
(the browser tests cover the served app).

The internal assistant's tools (search_products, get_product, get_purchase_policy,
check_price_and_availability, prepare_order, get_proposal, saved receipts) run only inside a chat
turn driven by a paid LLM provider, so they are exercised by the scripted-provider pytest suites
(tests/test_agent*.py), not here. The sweep checks message CSRF rejection only; it never submits
an authenticated chat turn, even when the target server has an LLM provider configured.

    uv run python tests/sweep/run_sweep.py                 # DEMO_BASE_URL or http://localhost:8000
    uv run python tests/sweep/run_sweep.py --strict        # a SKIP counts as a failure

The buyer password comes from the environment or .env (DEMO_BUYER_PASSWORD) and is never printed.
Exit code: 0 all passed (skips allowed unless --strict), 1 any failure.
"""

import argparse
import os
import sys
from uuid import uuid4

import httpx
from dotenv import load_dotenv


class Skip(Exception):
    """The check could not run for a stated reason. Never reported as a pass."""


def need(condition, message):
    if not condition:
        raise AssertionError(message)


class Sweep:
    def __init__(self, base, password):
        self.base = base.rstrip("/")
        self.password = password
        self.http = httpx.Client(base_url=self.base, timeout=60)
        self.csrf = None
        self.mode = "unknown"
        self.conversation = None
        self.results = []

    # -- helpers -----------------------------------------------------------------------------
    def headers(self, csrf=True):
        h = {"Origin": self.base}
        if csrf and self.csrf:
            h["X-CSRF-Token"] = self.csrf
        return h

    def login(self):
        r = self.http.post(
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

    def sign_in_required(self):
        anonymous = httpx.Client(base_url=self.base, timeout=30)
        for path in (
            "/api/session",
            "/api/conversations",
            "/api/purchases",
            "/api/approvals",
            f"/api/purchases/{uuid4()}",
            "/api/memories",
        ):
            r = anonymous.get(path)
            need(r.status_code == 401, f"GET {path} without a session gave {r.status_code}")
        return "6 endpoints refuse an anonymous caller"

    def login_controls(self):
        bad = httpx.post(
            self.base + "/api/login",
            json={"username": "buyer", "password": "definitely-the-wrong-password"},
            headers={"Origin": self.base},
            timeout=30,
        )
        need(bad.status_code in (401, 403, 429), f"wrong password gave {bad.status_code}")
        foreign = httpx.post(
            self.base + "/api/login",
            json={"username": "buyer", "password": self.password},
            headers={"Origin": "https://evil.example"},
            timeout=30,
        )
        need(foreign.status_code == 403, f"login from a foreign Origin gave {foreign.status_code}")
        self.login()
        r = self.http.get("/api/session")
        need(r.status_code == 200, f"session after login gave {r.status_code}")
        return "wrong password and foreign Origin refused; correct login opens a session"

    def csrf_enforced(self):
        body = {"title": "csrf probe", "idempotency_key": "sweep-csrf-" + str(uuid4())}
        for label, headers in (
            ("no CSRF token", {"Origin": self.base}),
            ("wrong CSRF token", {"Origin": self.base, "X-CSRF-Token": "wrong"}),
            ("foreign Origin", {**self.headers(), "Origin": "https://evil.example"}),
        ):
            r = self.http.post("/api/conversations", json=body, headers=headers)
            need(r.status_code == 403, f"create conversation with {label} gave {r.status_code}")
        listed = self.http.get("/api/conversations").json()["items"]
        need(all(c["title"] != "csrf probe" for c in listed), "a refused request created data")
        return "create refused without token, with a wrong token and from a foreign Origin"

    def conversation_create_and_retry(self):
        key = "sweep-conv-" + str(uuid4())
        body = {"title": "Sweep conversation", "idempotency_key": key}
        first = self.http.post("/api/conversations", json=body, headers=self.headers())
        need(first.status_code == 200, f"create gave {first.status_code}: {first.text[:120]}")
        self.conversation = first.json()["id"]
        again = self.http.post("/api/conversations", json=body, headers=self.headers())
        need(again.status_code == 200 and again.json()["id"] == self.conversation, "retry differed")
        other = self.http.post(
            "/api/conversations",
            json={"title": "A different title", "idempotency_key": key},
            headers=self.headers(),
        )
        need(other.status_code >= 400, f"reusing a key for another body gave {other.status_code}")
        return "created; same key returns the same conversation; a conflicting reuse is refused"

    def conversation_list_and_get(self):
        if not self.conversation:
            raise Skip("no conversation was created")
        listed = self.http.get("/api/conversations", params={"limit": 50}).json()
        need(self.conversation in {c["id"] for c in listed["items"]}, "not in the list")
        got = self.http.get(f"/api/conversations/{self.conversation}")
        need(got.status_code == 200, f"get gave {got.status_code}")
        detail = got.json()
        need(detail["messages"] == [] and detail["purchases"] == [], "new conversation not empty")
        missing = self.http.get(f"/api/conversations/{uuid4()}")
        need(missing.status_code == 404, f"unknown conversation gave {missing.status_code}")
        return "listed; fetched; unknown id is 404"

    def message_csrf_enforced(self):
        if not self.conversation:
            raise Skip("no conversation was created")
        url = f"/api/conversations/{self.conversation}/messages"
        body = {"text": "I need milk.", "idempotency_key": "sweep-msg-" + str(uuid4())}
        refused = self.http.post(url, json=body, headers={"Origin": self.base})
        need(refused.status_code == 403, f"message without CSRF gave {refused.status_code}")
        detail = self.http.get(f"/api/conversations/{self.conversation}").json()
        need(detail["messages"] == [], "a refused message created data")
        return "message without CSRF refused; no chat turn submitted or stored"

    def purchases_and_approvals(self):
        for path in ("/api/purchases", "/api/approvals"):
            r = self.http.get(path, params={"limit": 5})
            need(r.status_code == 200, f"GET {path} gave {r.status_code}")
            need("items" in r.json(), f"{path} has no items list")
        for path in (f"/api/purchases/{uuid4()}", f"/api/approvals/{uuid4()}"):
            r = self.http.get(path)
            need(r.status_code == 404, f"GET {path} gave {r.status_code}")
        return "lists open; unknown proposal and approval are 404"

    def memory_management(self):
        # Personal, uniquely keyed and forgotten at the end: safe on a --live database.
        body = {
            "scope": "self",
            "key": "instruction.sweep_" + uuid4().hex[:12],
            "value": {"text": "Sweep check: keep replies short."},
            "idempotency_key": "sweep-memory-" + str(uuid4()),
        }
        refused = self.http.post("/api/memories", json=body, headers={"Origin": self.base})
        need(refused.status_code == 403, f"memory create without CSRF gave {refused.status_code}")
        created = self.http.post("/api/memories", json=body, headers=self.headers())
        need(created.status_code == 200, f"memory create gave {created.status_code}")
        retry = self.http.post("/api/memories", json=body, headers=self.headers()).json()
        mid = created.json()["memory_id"]
        need(retry["replayed"] and retry["memory_id"] == mid, "memory retry was not replayed")
        stale = {"expected_revision": 9, "value": body["value"], "idempotency_key": str(uuid4())}
        conflict = self.http.put(f"/api/memories/{mid}", json=stale, headers=self.headers())
        need(conflict.status_code == 409, f"stale memory update gave {conflict.status_code}")
        listed = self.http.get("/api/memories", params={"scope": "self", "limit": 50}).json()
        need(any(i["id"] == mid for i in listed["items"]), "saved memory missing from the list")
        forget = {"expected_revision": 1, "idempotency_key": "sweep-forget-" + str(uuid4())}
        gone = self.http.post(f"/api/memories/{mid}/delete", json=forget, headers=self.headers())
        need(gone.status_code == 200 and gone.json()["status"] == "deleted", "forget failed")
        return "memory create/retry/revision conflict/list/forget; CSRF required"

    def confirmation_and_decision_controls(self):
        proposal = str(uuid4())
        confirm = f"/api/purchases/{proposal}/confirm"
        body = {
            "proposal_id": proposal,
            "revision": 1,
            "idempotency_key": "sweep-confirm-" + str(uuid4()),
        }
        no_csrf = self.http.post(confirm, json=body, headers={"Origin": self.base})
        need(no_csrf.status_code == 403, f"confirm without CSRF gave {no_csrf.status_code}")
        unknown = self.http.post(confirm, json=body, headers=self.headers())
        need(unknown.status_code == 404, f"confirm unknown gave {unknown.status_code}")
        decision = f"/api/approvals/{uuid4()}/decision"
        payload = {"revision": 1, "decision": "approve"}
        no_csrf = self.http.post(decision, json=payload, headers={"Origin": self.base})
        need(no_csrf.status_code == 403, f"decision without CSRF gave {no_csrf.status_code}")
        unknown = self.http.post(decision, json=payload, headers=self.headers())
        need(unknown.status_code == 404, f"decision on unknown gave {unknown.status_code}")
        return "confirm and decide need CSRF; unknown proposals are refused"

    def logout_closes_the_session(self):
        r = self.http.post("/api/logout", headers=self.headers())
        need(r.status_code == 204, f"logout gave {r.status_code}")
        after = self.http.get("/api/conversations")
        need(after.status_code == 401, f"conversations after logout gave {after.status_code}")
        self.csrf = None
        return "session ends; protected endpoints refuse the old cookie"

    def all(self):
        for name, fn in [
            ("health/ready", self.health),
            ("sign-in required", self.sign_in_required),
            ("login controls", self.login_controls),
            ("CSRF and Origin enforced", self.csrf_enforced),
            ("create conversation (+ retry)", self.conversation_create_and_retry),
            ("list and get conversation", self.conversation_list_and_get),
            ("message CSRF enforced", self.message_csrf_enforced),
            ("purchases and approvals", self.purchases_and_approvals),
            ("memory management", self.memory_management),
            ("confirm and decide controls", self.confirmation_and_decision_controls),
            ("logout", self.logout_closes_the_session),
        ]:
            self.run(name, fn)


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default=os.getenv("DEMO_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--strict", action="store_true", help="count SKIP as failure")
    args = ap.parse_args()
    if not os.getenv("DEMO_BUYER_PASSWORD"):
        sys.exit("DEMO_BUYER_PASSWORD is not set (see .env.example)")
    sweep = Sweep(args.base_url, os.environ["DEMO_BUYER_PASSWORD"])
    sweep.all()
    width = max(len(n) for n, _, _ in sweep.results)
    for name, status, detail in sweep.results:
        print(f"{status:4}  {name:<{width}}  {detail}")
    counts = {s: sum(1 for _, x, _ in sweep.results if x == s) for s in ("PASS", "SKIP", "FAIL")}
    print(f"\n{counts['PASS']} passed, {counts['SKIP']} skipped, {counts['FAIL']} failed")
    print(f"configured upstream mode: {sweep.mode.upper()} (HTTP sweep does not query the supplier)")
    bad = counts["FAIL"] or (args.strict and counts["SKIP"])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
