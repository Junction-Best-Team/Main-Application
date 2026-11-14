from urllib.parse import urlparse
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from aimo.config import settings
from aimo.db import Problem
from aimo.schemas import (
    CommitRequest,
    CommitResponse,
    LookupRequest,
    LookupResponse,
    OrderResponse,
    PolicyResponse,
    PrepareRequest,
    ProductResponse,
    ProposalResponse,
    SearchRequest,
    SearchResponse,
)
from aimo.service import Service


def build_mcp(service: Service):
    host = urlparse(settings().public_base_url).netloc
    mcp = FastMCP(
        "Valio Aimo seller gateway",
        instructions="Eight buyer-scoped tools. Buyer approval uses a separate authenticated inbox. All orders are mock acceptance; no stock reservation.",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            allowed_hosts=[host, "localhost:*", "127.0.0.1:*"],
            allowed_origins=[settings().public_base_url],
        ),
    )

    def identity(ctx):
        request = ctx.request_context.request
        if request is None:
            raise ValueError("Authenticated HTTP transport is required")
        actor = getattr(request.state, "agent_identity", None)
        if actor is None:
            raise ValueError("Authenticated HTTP transport is required")
        return actor

    async def call(ctx, operation, *args):
        try:
            import anyio

            actor = identity(ctx)
            return await anyio.to_thread.run_sync(getattr(service, operation), actor, *args)
        except Problem as e:
            raise ValueError(f"{e.code}: {e.message}") from None

    @mcp.tool(structured_output=True)
    async def search_products(request: SearchRequest, ctx: Context) -> SearchResponse:
        """Discover candidates using hybrid retrieval and explicit dietary evidence; no live stock claim."""
        return SearchResponse.model_validate(await call(ctx, "search_products", request))

    @mcp.tool(structured_output=True)
    async def get_product(product_id: str, ctx: Context) -> ProductResponse:
        """Inspect supported product attributes, packaging and evidence provenance."""
        return ProductResponse.model_validate(await call(ctx, "get_product", product_id))

    @mcp.tool(structured_output=True)
    async def get_purchase_policy(ctx: Context) -> PolicyResponse:
        """Read the calling agent's effective versioned policy. Cannot edit authority."""
        return PolicyResponse.model_validate(await call(ctx, "get_purchase_policy"))

    @mcp.tool(structured_output=True)
    async def check_price_and_availability(request: LookupRequest, ctx: Context) -> LookupResponse:
        """Look up current commercial evidence for at most 50 shortlisted IDs and a delivery date."""
        return LookupResponse.model_validate(
            await call(ctx, "check_price_and_availability", request)
        )

    @mcp.tool(structured_output=True)
    async def prepare_order(request: PrepareRequest, ctx: Context) -> ProposalResponse:
        """Prepare an immutable revision; evaluate policy, quantities, price, tax and fulfillment. No order is placed."""
        return ProposalResponse.model_validate(await call(ctx, "prepare_order", request))

    @mcp.tool(structured_output=True)
    async def get_proposal(proposal_id: UUID, ctx: Context) -> ProposalResponse:
        """Resume a paused mission by checking decision, expiry and next action. No human wait in this call."""
        return ProposalResponse.model_validate(await call(ctx, "get_proposal", proposal_id))

    @mcp.tool(structured_output=True)
    async def commit_order(request: CommitRequest, ctx: Context) -> CommitResponse:
        """Revalidate and atomically create a mock receipt, or return a revised proposal. Retry with the same key."""
        return CommitResponse.model_validate(await call(ctx, "commit_order", request))

    @mcp.tool(structured_output=True)
    async def get_order(order_id: UUID, ctx: Context) -> OrderResponse:
        """Retrieve an authorized persistent mock receipt; no real supplier order or reservation exists."""
        return OrderResponse.model_validate(await call(ctx, "get_order", order_id))

    return mcp
