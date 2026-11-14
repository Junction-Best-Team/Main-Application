"""Explicit dedicated local-container restart check for an existing chat and basket."""

import argparse
import os
import subprocess
import time
from uuid import uuid4

import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--container", required=True, help="Dedicated local verification container to restart"
    )
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--conversation", required=True)
    parser.add_argument("--proposal", required=True)
    args = parser.parse_args()
    with httpx.Client(
        base_url=args.base_url, timeout=120, headers={"Origin": args.base_url}
    ) as client:
        login = client.post(
            "/api/login", json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]}
        )
        login.raise_for_status()
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        chat = client.get("/api/conversations/" + args.conversation)
        chat.raise_for_status()
        purchase = client.get("/api/purchases/" + args.proposal)
        purchase.raise_for_status()
        payload = {
            "proposal_id": args.proposal,
            "revision": purchase.json()["revision"],
            "idempotency_key": str(uuid4()),
        }
        # This script explicitly confirms a mock order in a dedicated verification DB.
        receipt = client.post("/api/purchases/" + args.proposal + "/confirm", json=payload)
        receipt.raise_for_status()
        assert receipt.json()["status"] == "accepted_mock", (
            "Changed terms require a fresh customer review"
        )
        subprocess.run(["docker", "restart", args.container], check=True, capture_output=True)
        for _ in range(30):
            try:
                if client.get("/health/ready").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Container failed to become ready after restart")
        assert client.get("/api/session").status_code == 200
        assert (
            client.get("/api/conversations/" + args.conversation).json()["messages"]
            == chat.json()["messages"]
        )
        assert (
            client.post("/api/purchases/" + args.proposal + "/confirm", json=payload).json()
            == receipt.json()
        )
        print("Conversation, session, confirmation and identical mock receipt survived restart.")


if __name__ == "__main__":
    main()
