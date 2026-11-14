"""Authenticated chat demo. Customer confirmation remains an explicit product action."""

import argparse
import json
import os
import time
from uuid import uuid4

import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conversation", help="Continue a saved conversation UUID")
    parser.add_argument("--message", default="I need ingredients for 200 portions of carbonara.")
    args = parser.parse_args()
    base = os.getenv("DEMO_BASE_URL", "http://localhost:8000").rstrip("/")
    with httpx.Client(base_url=base, timeout=120, headers={"Origin": base}) as client:
        login = client.post(
            "/api/login", json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]}
        )
        login.raise_for_status()
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        if args.conversation:
            cid = args.conversation
        else:
            created = client.post(
                "/api/conversations",
                json={"title": "Carbonara for 200", "idempotency_key": str(uuid4())},
            )
            created.raise_for_status()
            cid = created.json()["id"]
        saved = client.get("/api/conversations/" + cid)
        saved.raise_for_status()
        retry = saved.json().get("retry_message")
        response = client.post(
            "/api/conversations/" + cid + "/messages",
            json=retry
            or {
                "text": args.message,
                "idempotency_key": str(uuid4()),
            },
        )
        response.raise_for_status()
        deadline = time.monotonic() + 300
        while response.json()["busy"] and time.monotonic() < deadline:
            time.sleep(2)
            response = client.get("/api/conversations/" + cid)
            response.raise_for_status()
        if response.json()["busy"] or response.json()["retry_message"]:
            raise RuntimeError("Response pending or interrupted; reopen the saved conversation to retry.")
        print(
            json.dumps(
                {
                    "conversation_url": base + "/conversations/" + cid,
                    "message": response.json()["messages"][-1],
                    "purchases": response.json()["purchases"],
                    "next": "Open the product to review exact terms and explicitly confirm. Orders remain mocks.",
                },
                default=str,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
