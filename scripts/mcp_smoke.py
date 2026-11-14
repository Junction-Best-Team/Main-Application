"""Exercise the real official SDK over authenticated stateless HTTP; no custom buyer agent."""

import asyncio
import json
import os
from datetime import date, timedelta
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    load_dotenv()
    base = os.getenv("DEMO_BASE_URL", "http://localhost:8000")
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + os.environ["DEMO_AGENT_TOKEN"]}
    ) as http:
        async with streamable_http_client(base + "/mcp/", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {
                    "search_products",
                    "get_product",
                    "get_purchase_policy",
                    "check_price_and_availability",
                    "prepare_order",
                    "get_proposal",
                    "commit_order",
                    "get_order",
                }
                result = await session.call_tool("get_purchase_policy", {})
                assert not result.isError
                assert result.structuredContent["buyer_id"] == "demo-hotel"
                search = await session.call_tool(
                    "search_products",
                    {
                        "request": {
                            "query": "464306",
                            "requirements": {"lactose_free": True},
                            "limit": 5,
                        }
                    },
                )
                assert not search.isError
                assert search.structuredContent["products"][0]["id"] == "464306"
                product = await session.call_tool("get_product", {"product_id": "464306"})
                assert not product.isError and product.structuredContent["id"] == "464306"
                purchase = {
                    "request_id": "MCP autonomous smoke",
                    "destination": "hotel-helsinki",
                    "delivery_date": str(date.today() + timedelta(days=2)),
                    "lines": [{"product_id": "464306", "amount": "10", "unit": "L"}],
                }
                p = await session.call_tool("prepare_order", {"request": purchase})
                assert not p.isError, p
                proposal = p.structuredContent
                assert proposal["policy_outcome"] == "ready_to_commit"
                lookup = await session.call_tool(
                    "check_price_and_availability",
                    {
                        "request": {
                            "product_ids": ["464306"],
                            "delivery_date": purchase["delivery_date"],
                        }
                    },
                )
                assert not lookup.isError and "464306" in lookup.structuredContent["products"]
                resumed = await session.call_tool(
                    "get_proposal", {"proposal_id": proposal["proposal_id"]}
                )
                assert (
                    not resumed.isError
                    and resumed.structuredContent["revision"] == proposal["revision"]
                )
                payload = {
                    "proposal_id": proposal["proposal_id"],
                    "revision": proposal["revision"],
                    "idempotency_key": str(uuid4()),
                }
                receipt = await session.call_tool("commit_order", {"request": payload})
                assert not receipt.isError, receipt
                retry = await session.call_tool("commit_order", {"request": payload})
                assert receipt.structuredContent == retry.structuredContent
                got = await session.call_tool(
                    "get_order", {"order_id": receipt.structuredContent["order_id"]}
                )
                assert got.structuredContent == receipt.structuredContent
                print(
                    json.dumps(
                        {
                            "tools": len(tools.tools),
                            "status": receipt.structuredContent["status"],
                            "same_receipt_on_retry": True,
                        }
                    )
                )


if __name__ == "__main__":
    asyncio.run(main())
