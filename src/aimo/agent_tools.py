"""Typed internal tools. The model has no human decision or commitment operation."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable
from uuid import UUID

from pydantic import Field, TypeAdapter, ValidationError

from aimo.chat_schemas import AgentTurn, MealPlan
from aimo.db import Problem, fingerprint
from aimo.schemas import (
    Amount,
    LookupRequest,
    LookupResponse,
    Model,
    OrderResponse,
    PolicyResponse,
    PrepareRequest,
    ProductResponse,
    ProposalResponse,
    PurchaseRequest,
    SearchRequest,
    SearchResponse,
)


class EmptyRequest(Model):
    pass


class ProductRequest(Model):
    product_id: str = Field(min_length=1, max_length=40)


class ProposalRequest(Model):
    proposal_id: UUID


class OrderRequest(Model):
    order_id: UUID


@dataclass(frozen=True)
class ToolSpec:
    request: type[Model]
    description: str
    handler: Callable

    def schema(self, name):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": self.description,
                "parameters": self.request.model_json_schema(),
            },
        }


class ToolSession:
    """Fresh per turn; persistent preparation deduplication belongs to Service."""

    def __init__(self, identity, service):
        self.identity = dict(identity)
        self.service = service
        self.preparation_key = "chat-" + fingerprint({"turn": identity["_turn_id"]})
        self.plan = None
        self.proposal = None
        self.receipt = None
        self.prepared_digest = None
        self.products = {}
        self.registry = {
            "search_products": ToolSpec(
                SearchRequest, "Find candidates, not suitability guarantees.", self.search
            ),
            "get_product": ToolSpec(
                ProductRequest, "Read product IDs, units and catalog evidence.", self.product
            ),
            "get_purchase_policy": ToolSpec(
                EmptyRequest, "Read current buyer scope and limits.", self.policy
            ),
            "check_price_and_availability": ToolSpec(
                LookupRequest,
                "Read supplier evidence for a shortlist and delivery date.",
                self.lookup,
            ),
            "publish_meal_plan": ToolSpec(
                MealPlan,
                "Publish total required quantities for the requested portions. "
                "Keep recipe basis/assumptions in notes; no pack rounding or purchase authority.",
                self.publish,
            ),
            "prepare_order": ToolSpec(
                PurchaseRequest,
                "Prepare the complete published plan through purchasing validation. "
                "Server assigns the retry key. Does not authorize or commit a purchase.",
                self.prepare,
            ),
            "get_proposal": ToolSpec(
                ProposalRequest, "Read an existing scoped basket and its state.", self.read_proposal
            ),
            "get_order": ToolSpec(OrderRequest, "Read an existing saved mock receipt.", self.order),
        }

    @property
    def definitions(self):
        return [tool.schema(name) for name, tool in self.registry.items()]

    @staticmethod
    def checked(model, value):
        try:
            return model.model_validate(value).model_dump(mode="json")
        except ValidationError:
            raise Problem(
                "TOOL_RESULT_INVALID",
                "The purchasing tool returned invalid data. Retry later.",
                502,
            ) from None

    def invoke(self, name, arguments):
        tool = self.registry.get(name)
        if tool is None:
            raise Problem(
                "TOOL_NOT_ALLOWED",
                "This operation is unavailable to the assistant. "
                "Use the authenticated customer confirmation control to buy.",
                422,
            )
        try:
            request = tool.request.model_validate_json(arguments)
        except ValidationError:
            raise Problem(
                "INVALID_TOOL_ARGUMENTS",
                "Use the tool's typed fields. "
                "Identity, permissions and preparation retry keys cannot be model arguments.",
                422,
            ) from None
        return tool.handler(request)

    def scoped(self, model, value):
        result = self.checked(model, value)
        expected = {"buyer_id": self.identity["buyer_id"], "agent_id": self.identity["id"]}
        if any(field in result and result[field] != value for field, value in expected.items()):
            raise Problem(
                "TOOL_RESULT_INVALID", "The tool returned data outside this agent scope.", 502
            )
        return result

    def search(self, request):
        return self.checked(SearchResponse, self.service.search_products(self.identity, request))

    def product(self, request):
        result = self.checked(
            ProductResponse, self.service.get_product(self.identity, request.product_id)
        )
        if result["id"] != request.product_id:
            raise Problem("TOOL_RESULT_INVALID", "The tool returned a different product ID.", 502)
        self.products[request.product_id] = result
        return result

    def policy(self, request):
        return self.scoped(PolicyResponse, self.service.get_purchase_policy(self.identity))

    def lookup(self, request):
        return self.checked(
            LookupResponse, self.service.check_price_and_availability(self.identity, request)
        )

    def publish(self, plan):
        if self.prepared_digest is not None and plan != self.plan:
            raise Problem("MEAL_PLAN_LOCKED", "Request recipe changes in a new customer message.")
        if self.plan:
            previous = Counter(i.name.strip().casefold() for i in self.plan.ingredients)
            current = Counter(i.name.strip().casefold() for i in plan.ingredients)
            if previous - current:
                raise Problem(
                    "INCOMPLETE_MEAL_PLAN",
                    "Keep every previously required ingredient. "
                    "Explain shortages and ask the customer before changing the recipe.",
                    422,
                )
        for ingredient in plan.ingredients:
            try:
                TypeAdapter(Amount).validate_python(ingredient.amount)
            except ValidationError:
                raise Problem(
                    "INVALID_MEAL_QUANTITY",
                    "Ingredient amounts must be positive, finite "
                    "and within 14 digits and 4 decimal places.",
                    422,
                ) from None
            if ingredient.product_id and ingredient.product_id not in self.products:
                raise Problem(
                    "PRODUCT_NOT_VERIFIED",
                    "Read every selected product with get_product first.",
                    422,
                )
        self.plan = plan.model_copy(deep=True)
        return {"meal_plan": self.plan.model_dump(mode="json"), "purchase_authorized": False}

    def prepare(self, request):
        if not self.plan or any(not item.product_id for item in self.plan.ingredients):
            raise Problem(
                "INCOMPLETE_MEAL_PLAN",
                "Match every ingredient before preparing a meal basket.",
                422,
            )
        required = {}
        for item in self.plan.ingredients:
            key = (item.product_id, item.unit)
            required[key] = required.get(key, Decimal(0)) + Decimal(item.amount)
        actual = {(line.product_id, line.unit): line.amount for line in request.lines}
        if required != actual:
            raise Problem(
                "MEAL_BASKET_MISMATCH",
                "Include exactly the published ingredient totals and units. "
                "Combine duplicate SKUs; purchasing tools perform pack rounding.",
                422,
            )
        digest = fingerprint(request.model_dump(mode="json"))
        if self.prepared_digest is not None and self.prepared_digest != digest:
            raise Problem("IDEMPOTENCY_CONFLICT", "This turn already prepared different terms.")
        result = self.scoped(
            ProposalResponse,
            self.service.prepare_order(
                self.identity,
                PrepareRequest(**request.model_dump(), idempotency_key=self.preparation_key),
            ),
        )
        self.proposal, self.prepared_digest = result, digest
        return result

    def read_proposal(self, request):
        result = self.scoped(
            ProposalResponse, self.service.get_proposal(self.identity, request.proposal_id)
        )
        if result["proposal_id"] != str(request.proposal_id):
            raise Problem("TOOL_RESULT_INVALID", "The tool returned a different proposal ID.", 502)
        if self.prepared_digest is None or self.proposal["proposal_id"] == result["proposal_id"]:
            self.proposal = result
        return result

    def order(self, request):
        result = self.scoped(OrderResponse, self.service.get_order(self.identity, request.order_id))
        if result["order_id"] != str(request.order_id):
            raise Problem("TOOL_RESULT_INVALID", "The tool returned a different order ID.", 502)
        self.receipt = result
        return result

    def result(self, narrative=""):
        notice = ""
        if self.proposal:
            if self.proposal.get("order_id"):
                notice = "This purchase has a saved mock receipt. No supplier order was placed."
            elif self.proposal["policy_outcome"] in ("denied", "needs_resolution"):
                notice = "The basket is blocked: " + "; ".join(
                    reason["message"] for reason in self.proposal["reasons"]
                )
            else:
                notice = (
                    "Review the verified basket and exact revision, then use the Confirm "
                    "purchase button. No supplier order has been placed."
                )
        elif self.receipt:
            notice = "Accepted by demo order service. No supplier order or inventory reservation."
        if notice:
            # Preserve the authoritative state notice even with a long model narrative.
            narrative = narrative[: max(0, 20_000 - len(notice) - 2)].strip()
        text = "\n\n".join(part for part in (narrative, notice) if part)
        return AgentTurn(
            text=(text or "Review the recipe and resolve missing ingredient evidence.")[:20_000],
            meal_plan=self.plan,
            proposal_id=self.proposal["proposal_id"] if self.proposal else None,
        )
