"""HTTP reference client, not a purchasing agent. Buyer decisions happen in the inbox."""

import argparse
import json
import os
from datetime import date, timedelta
from uuid import uuid4

import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", help="Proposal ID approved independently in the buyer inbox")
    parser.add_argument("--key", help="Stable idempotency key for a retry")
    args = parser.parse_args()
    base = os.getenv("DEMO_BASE_URL", "http://localhost:8000")
    with httpx.Client(
        base_url=base,
        headers={"Authorization": "Bearer " + os.environ["DEMO_AGENT_TOKEN"]},
        timeout=60,
    ) as client:

        def get(path):
            r = client.get("/api/agent/" + path)
            r.raise_for_status()
            return r.json()

        def post(path, body):
            r = client.post("/api/agent/" + path, json=body)
            r.raise_for_status()
            return r.json()

        def commit(p, key=None):
            body = {
                "proposal_id": p["proposal_id"],
                "revision": p["revision"],
                "idempotency_key": key or str(uuid4()),
            }
            first = post("commit_order", body)
            if first.get("status") == "accepted_mock":
                assert post("commit_order", body) == first
            return first

        if args.resume:
            p = get("proposals/" + args.resume)
            if p["next_action"]["type"] != "commit":
                print(
                    json.dumps(
                        {
                            "proposal_id": args.resume,
                            "approval_status": p["approval_status"],
                            "next_action": p["next_action"],
                        },
                        indent=2,
                    )
                )
            else:
                print(json.dumps(commit(p, args.key), indent=2))
            return
        policy = get("purchase-policy")
        print(
            json.dumps(
                {"policy_version": policy["policy_version"], "rules": policy["rules"]}, indent=2
            )
        )
        body = {
            "idempotency_key": str(uuid4()),
            "request_id": "Autonomous breakfast " + str(uuid4())[:8],
            "destination": "hotel-helsinki",
            "delivery_date": str(date.today() + timedelta(days=2)),
            "requirements": {"lactose_free": True},
            "lines": [{"product_id": "464306", "amount": "10", "unit": "L"}],
        }
        p = post("prepare_order", body)
        assert p["policy_outcome"] == "ready_to_commit", p["reasons"]
        print(json.dumps({"autonomous_receipt": commit(p)}, indent=2))
        denied = post(
            "prepare_order", body | {"budget_gross": "1", "idempotency_key": str(uuid4())}
        )
        shortage = post(
            "prepare_order",
            body
            | {
                "idempotency_key": str(uuid4()),
                "lines": [{"product_id": "464306", "amount": "1000", "unit": "L"}],
            },
        )
        assert (
            denied["policy_outcome"] == "denied"
            and shortage["policy_outcome"] == "needs_resolution"
        )
        mission = post(
            "prepare_order",
            body
            | {
                "idempotency_key": str(uuid4()),
                "request_id": "Mission breakfast " + str(uuid4())[:8],
                "lines": [
                    {"product_id": "464306", "amount": "600", "unit": "L"},
                    {
                        "product_id": "464398",
                        "amount": "400",
                        "unit": "L",
                        "substitutes_for": "464306",
                    },
                ],
            },
        )
        assert mission["policy_outcome"] == "approval_required"
        print(
            json.dumps(
                {
                    "denied_reason": denied["reasons"],
                    "unresolved_reason": shortage["reasons"],
                    "mission_proposal": mission["proposal_id"],
                    "buyer_inbox": base + "/approvals",
                    "next_action": mission["next_action"],
                    "resume_command": "uv run python scripts/demo.py --resume "
                    + mission["proposal_id"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
