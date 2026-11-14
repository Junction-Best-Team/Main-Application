"""Explicit local-container test: persist buyer decision/session across process restart."""

import argparse
import json
import os
import subprocess
import time
from datetime import date, timedelta
from uuid import uuid4

import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--container", required=True, help="Dedicated local verification container to restart"
    )
    parser.add_argument("--base-url", default="http://localhost:8001")
    args = parser.parse_args()
    with (
        httpx.Client(
            base_url=args.base_url,
            timeout=30,
            headers={"Authorization": "Bearer " + os.environ["DEMO_AGENT_TOKEN"]},
        ) as agent,
        httpx.Client(
            base_url=args.base_url, timeout=30, headers={"Origin": args.base_url}
        ) as buyer,
    ):
        prepared = agent.post(
            "/api/agent/prepare_order",
            json={
                "request_id": "Restart verification",
                "destination": "hotel-helsinki",
                "delivery_date": str(date.today() + timedelta(days=2)),
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
        prepared.raise_for_status()
        p = prepared.json()
        assert p["policy_outcome"] == "approval_required"
        login = buyer.post(
            "/api/login", json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]}
        )
        login.raise_for_status()
        approval = buyer.post(
            "/api/approvals/" + p["approval_id"] + "/decision",
            json={"revision": p["revision"], "decision": "approve"},
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )
        approval.raise_for_status()
        assert approval.json()["order_status"] == "not_placed"
        subprocess.run(["docker", "restart", args.container], check=True, capture_output=True)
        for _ in range(20):
            try:
                if agent.get("/health/ready").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Container failed to become ready after restart")
        assert buyer.get("/api/session").status_code == 200
        resumed = agent.get("/api/agent/proposals/" + p["proposal_id"])
        resumed.raise_for_status()
        assert resumed.json()["approval_status"] == "approved"
        payload = {
            "proposal_id": p["proposal_id"],
            "revision": p["revision"],
            "idempotency_key": str(uuid4()),
        }
        receipt = agent.post("/api/agent/commit_order", json=payload)
        receipt.raise_for_status()
        assert receipt.json()["order_status"] == "accepted_mock"
        assert receipt.json()["next_action"]["type"] == "complete"
        assert agent.post("/api/agent/commit_order", json=payload).json() == receipt.json()
        print(
            json.dumps(
                {
                    "session_survived_restart": True,
                    "approval_survived_restart": True,
                    "agent_resumed": True,
                    "mock_order_created_once": True,
                }
            )
        )


if __name__ == "__main__":
    main()
